"""
normalize.py — SP-03: make every extracted line CONSISTENT.

Two jobs:
  1) Convert quantity to ONE base unit  (electricity->kWh, fuel->litre, gas->m3)
  2) Clean labels (lowercase, trim) so 'Electricity' == 'electricity'

We KEEP the original quantity+unit too, so the audit trail shows both.
"""

from typing import Optional
from pathlib import Path
from pydantic import BaseModel, Field

from ingest import ingest_csv, ingest_pdf
from extract import extract_with_rules, extract_with_llm, ExtractedLine

DATA_DIR = Path(__file__).parent.parent / "data"


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
# key = (unit as written, lowercased)  ->  (base unit, multiply by this)
UNIT_CONVERSIONS = {
    "kwh":   ("kWh", 1),        # already base
    "mwh":   ("kWh", 1000),     # 1 MWh = 1000 kWh
    "l":     ("litre", 1),      # already base
    "litre": ("litre", 1),
    "litres":("litre", 1),
    "kl":    ("litre", 1000),   # 1 kilolitre = 1000 litre
    "m3":    ("m3", 1),         # already base
    "m³":    ("m3", 1),
}

def normalize_unit(quantity, unit):
    """Return (quantity_in_base_unit, base_unit, note)."""
    if quantity is None or unit is None:
        return quantity, unit, "missing quantity or unit"

    key = str(unit).strip().lower()          # clean the unit text
    if key in UNIT_CONVERSIONS:
        base_unit, factor = UNIT_CONVERSIONS[key]
        return quantity * factor, base_unit, None
    else:
        # unknown unit -> don't guess; flag it for review
        return quantity, unit, f"unknown unit '{unit}' - left as-is"


def clean_text(value):
    """Lowercase + trim, so labels are consistent. Handles None safely."""
    if value is None:
        return None
    return str(value).strip().lower()


# ---------- 2) NORMALIZE ONE EXTRACTED LINE ----------
def normalize_line(extracted: ExtractedLine) -> NormalizedLine:
    base_qty, base_unit, note = normalize_unit(extracted.quantity, extracted.unit)

    return NormalizedLine(
        activity=clean_text(extracted.activity),      # 'Electricity' -> 'electricity'
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