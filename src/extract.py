"""
extract.py — SP-02 (hardened): pull real fields from each record.
Method A: RULES for CSV rows.   Method B: LLM (Ollama) for free text.
Hardened so ONE bad row never crashes the whole run.
"""

import re
from typing import Optional
from pathlib import Path
from pydantic import BaseModel, Field

from ingest import ingest_csv, ingest_pdf

DATA_DIR = Path(__file__).parent.parent / "data"
OLLAMA_MODEL = "qwen3:1.7b"   # a fast small model from your `ollama list`


# ---------- the clean shape we want ----------
class ExtractedLine(BaseModel):
    activity: str = Field(description="electricity, diesel, petrol, natural gas, lpg, or unknown")
    quantity: Optional[float] = Field(default=None, description="the numeric amount used")
    unit: Optional[str] = Field(default=None, description="unit like kWh, MWh, litre, KL, m3")
    period: Optional[str] = Field(default=None, description="billing period or date, if present")


# ================= METHOD A: RULES =================
QTY_COLUMNS    = ["Units Consumed", "kWh", "Energy (Units)", "Net Units Billed", "Consumption", "Quantity"]
UNIT_COLUMNS   = ["Unit", "Qty Unit"]
PERIOD_COLUMNS = ["Billing Period", "Invoice Date"]
DESC_COLUMNS   = ["Product", "GL Description"]

# specific keywords only — bare "gas" removed to avoid "gasket"
ACTIVITY_KEYWORDS = {
    "electricity": ["electricity", "kwh", "power", "energy charges"],
    "diesel":      ["diesel", "hsd"],
    "petrol":      ["petrol", "gasoline", "motor spirit"],
    "natural gas": ["natural gas", "png", "piped natural gas"],
    "lpg":         ["lpg", "cooking gas", "propane"],
}

def find_first(raw, columns):
    """Return the value of the first column that is present and not empty."""
    for col in columns:
        if col in raw and raw[col] not in (None, ""):
            return raw[col]
    return None

def guess_activity(text):
    """Whole-word keyword match; 'gas' won't match inside 'gasket'."""
    if not text:
        return "unknown"
    low = str(text).lower()
    for activity, words in ACTIVITY_KEYWORDS.items():
        for w in words:
            if re.search(r"\b" + re.escape(w) + r"\b", low):   # \b = word boundary
                return activity
    return "unknown"

# words that suggest "this IS energy/fuel, just unclear which one" -> escalate, don't refuse
AMBIGUOUS_HINTS = ["fuel", "energy", "consumption", "utility"]

def looks_ambiguous(record):
    """True if an 'unknown' line still smells like energy/fuel (should escalate)."""
    raw = record.get("raw", {})
    text = " ".join(str(v) for v in raw.values()).lower()
    return any(hint in text for hint in AMBIGUOUS_HINTS)

def safe_float(value):
    """Turn a value into a number safely. Handles '1,234' and returns None on junk."""
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())   # remove commas/spaces
    except (ValueError, TypeError):
        return None                                          # not a number -> None, no crash

def extract_with_rules(record):
    raw = record.get("raw", {})
    source = record.get("source_file", "")

    if source == "electricity_bills.csv":
        activity = "electricity"
    elif source == "diesel_invoices.csv":
        activity = "diesel"
    else:
        activity = guess_activity(find_first(raw, DESC_COLUMNS))

    return ExtractedLine(
        activity=activity,
        quantity=safe_float(find_first(raw, QTY_COLUMNS)),   # safe number
        unit=find_first(raw, UNIT_COLUMNS),
        period=(str(find_first(raw, PERIOD_COLUMNS))
                if find_first(raw, PERIOD_COLUMNS) is not None else None),
    )


# ================= METHOD B: LLM via Ollama =================
def extract_with_llm(text):
    from ollama import chat
    prompt = (
        "You are reading one energy or fuel bill line.\n"
        "Extract: activity (electricity, diesel, petrol, natural gas, lpg, or unknown), "
        "quantity (a number), unit, and period.\n"
        "If a field is not present, use null. Return JSON only.\n\n"
        f"TEXT:\n{text}"
    )
    try:
        response = chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            format=ExtractedLine.model_json_schema(),
            options={"temperature": 0},
        )
        # handle both new (.message.content) and old (["message"]["content"]) styles
        content = getattr(response, "message", None)
        content = content.content if content is not None else response["message"]["content"]
        return ExtractedLine.model_validate_json(content)
    except Exception as e:
        # never crash — return a safe "unknown" line and record why
        print(f"   [LLM fallback] could not extract: {e}")
        return ExtractedLine(activity="unknown", quantity=None, unit=None, period=None)


# ================= RUN =================
def main():
    records = []
    records += ingest_csv(DATA_DIR / "electricity_bills.csv")
    records += ingest_csv(DATA_DIR / "diesel_invoices.csv")
    records += ingest_csv(DATA_DIR / "erp_spend_export.csv")
    records += ingest_pdf(DATA_DIR / "electricity_bill_sample.pdf")

    print("\n========== METHOD A: RULES (CSV rows) ==========\n")
    for r in records:
        if r["source_type"] == "csv":
            line = extract_with_rules(r)
            print(f"{r['raw'].get('line_id','?'):10} -> activity={line.activity:12} "
                  f"qty={line.quantity} unit={line.unit} period={line.period}")

    print("\n========== METHOD B: LLM via Ollama (PDF text) ==========\n")
    for r in records:
        if r["source_type"] == "pdf":
            line = extract_with_llm(r["raw_text"])
            print(f"PDF page {r['source_page']} -> {line.model_dump()}")


if __name__ == "__main__":
    main()