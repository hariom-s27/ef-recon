"""
dedup.py — SP-08: find bills entered twice (duplicates) and count them once.
Uses a FINGERPRINT (a match key) + blocking: same fingerprint = same bill.
This is O(n) — one pass — so it scales to millions of rows.
"""

from decimal import Decimal
from pathlib import Path

from paths import DATA_DIR, OUTPUT_DIR
from ingest import ingest_csv, ingest_pdf
from extract import extract_with_rules, extract_with_llm, looks_ambiguous
from normalize import normalize_line
from match import load_factors, exact_match, semantic_match, ACCEPT_SCORE, ESCALATE_SCORE
from compute import compute_emissions


# ---------- build a fingerprint for one line ----------
def fingerprint(norm, site):
    """
    A short string that is the SAME for two copies of the same bill.
    We use: activity + unit + quantity + period + site.
    If two lines make the same fingerprint, they're the same bill.
    """
    return f"{norm.activity}|{norm.unit}|{norm.quantity}|{norm.period}|{site}"


def get_site(record):
    """Pull a site name from the raw record (electricity bills have 'Site')."""
    raw = record.get("raw", {})
    return str(raw.get("Site", "")).strip().lower()


def build_lines():
    """Run the pipeline and return a list of accepted, computed lines."""
    factors = load_factors()
    records = []
    records += ingest_csv(DATA_DIR / "electricity_bills.csv")
    records += ingest_csv(DATA_DIR / "diesel_invoices.csv")
    records += ingest_csv(DATA_DIR / "erp_spend_export.csv")
    records += ingest_pdf(DATA_DIR / "electricity_bill_sample.pdf")

    lines = []
    for r in records:
        if r["source_type"] == "csv":
            extracted = extract_with_rules(r)
            line_id = r["raw"].get("line_id", "?")
            site = get_site(r)
        else:
            extracted = extract_with_llm(r["raw_text"])
            line_id = f"PDF-p{r['source_page']}"
            site = "pdf"
        norm = normalize_line(extracted)

        if norm.activity == "unknown" or norm.unit is None:
            continue  # skip noise/ambiguous for the total

        fac = exact_match(norm, factors)
        if not fac:
            fac, score = semantic_match(norm, factors)
            if score < ACCEPT_SCORE:
                continue  # not confident -> not counted

        emissions = compute_emissions(norm.quantity, fac["value"])
        lines.append({
            "line_id": line_id,
            "fingerprint": fingerprint(norm, site),
            "emissions": emissions,
        })
    return lines


# ---------- the deduplication step ----------
def deduplicate(lines):
    """Keep the first line of each fingerprint; flag the rest as duplicates."""
    seen = {}            # fingerprint -> the line_id we kept first
    kept, duplicates = [], []

    for line in lines:
        fp = line["fingerprint"]
        if fp in seen:
            # we've seen this exact bill before -> it's a duplicate
            line["duplicate_of"] = seen[fp]
            duplicates.append(line)
        else:
            seen[fp] = line["line_id"]
            kept.append(line)
    return kept, duplicates


def main():
    print("Building computed lines...")
    lines = build_lines()

    kept, duplicates = deduplicate(lines)

    total_raw   = sum((l["emissions"] for l in lines), Decimal("0"))
    total_clean = sum((l["emissions"] for l in kept),  Decimal("0"))

    print("\n=================  DEDUPLICATION REPORT  =================\n")
    print(f"Total lines:        {len(lines)}")
    print(f"Kept (unique):      {len(kept)}")
    print(f"Duplicates found:   {len(duplicates)}")

    if duplicates:
        print("\nDuplicate lines removed from the total:")
        for d in duplicates:
            print(f"   {d['line_id']} is a duplicate of {d['duplicate_of']} "
                  f"(both {d['emissions']} kgCO2e)")

    print("\n-------------------------------------------")
    print(f"Total BEFORE dedup: {total_raw} kgCO2e")
    print(f"Total AFTER  dedup: {total_clean} kgCO2e")
    print(f"Difference removed: {total_raw - total_clean} kgCO2e")
    print("=========================================================")


if __name__ == "__main__":
    main()