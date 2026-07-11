"""
compute.py — SP-05: turn each matched line into a REAL emissions number,
with a full audit trail. Uses Decimal for exact, audit-grade math.

emissions (kgCO2e) = quantity (base unit) × emission factor (per base unit)
"""

import csv
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from ingest import ingest_csv, ingest_pdf
from extract import extract_with_rules, extract_with_llm
from normalize import normalize_line
from match import load_factors, exact_match, semantic_match, ACCEPT_SCORE, ESCALATE_SCORE

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"


def to_decimal(value):
    """Make an exact Decimal from a number, safely (via string to avoid float error)."""
    if value is None:
        return None
    return Decimal(str(value))          # str() first -> no binary float mistake


def compute_emissions(quantity, factor_value):
    """emissions = quantity × factor, as exact Decimal, rounded to 3 dp."""
    q = to_decimal(quantity)
    f = to_decimal(factor_value)
    if q is None or f is None:
        return None
    result = q * f
    return result.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)   # 3 decimals


def main():
    print("Loading + embedding factor library...")
    factors = load_factors()
    # quick lookup of a factor's full info by its id
    factor_by_id = {f["factor_id"]: f for f in factors}
    print(f"  {len(factors)} factors ready.\n")

    records = []
    records += ingest_csv(DATA_DIR / "electricity_bills.csv")
    records += ingest_csv(DATA_DIR / "diesel_invoices.csv")
    records += ingest_csv(DATA_DIR / "erp_spend_export.csv")
    records += ingest_pdf(DATA_DIR / "electricity_bill_sample.pdf")

    results = []          # we'll collect finished, audit-ready records here
    total = Decimal("0")  # running total of accepted emissions

    print("\n========== SP-05: COMPUTED EMISSIONS ==========\n")
    for r in records:
        if r["source_type"] == "csv":
            extracted = extract_with_rules(r)
            line_id = r["raw"].get("line_id", "?")
            source_ref = f"{r['source_file']} row {r['source_row']}"
        else:
            extracted = extract_with_llm(r["raw_text"])
            line_id = f"PDF-p{r['source_page']}"
            source_ref = f"{r['source_file']} page {r['source_page']}"
        norm = normalize_line(extracted)

        # skip noise
        if norm.activity == "unknown" or norm.unit is None:
            print(f"{line_id:12} REFUSE (no clear activity/unit)")
            continue

        # match (exact first, else semantic)
        fac = exact_match(norm, factors)
        if fac:
            score, how = 1.0, "exact"
        else:
            fac, score = semantic_match(norm, factors)
            how = "semantic"

        # decide
        if how == "exact" or score >= ACCEPT_SCORE:
            emissions = compute_emissions(norm.quantity, fac["value"])
            total += emissions
            # build the FULL audit-ready record
            record = {
                "line_id":        line_id,
                "activity":       norm.activity,
                "quantity":       norm.quantity,
                "unit":           norm.unit,
                "factor_id":      fac["factor_id"],
                "factor_value":   fac["value"],
                "emissions_kgco2e": str(emissions),   # store as string = exact
                "match_type":     how,
                "source":         source_ref,          # <-- the audit trail
            }
            results.append(record)
            print(f"{line_id:12} {norm.activity:12} {str(norm.quantity):>10} {norm.unit:5} "
                  f"× {fac['value']:<7} = {str(emissions):>12} kgCO2e   [{fac['factor_id']}, {how}]")
        else:
            print(f"{line_id:12} {norm.activity:12} -> ⚠️ ESCALATE (score {score:.2f}) - not counted")

    # ----- summary -----
    total_tonnes = (total / Decimal("1000")).quantize(Decimal("0.001"))
    print("\n-------------------------------------------")
    print(f"Lines counted : {len(results)}")
    print(f"TOTAL emissions: {total} kgCO2e  =  {total_tonnes} tCO2e")

    # save the audit-ready results to a file
    out = BASE_DIR / "computed_emissions.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)
    print(f"Saved audit-ready results -> {out.name}")


if __name__ == "__main__":
    main()