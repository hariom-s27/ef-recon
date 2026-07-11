# src/brsr_ingest.py
"""
Automated BRSR Principle-6 energy ingester.
Finds the energy table in ANY BRSR PDF (no hardcoded page), reads the
fixed SEBI rows, keeps entities separate, then does a dedup check + Scope-2 recompute.
No LLM needed — the format is standardized, so deterministic parsing wins.
"""
import pdfplumber

# ---------- constants ----------
GJ_TO_KWH = 277.778          # 1 GJ = 277.778 kWh
CEA_FACTOR = 0.7117          # tCO2 per MWh (CEA v21 all-India grid)

# fixed SEBI row labels -> our field names (substring match, lowercased)
LABELS = {
    "electricity consumption (a)": "renew_elec_gj",      # renewable electricity
    "electricity consumption (d)": "nonrenew_elec_gj",   # non-renewable (grid) electricity
    "fuel consumption (e)":        "nonrenew_fuel_gj",    # non-renewable fuel (lumped)
    "(a+b+c+d+e+f)":               "total_energy_gj",     # grand total
}

# ---------- small helpers ----------
def parse_indian_number(s):
    """'6,50,710' -> 650710.0 ; '3,72,058*' -> 372058.0 ; '-' or '' -> None"""
    if s is None:
        return None
    s = str(s).strip().replace("*", "").replace(",", "")
    if s in ("", "-", "NA", "N.A.", "N.A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None

def first_number_in_row(row):
    """First parseable number after the label cell = the FY25 (current year) value."""
    for cell in row[1:]:
        val = parse_indian_number(cell)
        if val is not None:
            return val
    return None

def detect_entity(text):
    """Entity header appears as its own short line. Check most-specific first."""
    for line in text.splitlines():
        s = line.strip().lower().rstrip(".")
        if s == "tml, tmpvl and tpeml":
            return "TML+TMPVL+TPEML (combined)"
        if s == "tmpvl and tpeml":
            return "TMPVL+TPEML"
        if s == "tml":
            return "TML"
    return None

# ---------- locate the energy section (no hardcoded page) ----------
def find_energy_pages(pdf):
    start = None
    for i, page in enumerate(pdf.pages):
        txt = (page.extract_text() or "").lower()
        if start is None and "details of total energy consumption" in txt:
            start = i
        elif start is not None and ("designated consumers" in txt
                                    or "disclosures related to water" in txt):
            return list(range(start, i + 1))     # section ends here
    return list(range(start, len(pdf.pages))) if start is not None else []

# ---------- read one table using the fixed labels ----------
def extract_energy_from_table(table):
    out = {}
    for row in table:
        if not row or row[0] is None:
            continue
        label = str(row[0]).lower().replace("\n", " ")
        for key, field in LABELS.items():
            if key in label:
                out[field] = first_number_in_row(row)
    return out

# ---------- orchestrator ----------
def ingest_brsr_energy(pdf_path):
    records = []
    current_entity = None
    with pdfplumber.open(pdf_path) as pdf:
        for i in find_energy_pages(pdf):
            page = pdf.pages[i]
            ent = detect_entity(page.extract_text() or "")
            if ent:
                current_entity = ent
            for table in page.extract_tables():
                energy = extract_energy_from_table(table)
                if energy.get("nonrenew_elec_gj") is not None or energy.get("total_energy_gj") is not None:
                    records.append({"entity": current_entity, "source_page": i + 1, **energy})
    return records

# ---------- the two demos ----------
def dedup_check(records):
    parts = [r for r in records if r["entity"] in ("TML", "TMPVL+TPEML")]
    combined = next((r for r in records if r["entity"] and "combined" in r["entity"]), None)
    if not combined or len(parts) < 2:
        print("Dedup check: need both parts + combined block; not found.")
        return
    sum_elec = sum((p.get("nonrenew_elec_gj") or 0) for p in parts)
    comb_elec = combined.get("nonrenew_elec_gj") or 0
    print(f"\n--- DEDUP CHECK (electricity) ---")
    print(f"Sum of parts : {sum_elec:,.0f} GJ")
    print(f"Combined block: {comb_elec:,.0f} GJ")
    if comb_elec and abs(sum_elec - comb_elec) / comb_elec < 0.01:
        print("DUPLICATE DETECTED: combined = sum of parts. Count ONCE, not both.")
    else:
        print("No exact duplication detected.")

def recompute_scope2(record):
    gj = record.get("nonrenew_elec_gj")
    if gj is None:
        return
    mwh = gj * GJ_TO_KWH / 1000
    tco2 = mwh * CEA_FACTOR
    print(f"  {record['entity']:<28} {gj:>12,.0f} GJ -> {mwh:>12,.0f} MWh -> {tco2:>10,.0f} tCO2e")

# ---------- run ----------
if __name__ == "__main__":
    PDF = "data/Voluntary-Report-based-on-BRSR-Framework-for-FY-2024-25.pdf"
    recs = ingest_brsr_energy(PDF)

    print("=== EXTRACTED ENERGY RECORDS ===")
    for r in recs:
        print(r)

    dedup_check(recs)

    print(f"\n--- SCOPE 2 RECOMPUTE (grid electricity x CEA {CEA_FACTOR}) ---")
    for r in recs:
        recompute_scope2(r)