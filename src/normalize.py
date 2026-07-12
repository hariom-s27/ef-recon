"""
normalize.py — SP-03: make every extracted line CONSISTENT.

Two jobs:
  1) Convert quantity to ONE base unit  (electricity->kWh, fuel->litre, gas->m3)
  2) Clean labels (lowercase, trim) so 'Electricity' == 'electricity'

We KEEP the original quantity+unit too, so the audit trail shows both.
"""

from typing import Optional
from pydantic import BaseModel, Field

from ingest import ingest_csv, ingest_pdf
from extract import extract_with_rules, extract_with_llm, ExtractedLine
from paths import DATA_DIR


# ---------- the clean, normalized shape ----------
class NormalizedLine(BaseModel):
    activity: str
    # what we will actually use downstream:
    quantity: Optional[float] = Field(default=None, description="amount in the BASE unit")
    unit: Optional[str] = Field(default=None, description="the base unit (kWh, litre, m3)")
    period: Optional[str] = None
    # keep the originals for the audit trail:
    original_quantity: Optional[float] = None
    original_unit: Optional[str] = None
    note: Optional[str] = None   # anything worth flagging


# ---------- 1) UNIT CONVERSION TABLE ----------
# key = unit as written (lowercased) -> (base unit, multiply factor)
UNIT_CONVERSIONS = {
    "kwh":   ("kWh", 1),
    "mwh":   ("kWh", 1000),
    "gj":    ("kWh", 277.778),     # 1 GJ = 277.778 kWh  (BRSR reports energy in GJ)
    "l":     ("litre", 1),
    "litre": ("litre", 1),
    "litres":("litre", 1),
    "kl":    ("litre", 1000),
    "gallon":("litre", 3.785),     # US gallon -> litre
    "gallons":("litre", 3.785),
    "m3":    ("m3", 1),
    "m³":    ("m3", 1),
    "sm3":   ("m3", 1),            # standard cubic metre (gas)
    "kg":    ("kg", 1),            # kept as-is; whether it's usable is decided in match
    "tonne": ("tonne", 1),
    "mt":    ("tonne", 1),
    "t":     ("tonne", 1),
    "units": ("kWh", 1),      # "Units" on an Indian electricity bill = kWh
    "unit":  ("kWh", 1),
}

def normalize_unit(quantity, unit):
    """Return (quantity_in_base_unit, base_unit, note)."""
    if quantity is None or unit is None:
        return quantity, unit, "missing quantity or unit"
    key = str(unit).strip().lower()
    if key in UNIT_CONVERSIONS:
        base_unit, factor = UNIT_CONVERSIONS[key]
        return quantity * factor, base_unit, None
    # truly unknown unit -> keep, flag for review (do NOT guess)
    return quantity, unit, f"unknown unit '{unit}' - left as-is"


def clean_text(value):
    """Lowercase + trim, so labels are consistent. Handles None safely."""
    if value is None:
        return None
    return str(value).strip().lower()


# ---------- ACTIVITY ALIASES (deterministic — runs before trusting the LLM) ----------
# maps messy activity/header text -> canonical activity. Sourced from your factor aliases.
ACTIVITY_ALIASES = {
    "electricity": ["electricity", "power", "grid", "units consumed", "units",
                    "energy charges", "energy (units)", "energy", "consumption",
                    "discom", "net units billed", "total units", "ht supply", "grid import"],
    "diesel":      ["diesel", "hsd", "high speed diesel", "dg fuel", "genset fuel",
                    "generator fuel", "dg set", "d.g. set"],
    "petrol":      ["petrol", "gasoline", "motor spirit"],
    "natural gas": ["natural gas", "png", "piped natural gas"],
    "lpg":         ["lpg", "liquefied petroleum gas", "cooking gas", "propane"],
    "cng":         ["cng", "compressed natural gas"],
    "coal":        ["coal", "steam coal", "thermal coal"],
}

def canonical_activity(text):
    """Map any activity/header text to a canonical activity, or None if no match."""
    if not text:
        return None
    low = str(text).lower().strip()
    # longest aliases first so 'natural gas' wins over 'gas'
    for activity, aliases in ACTIVITY_ALIASES.items():
        for alias in sorted(aliases, key=len, reverse=True):
            if alias in low:
                return activity
    return None


# fuels/materials NOT in our factor library -> must escalate, never match
UNSUPPORTED_FUELS = ["furnace oil", "pet coke", "petcoke", "hfo", "heavy fuel oil",
                     "biomass", "briquette", "briquettes", "lignite", "naphtha", "bagasse"]

def has_unsupported_fuel(text):
    """True if the text names a fuel we have no factor for -> honest escalation."""
    low = str(text or "").lower()
    return any(f in low for f in UNSUPPORTED_FUELS)


# ---------- 2) NORMALIZE ONE EXTRACTED LINE ----------
def normalize_line(extracted: ExtractedLine) -> NormalizedLine:
    base_qty, base_unit, note = normalize_unit(extracted.quantity, extracted.unit)

    # deterministic alias fix first; fall back to the LLM's guess only if no alias matches
    fixed_activity = canonical_activity(extracted.activity) or clean_text(extracted.activity)

    return NormalizedLine(
        activity=fixed_activity,
        quantity=base_qty,
        unit=base_unit,
        period=extracted.period,
        original_quantity=extracted.quantity,         # keep the original
        original_unit=extracted.unit,                 # keep the original
        note=note,
    )


# ---------- RUN ----------
def main():
    records = []
    records += ingest_csv(DATA_DIR / "electricity_bills.csv")
    records += ingest_csv(DATA_DIR / "diesel_invoices.csv")
    records += ingest_csv(DATA_DIR / "erp_spend_export.csv")
    records += ingest_pdf(DATA_DIR / "electricity_bill_sample.pdf")

    print("\n========== SP-03: NORMALIZED LINES ==========\n")
    for r in records:
        # extract first (rules for CSV, LLM for PDF)
        if r["source_type"] == "csv":
            extracted = extract_with_rules(r)
            line_id = r["raw"].get("line_id", "?")
        else:
            try:
                extracted = extract_with_llm(r["raw_text"])
            except Exception as e:
                print("LLM error:", e); continue
            line_id = f"PDF-p{r['source_page']}"

        # then normalize
        norm = normalize_line(extracted)

        flag = f"   [NOTE: {norm.note}]" if norm.note else ""
        print(f"{line_id:12} {norm.activity:12} "
              f"{str(norm.original_quantity):>10} {str(norm.original_unit):<5} "
              f"-> {str(norm.quantity):>12} {norm.unit}{flag}")


if __name__ == "__main__":
    main()