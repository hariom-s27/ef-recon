"""
generate_synthetic_bills.py
---------------------------------
Generates realistic, MESSY Indian activity data (electricity bills, diesel invoices,
an ERP spend export) for testing an emission-factor reconciliation engine, PLUS a
gold-labelled answer key so accuracy (Precision@1) can be measured with no real data.

Every generated line has a stable line_id and a KNOWN correct answer, recorded in
gold_labels.csv. The "messiness" (unit chaos, header variation, duplicates, noise
lines, ambiguous descriptions, missing periods, site-name variation) is deliberate —
each row is tagged with the reconciliation problem it embeds, so you can point to each
one in a demo.

Run:  python generate_synthetic_bills.py
Out:  ./data/*.csv  and  ./data/electricity_bill_sample.pdf (if reportlab installed)
"""

import csv, os, random, datetime
from pathlib import Path

SEED = 42                     # deterministic => reproducible gold set
random.seed(SEED)

HERE = Path(__file__).parent
DATA = HERE / "data"
DATA.mkdir(exist_ok=True)

# ---- load the factor library (single source of truth for values) -------------
FACTORS = {}
with open(HERE / "emission_factors.csv", newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        FACTORS[row["factor_id"]] = row
def factor_val(fid): return float(FACTORS[fid]["factor_kgco2e_per_unit"])

# ---- reference data ----------------------------------------------------------
DISCOMS   = ["UPPCL", "Torrent Power", "Tata Power-DDL", "BESCOM", "Adani Electricity",
             "MSEDCL", "CESC", "DHBVN"]
SITES     = [("Plant-1", "Unit 1 Kanpur", "KNP-01"),
             ("Plant-2", "Unit 2 Pune",   "PUN-02"),
             ("Warehouse", "Central WH Delhi", "DEL-WH")]
DIESEL_VENDORS = ["Indian Oil", "Bharat Petroleum", "HPCL", "Reliance Petro"]

gold_rows = []
_counter = {}
def new_id(prefix):
    _counter[prefix] = _counter.get(prefix, 0) + 1
    return f"{prefix}-{_counter[prefix]:04d}"

def add_gold(line_id, src, raw_desc, factor_id, qty_canonical, unit_canonical, tags):
    """Record the correct answer for one generated line."""
    expected = round(qty_canonical * factor_val(factor_id), 3) if factor_id in FACTORS else ""
    gold_rows.append({
        "line_id": line_id, "source_file": src, "raw_description": raw_desc,
        "correct_factor_id": factor_id,               # or NO_FACTOR / ESCALATE
        "canonical_qty": qty_canonical, "canonical_unit": unit_canonical,
        "expected_kgco2e": expected, "messiness_tags": "|".join(tags),
    })

def rand_period(missing_prob=0.0):
    if random.random() < missing_prob:
        return ""                                     # missing period => parser fallback test
    m = random.randint(1, 12); y = 2025
    start = datetime.date(y, m, 1)
    return f"{start:%d-%b-%Y}"

# =============================================================================
# 1) ELECTRICITY BILLS  (Scope 2)  -- header + unit chaos, duplicates, missing period
# =============================================================================
# Different DISCOMs label the consumption column differently -> header variation.
ELEC_HEADERS = ["Units Consumed", "kWh", "Energy (Units)", "Net Units Billed", "Consumption"]

elec_records = []
for _ in range(14):
    discom = random.choice(DISCOMS)
    site   = random.choice(SITES)
    site_name = random.choice(site)               # same site appears under 3 names
    header = random.choice(ELEC_HEADERS)
    true_kwh = random.randint(4000, 90000)        # canonical truth in kWh
    tags = ["header_variation"]

    # UNIT CHAOS: ~1 in 4 bills reports in MWh instead of kWh
    if random.random() < 0.25:
        shown_val, shown_unit = round(true_kwh / 1000, 3), "MWh"
        tags.append("unit_mwh_not_kwh")
    else:
        shown_val, shown_unit = true_kwh, "kWh"

    period = rand_period(missing_prob=0.15)
    if period == "": tags.append("missing_period")

    lid = new_id("ELEC")
    elec_records.append({
        "line_id": lid, "DISCOM": discom, "Site": site_name,
        "Billing Period": period, header: shown_val, "Unit": shown_unit,
        "Amount (INR)": round(shown_val * (8 if shown_unit=="kWh" else 8000) * random.uniform(0.9,1.1), 2),
        "_header_used": header,
    })
    add_gold(lid, "electricity_bills.csv", f"{discom} {header}={shown_val} {shown_unit}",
             "EF-IN-ELEC-GRID", true_kwh, "kWh", tags)

# DUPLICATE: same bill arrives twice (double-counting risk) -> dedup test
dup = dict(elec_records[3]); dup_lid = new_id("ELEC"); dup["line_id"] = dup_lid
elec_records.append(dup)
# the duplicate's TRUE contribution is zero (it should be removed, not counted)
add_gold(dup_lid, "electricity_bills.csv", "EXACT DUPLICATE of "+elec_records[3]["line_id"],
         "EF-IN-ELEC-GRID", 0, "kWh", ["duplicate_row", "should_be_deduped"])

# write electricity bills (union of all possible headers so it's a real messy CSV)
elec_cols = ["line_id", "DISCOM", "Site", "Billing Period"] + ELEC_HEADERS + ["Unit", "Amount (INR)"]
with open(DATA / "electricity_bills.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=elec_cols, extrasaction="ignore")
    w.writeheader()
    for r in elec_records:
        row = {k: r.get(k, "") for k in elec_cols}
        row[r["_header_used"]] = r[r["_header_used"]]   # value only under its own header
        w.writerow(row)

# =============================================================================
# 2) DIESEL INVOICES  (Scope 1)  -- name variation, litre vs kilolitre chaos
# =============================================================================
DIESEL_NAMES = ["Diesel", "HSD", "High Speed Diesel", "DG Set Diesel"]
with open(DATA / "diesel_invoices.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["line_id", "Vendor", "Invoice Date", "Product", "Quantity", "Qty Unit", "Rate (INR)"])
    for _ in range(10):
        name = random.choice(DIESEL_NAMES)
        true_litres = random.randint(200, 9000)
        tags = ["fuel_name_variation"]
        # UNIT CHAOS: ~1 in 4 invoices in kilolitres (KL) instead of litres
        if random.random() < 0.25:
            qty, unit = round(true_litres / 1000, 3), "KL"; tags.append("unit_kilolitre")
        else:
            qty, unit = true_litres, "L"
        lid = new_id("DSL")
        w.writerow([lid, random.choice(DIESEL_VENDORS), rand_period(), name, qty, unit,
                    round(qty * (92 if unit=="L" else 92000) * random.uniform(0.95,1.05), 2)])
        add_gold(lid, "diesel_invoices.csv", f"{name} {qty} {unit}",
                 "EF-DIESEL-L", true_litres, "litre", tags)

# =============================================================================
# 3) ERP SPEND EXPORT  -- mixed categories + NOISE lines + AMBIGUOUS lines
# =============================================================================
# This is the hardest file: the engine must (a) map real energy lines, (b) NOT force a
# factor onto non-energy noise, and (c) escalate genuinely ambiguous lines.
erp = []
def erp_line(desc, qty, unit, factor_id, tags):
    lid = new_id("ERP")
    erp.append([lid, desc, qty, unit])
    canon = qty
    if factor_id == "EF-NATGAS-M3":  canon_unit = "m3"
    elif factor_id == "EF-LPG-L":    canon_unit = "litre"
    elif factor_id == "EF-PETROL-L": canon_unit = "litre"
    else:                            canon_unit = unit
    add_gold(lid, "erp_spend_export.csv", desc,
             factor_id, canon if factor_id in FACTORS else "", canon_unit, tags)

erp_line("Electricity charges - Unit 1", random.randint(5000, 40000), "kWh", "EF-IN-ELEC-GRID", ["clean"])
erp_line("PNG (piped natural gas) consumption", random.randint(300, 4000), "m3", "EF-NATGAS-M3", ["clean"])
erp_line("LPG cylinders - canteen", random.randint(50, 600), "litre", "EF-LPG-L", ["confirm_litre_vs_kg"])
erp_line("Petrol reimbursement - sales cars", random.randint(80, 900), "litre", "EF-PETROL-L", ["clean"])
# NOISE: non-energy lines -> correct answer is NO_FACTOR (must not be force-mapped)
erp_line("Printer cartridges & stationery", 1, "lot", "NO_FACTOR", ["noise_non_energy", "must_not_map"])
erp_line("Management consultancy fees", 1, "lot", "NO_FACTOR", ["noise_non_energy", "must_not_map"])
# AMBIGUOUS: "Fuel" could be diesel or petrol -> low confidence -> ESCALATE
erp_line("Fuel expenses (mixed vehicles)", random.randint(100, 2000), "litre", "ESCALATE", ["ambiguous_fuel", "should_escalate"])

with open(DATA / "erp_spend_export.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["line_id", "GL Description", "Quantity", "Unit"])
    w.writerows(erp)

# =============================================================================
# 4) GOLD ANSWER KEY
# =============================================================================
with open(DATA / "gold_labels.csv", "w", newline="", encoding="utf-8") as f:
    cols = ["line_id", "source_file", "raw_description", "correct_factor_id",
            "canonical_qty", "canonical_unit", "expected_kgco2e", "messiness_tags"]
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(gold_rows)

# =============================================================================
# 5) One PDF electricity bill (exercise the PDF-parsing path)  -- optional
# =============================================================================
pdf_note = "skipped (reportlab not installed)"
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import cm
    p = DATA / "electricity_bill_sample.pdf"
    c = canvas.Canvas(str(p), pagesize=A4); W, H = A4
    c.setFont("Helvetica-Bold", 16); c.drawString(2*cm, H-2*cm, "UPPCL - Electricity Bill")
    c.setFont("Helvetica", 10)
    lines = [
        "Consumer No: 41-002983  |  Site: Unit 1 Kanpur (KNP-01)",
        "Billing Period: 01-Jun-2025 to 30-Jun-2025",
        "",
        "Units Consumed        : 23,450 kWh",
        "Energy Charges (INR)  : 1,87,600",
        "Fixed Charges (INR)   : 12,000",
        "Total Payable (INR)   : 1,99,600",
    ]
    y = H - 3.2*cm
    for ln in lines:
        c.drawString(2*cm, y, ln); y -= 0.7*cm
    c.showPage(); c.save()
    # gold entry for the PDF bill
    add_gold("PDF-0001", "electricity_bill_sample.pdf", "UPPCL Units Consumed=23450 kWh",
             "EF-IN-ELEC-GRID", 23450, "kWh", ["pdf_source", "clean"])
    # re-write gold to include the PDF row
    with open(DATA / "gold_labels.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(gold_rows)
    pdf_note = f"written -> {p.name}"
except Exception as e:
    pdf_note = f"skipped ({e})"

# ---- summary -----------------------------------------------------------------
n_map = sum(1 for g in gold_rows if g["correct_factor_id"] in FACTORS and g["canonical_qty"] != 0)
n_dup = sum(1 for g in gold_rows if "duplicate_row" in g["messiness_tags"])
n_noise = sum(1 for g in gold_rows if g["correct_factor_id"] == "NO_FACTOR")
n_esc = sum(1 for g in gold_rows if g["correct_factor_id"] == "ESCALATE")
print("Generated files in ./data :")
for fn in sorted(os.listdir(DATA)): print("  -", fn)
print(f"\nGold lines: {len(gold_rows)} total | {n_map} mappable | "
      f"{n_dup} duplicate | {n_noise} noise(NO_FACTOR) | {n_esc} ambiguous(ESCALATE)")
print("PDF bill:", pdf_note)
