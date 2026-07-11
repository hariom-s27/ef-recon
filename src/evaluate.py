"""
evaluate.py — SP-06: grade the engine against the gold answer key.
Produces Precision@1 with a Wilson confidence interval, plus noise/escalation
checks and a list of hard cases (what we got wrong).
"""

import csv
from statsmodels.stats.proportion import proportion_confint

from ingest import ingest_csv, ingest_pdf
from extract import extract_with_rules, extract_with_llm, looks_ambiguous
from normalize import normalize_line
from match import load_factors, exact_match, semantic_match, ACCEPT_SCORE, ESCALATE_SCORE
from paths import DATA_DIR
from logging_setup import setup_logging


# ---------- 1) load the answer key ----------
def load_gold():
    """line_id -> the correct answer (factor_id, or NO_FACTOR / ESCALATE)."""
    gold = {}
    with open(DATA_DIR / "gold_labels.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gold[row["line_id"]] = row["correct_factor_id"].strip()
    return gold


# ---------- 2) run the engine on one record -> (line_id, predicted, decision) ----------
def predict(record, factors):
    if record["source_type"] == "csv":
        extracted = extract_with_rules(record)
        line_id = record["raw"].get("line_id", "?")
    else:
        extracted = extract_with_llm(record["raw_text"])
        line_id = "PDF-0001"     # our gold key names the PDF line PDF-0001
    norm = normalize_line(extracted)

    # noise -> engine refuses, unless it still smells like fuel/energy -> escalate
    if norm.activity == "unknown" or norm.unit is None:
        if looks_ambiguous(record):
            return line_id, "ESCALATE", "escalate"     # unclear fuel -> human
        return line_id, "NO_FACTOR", "refuse"           # true noise -> refuse

    fac = exact_match(norm, factors)
    if fac:
        return line_id, fac["factor_id"], "accept"

    best, score = semantic_match(norm, factors)
    if score >= ACCEPT_SCORE:
        return line_id, best["factor_id"], "accept"
    elif score >= ESCALATE_SCORE:
        return line_id, "ESCALATE", "escalate"
    else:
        return line_id, "NO_FACTOR", "refuse"


def main():
    setup_logging()
    print("Loading factors + gold key...")
    factors = load_factors()
    gold = load_gold()

    records = []
    records += ingest_csv(DATA_DIR / "electricity_bills.csv")
    records += ingest_csv(DATA_DIR / "diesel_invoices.csv")
    records += ingest_csv(DATA_DIR / "erp_spend_export.csv")
    records += ingest_pdf(DATA_DIR / "electricity_bill_sample.pdf")

    # counters
    match_correct = match_total = 0        # for Precision@1 (only real mappable lines)
    noise_correct = noise_total = 0        # noise correctly refused
    esc_correct   = esc_total   = 0        # ambiguous correctly escalated
    hard_cases = []                        # the lines we got wrong

    for r in records:
        line_id, predicted, decision = predict(r, factors)
        truth = gold.get(line_id)
        if truth is None:
            continue   # no gold answer for this line, skip

        if truth == "NO_FACTOR":
            # this is a noise line: engine SHOULD refuse
            noise_total += 1
            if predicted == "NO_FACTOR":
                noise_correct += 1
            else:
                hard_cases.append((line_id, "noise", f"predicted {predicted}, should REFUSE"))

        elif truth == "ESCALATE":
            # ambiguous line: engine SHOULD escalate
            esc_total += 1
            if decision == "escalate":
                esc_correct += 1
            else:
                hard_cases.append((line_id, "ambiguous", f"decision {decision}, should ESCALATE"))

        else:
            # a real mappable line: engine SHOULD pick the correct factor
            match_total += 1
            if predicted == truth:
                match_correct += 1
            else:
                hard_cases.append((line_id, "match", f"predicted {predicted}, correct {truth}"))

    # ---------- Precision@1 with Wilson interval ----------
    p = match_correct / match_total if match_total else 0
    lo, hi = proportion_confint(match_correct, match_total, alpha=0.05, method="wilson")

    # ---------- report card ----------
    print("\n=================  RELIABILITY REPORT  =================\n")
    print(f"Precision@1 (factor match): {match_correct}/{match_total} = {p:.1%}")
    print(f"   95% Wilson CI: {lo:.1%} – {hi:.1%}   (n={match_total})")
    print(f"\nNoise correctly refused:    {noise_correct}/{noise_total}")
    print(f"Ambiguous correctly escalated: {esc_correct}/{esc_total}")

    print(f"\nHard cases (got wrong): {len(hard_cases)}")
    for line_id, kind, detail in hard_cases:
        print(f"   [{kind}] {line_id}: {detail}")
    if not hard_cases:
        print("   (none — perfect on this test set!)")

    print("\n=======================================================")


if __name__ == "__main__":
    main()