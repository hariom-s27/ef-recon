"""
compute.py — SP-05: turn each matched line into a REAL emissions number,
with a full audit trail. Uses Decimal for exact, audit-grade math.

emissions (kgCO2e) = quantity (base unit) × emission factor (per base unit)
"""

import csv
from decimal import Decimal, ROUND_HALF_UP

from ingest import ingest_csv, ingest_pdf
from extract import extract_with_rules, extract_with_llm
from normalize import normalize_line
from match import load_factors, match_line, resolve_decision
from paths import DATA_DIR, OUTPUT_DIR, ensure_output_dir
from totals import factor_bases, sum_by_basis, report_lines


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
    counted = []          # accepted emissions + their gas/GWP basis (summed per basis, ADR-002)
    bases = factor_bases()

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

        # match + decide via the ONE policy
        raw_text = " ".join(str(v) for v in r.get("raw", {}).values()) if r["source_type"] == "csv" \
            else r.get("raw_text", "")
        decision, fac = match_line(norm, factors, raw_text=raw_text)
        decision = resolve_decision(decision, r)
        how = "exact"

        if decision == "refuse":
            print(f"{line_id:12} REFUSE (no clear activity/unit)")
        elif decision == "accept":
            emissions = compute_emissions(norm.quantity, fac["value"])
            gas, gwp = bases.get(fac["factor_id"], ("", ""))
            counted.append({"emissions_kg": emissions, "gas_basis": gas, "gwp_basis": gwp})
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
            print(f"{line_id:12} {norm.activity:12} -> ⚠️ ESCALATE - not counted")

    # ----- summary -----
    totals = sum_by_basis(counted)
    total_tonnes = (totals["total_kg"] / Decimal("1000")).quantize(Decimal("0.001"))
    print("\n-------------------------------------------")
    print(f"Lines counted : {len(results)}")
    print(f"TOTAL emissions (plain sum): {totals['total_kg']} kg  =  {total_tonnes} t")
    print("\n".join(report_lines(totals)))

    # save the audit-ready results to a file
    out = ensure_output_dir(OUTPUT_DIR) / "computed_emissions.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)
    print(f"Saved audit-ready results -> {out.name}")


if __name__ == "__main__":
    main()