"""
match.py — SP-04 (standardized): match each clean line to the correct emission factor.

Decision policy (in order):
  1. activity MUST match  (never cross activities: electricity !-> gas, diesel !-> petrol)
  2. unit MUST match       among that activity's factors
  3. tie-break: prefer region IN over GLOBAL; NEVER auto-pick a 'special use' factor (e.g. -CM)
  4. activity matches but NO unit fits (LPG in kg, CNG in m3, diesel in gallons) -> ESCALATE
  5. activity unknown -> semantic fallback (suggest only, gated by score thresholds)
"""

import csv
import pickle
import os
import numpy as np
import ollama

from ingest import ingest_csv, ingest_pdf
from extract import extract_with_rules, extract_with_llm
from normalize import normalize_line
from paths import DATA_DIR
from config import ACCEPT_SCORE, ESCALATE_SCORE, EMBED_MODEL


def embed(text):
    return np.array(ollama.embeddings(model=EMBED_MODEL, prompt=text)["embedding"])

def cosine(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def factor_activity_type(row):
    """Clean category ('electricity','diesel',...) from the factor row."""
    text = f"{row['activity']} {row['aliases']}".lower()
    if "electricity" in text or "grid" in text or "solar" in text:
        return "electricity"
    if "diesel" in text:
        return "diesel"
    if "lpg" in text:
        return "lpg"
    if "petrol" in text or "gasoline" in text:
        return "petrol"
    if "cng" in text or "compressed natural gas" in text:
        return "cng"
    if "coal" in text:
        return "coal"
    if "natural gas" in text or "png" in text:
        return "natural gas"
    return row["activity"].strip().lower()


# factors that must NEVER be auto-selected (need a human / special context)
SPECIAL_USE = {"EF-IN-ELEC-GRID-CM"}          # Combined Margin: CDM only, never corporate Scope 2

# the ONLY activities our factor library actually covers
KNOWN_ACTIVITIES = {"electricity", "diesel", "petrol", "natural gas",
                    "lpg", "cng", "coal"}   # (solar handled as electricity)

# activity -> the unit(s) we can actually price it in
ALLOWED_UNITS = {
    "electricity": {"kwh"},
    "diesel":      {"litre"},
    "petrol":      {"litre"},
    "natural gas": {"m3", "kwh"},
    "lpg":         {"litre"},     # kg has NO factor -> must escalate
    "cng":         {"kg"},        # m3 has NO factor -> must escalate
    "coal":        {"tonne"},
}


def load_factors():
    cache = DATA_DIR.parent / "output" / "factors_cache.pkl"
    csv_path = DATA_DIR / "emission_factors.csv"
    # reuse cache if it's newer than the CSV
    if cache.exists() and os.path.getmtime(cache) > os.path.getmtime(csv_path):
        return pickle.load(open(cache, "rb"))

    factors = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            desc = f"{row['activity']} {row['unit_in']} {row['aliases'].replace('|', ' ')}"
            factors.append({
                "factor_id":     row["factor_id"],
                "activity_type": factor_activity_type(row),
                "unit_in":       row["unit_in"].strip().lower(),
                "region":        row.get("region", "GLOBAL").strip().upper(),
                "special":       row["factor_id"] in SPECIAL_USE,
                "value":         float(row["factor_kgco2e_per_unit"]),
                "source":        row.get("source", ""),
                "source_year":   row.get("source_year", ""),
                "desc":          desc,
                "vector":        embed(desc),
            })
    cache.parent.mkdir(exist_ok=True)
    pickle.dump(factors, open(cache, "wb"))
    return factors


# ---------- LEVEL 1: standardized exact match ----------
def exact_match(norm, factors):
    """Activity-first, unit-second, with tie-breaks. Returns a factor or None."""
    line_activity = (norm.activity or "").strip().lower()
    line_unit     = (norm.unit or "").strip().lower()

    # candidates: same activity, same unit, not special-use
    candidates = [f for f in factors
                  if f["activity_type"] == line_activity
                  and f["unit_in"] == line_unit
                  and not f["special"]]
    if not candidates:
        return None

    # tie-break: prefer India-specific factor over global
    candidates.sort(key=lambda f: 0 if f["region"] == "IN" else 1)
    return candidates[0]


def activity_known(norm, factors):
    """Does the line's activity exist in our library at all?"""
    line_activity = (norm.activity or "").strip().lower()
    return any(f["activity_type"] == line_activity for f in factors)


# ---------- LEVEL 2: semantic fallback (only when activity is unknown) ----------
def semantic_match(norm, factors):
    line_text = f"{norm.activity} {norm.unit}"
    line_vec = embed(line_text)
    best, best_score = None, -1.0
    for fac in factors:
        if fac["special"]:
            continue
        score = cosine(line_vec, fac["vector"])
        if score > best_score:
            best, best_score = fac, score
    return best, best_score


# ---------- the single decision function (use this everywhere) ----------
def match_line(norm, factors, raw_text=""):
    """Return (decision, factor_or_None). One policy, honest escalation."""
    activity = (norm.activity or "").strip().lower()
    unit     = (norm.unit or "").strip().lower()

    # named unsupported fuel in the raw text -> escalate before matching
    from normalize import has_unsupported_fuel
    if has_unsupported_fuel(raw_text) or has_unsupported_fuel(activity):
        return "escalate", None

    # 1. no activity or no unit -> caller decides escalate vs refuse
    if activity == "unknown" or norm.unit is None:
        return "escalate_or_refuse", None

    # 2. activity NOT in our library -> escalate, NEVER semantic-guess
    #    (furnace oil, pet coke, HFO, biomass all land here)
    if activity not in KNOWN_ACTIVITIES:
        return "escalate", None

    # 3. activity known but unit not one we can price (LPG kg, CNG m3, diesel gallons-if-unconverted)
    if unit not in ALLOWED_UNITS.get(activity, set()):
        return "escalate", None

    # 4. activity + unit both valid -> standardized exact match
    fac = exact_match(norm, factors)
    if fac:
        return "accept", fac

    # 5. safety net: known activity but no exact factor row -> escalate, don't force
    return "escalate", None


def main():
    print("Loading + embedding factor library...")
    factors = load_factors()
    print(f"  {len(factors)} factors embedded.\n")

    records = []
    records += ingest_csv(DATA_DIR / "electricity_bills.csv")
    records += ingest_csv(DATA_DIR / "diesel_invoices.csv")
    records += ingest_csv(DATA_DIR / "erp_spend_export.csv")
    records += ingest_pdf(DATA_DIR / "electricity_bill_sample.pdf")

    print("\n========== SP-04: MATCHED LINES ==========\n")
    for r in records:
        if r["source_type"] == "csv":
            extracted = extract_with_rules(r)
            line_id = r["raw"].get("line_id", "?")
        else:
            extracted = extract_with_llm(r["raw_text"])
            line_id = f"PDF-p{r['source_page']}"
        norm = normalize_line(extracted)

        decision, fac = match_line(norm, factors)
        fid = fac["factor_id"] if fac else "-"
        tag = {"accept": "✅", "escalate": "⚠️", "refuse": "❌",
               "escalate_or_refuse": "⚠️"}[decision]
        print(f"{line_id:12} {norm.activity:12} {str(norm.unit):6} -> {fid:18} {tag} {decision}")


if __name__ == "__main__":
    main()