"""
match.py — SP-04 (fixed): match each clean line to the correct emission factor.
Level 1: EXACT match on (activity, unit)  -> for clean lines. Precise, no guessing.
Level 2: EMBEDDINGS fallback              -> only when activity is unknown.
"""

import csv
import numpy as np

import ollama
from ingest import ingest_csv, ingest_pdf
from extract import extract_with_rules, extract_with_llm
from normalize import normalize_line
from paths import DATA_DIR

EMBED_MODEL = "nomic-embed-text"

ACCEPT_SCORE   = 0.60
ESCALATE_SCORE = 0.45


def embed(text):
    return np.array(ollama.embeddings(model=EMBED_MODEL, prompt=text)["embedding"])

def cosine(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def factor_activity_type(row):
    """Work out a clean category ('electricity','diesel',...) from the factor row."""
    text = f"{row['activity']} {row['aliases']}".lower()
    if "electricity" in text or "grid" in text:
        return "electricity"
    if "diesel" in text:
        return "diesel"
    if "lpg" in text:
        return "lpg"
    if "petrol" in text or "gasoline" in text:
        return "petrol"
    if "natural gas" in text or "png" in text:
        return "natural gas"
    return row["activity"].strip().lower()


def load_factors():
    factors = []
    with open(DATA_DIR / "emission_factors.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            desc = f"{row['activity']} {row['unit_in']} {row['aliases'].replace('|', ' ')}"
            factors.append({
                "factor_id":     row["factor_id"],
                "activity_type": factor_activity_type(row),      # <-- clean category key
                "unit_in":       row["unit_in"].strip().lower(),
                "value":         float(row["factor_kgco2e_per_unit"]),
                "desc":          desc,
                "vector":        embed(desc),
            })
    return factors


# ---------- LEVEL 1: exact match on (activity, unit) ----------
def exact_match(norm, factors):
    """Return the factor whose activity AND unit both match. Precise, no AI."""
    line_activity = (norm.activity or "").strip().lower()
    line_unit     = (norm.unit or "").strip().lower()
    for fac in factors:
        if fac["activity_type"] == line_activity and fac["unit_in"] == line_unit:
            return fac
    return None


# ---------- LEVEL 2: embeddings fallback (only for unknown) ----------
def semantic_match(norm, factors):
    line_text = f"{norm.activity} {norm.unit}"
    line_vec = embed(line_text)
    best, best_score = None, -1.0
    for fac in factors:
        score = cosine(line_vec, fac["vector"])
        if score > best_score:
            best, best_score = fac, score
    return best, best_score


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

        # noise -> refuse immediately
        if norm.activity == "unknown" or norm.unit is None:
            print(f"{line_id:12} {norm.activity:12} {str(norm.unit):6} -> ❌ REFUSE (no clear activity/unit)")
            continue

        # LEVEL 1: try exact match first
        fac = exact_match(norm, factors)
        if fac:
            print(f"{line_id:12} {norm.activity:12} {str(norm.unit):6} -> "
                  f"{fac['factor_id']:18} (exact) ✅ accept")
            continue

        # LEVEL 2: fall back to embeddings
        best, score = semantic_match(norm, factors)
        decision = "accept" if score >= ACCEPT_SCORE else ("escalate" if score >= ESCALATE_SCORE else "refuse")
        tag = {"accept": "✅", "escalate": "⚠️", "refuse": "❌"}[decision]
        print(f"{line_id:12} {norm.activity:12} {str(norm.unit):6} -> "
              f"{best['factor_id']:18} score={score:.2f} {tag} {decision} (semantic)")


if __name__ == "__main__":
    main()