"""
calibrate.py — SP-10: check if confidence is HONEST (calibration + ECE),
and guard against silent accuracy drops (regression test vs a saved baseline).
"""

import json
from pathlib import Path

from paths import DATA_DIR, OUTPUT_DIR
from ingest import ingest_csv, ingest_pdf
from extract import extract_with_rules, extract_with_llm, looks_ambiguous
from normalize import normalize_line
from match import load_factors, exact_match, semantic_match, ACCEPT_SCORE, ESCALATE_SCORE
import csv

BASELINE_FILE = OUTPUT_DIR / "baseline.json"


# ---------- load the gold answer key ----------
def load_gold():
    gold = {}
    with open(DATA_DIR / "gold_labels.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gold[row["line_id"]] = row["correct_factor_id"].strip()
    return gold


# ---------- run engine -> collect (confidence, correct?) ----------
def collect_predictions(factors, gold):
    records = []
    records += ingest_csv(DATA_DIR / "electricity_bills.csv")
    records += ingest_csv(DATA_DIR / "diesel_invoices.csv")
    records += ingest_csv(DATA_DIR / "erp_spend_export.csv")
    records += ingest_pdf(DATA_DIR / "electricity_bill_sample.pdf")

    data = []            # list of (confidence, correct_bool)
    correct = total = 0  # for Precision@1

    for r in records:
        if r["source_type"] == "csv":
            extracted = extract_with_rules(r)
            line_id = r["raw"].get("line_id", "?")
        else:
            extracted = extract_with_llm(r["raw_text"])
            line_id = "PDF-0001"
        norm = normalize_line(extracted)

        truth = gold.get(line_id)
        # only score real mappable lines (skip noise/ambiguous)
        if truth is None or truth in ("NO_FACTOR", "ESCALATE"):
            continue
        if norm.activity == "unknown" or norm.unit is None:
            continue

        fac = exact_match(norm, factors)
        if fac:
            confidence, predicted = 1.0, fac["factor_id"]      # exact = fully confident
        else:
            fac, score = semantic_match(norm, factors)
            confidence, predicted = score, fac["factor_id"]

        is_correct = (predicted == truth)
        data.append((confidence, is_correct))
        total += 1
        correct += 1 if is_correct else 0

    precision = correct / total if total else 0
    return data, precision, correct, total


# ---------- calibration: bins + ECE ----------
def calibration(data, n_bins=5):
    # make bins: 0-0.2, 0.2-0.4, ... 0.8-1.0
    bins = [[] for _ in range(n_bins)]
    for conf, correct in data:
        idx = min(int(conf * n_bins), n_bins - 1)   # which bin this confidence falls in
        bins[idx].append((conf, correct))

    print("\nReliability table (is the confidence honest?):")
    print(f"{'bin':12} {'count':>6} {'avg conf':>9} {'accuracy':>9} {'gap':>7}")
    ece = 0.0
    n = len(data)
    for i, b in enumerate(bins):
        if not b:
            continue
        avg_conf = sum(c for c, _ in b) / len(b)
        accuracy = sum(1 for _, ok in b if ok) / len(b)
        gap = abs(avg_conf - accuracy)
        ece += (len(b) / n) * gap                   # weighted gap
        lo, hi = i / n_bins, (i + 1) / n_bins
        print(f"{lo:.1f}-{hi:.1f}      {len(b):>6} {avg_conf:>9.3f} {accuracy:>9.3f} {gap:>7.3f}")
    return ece


# ---------- regression test ----------
def regression_check(precision):
    if BASELINE_FILE.exists():
        baseline = json.loads(BASELINE_FILE.read_text())["precision"]
        print(f"\nRegression check: baseline={baseline:.1%}, now={precision:.1%}")
        if precision + 1e-9 >= baseline:
            print("   ✅ PASS — accuracy did not drop.")
        else:
            print("   ⚠️  FAIL — accuracy DROPPED! You may have broken something.")
    else:
        print("\nNo baseline yet — saving this run as the baseline.")

    # save/update the baseline
    BASELINE_FILE.write_text(json.dumps({"precision": precision}, indent=2))
    print(f"   Baseline saved -> {BASELINE_FILE.name}")


def main():
    factors = load_factors()
    gold = load_gold()
    data, precision, correct, total = collect_predictions(factors, gold)

    print("\n=================  CALIBRATION & REGRESSION  =================")
    print(f"\nPrecision@1: {correct}/{total} = {precision:.1%}")

    ece = calibration(data)
    print(f"\nECE (Expected Calibration Error): {ece:.3f}")
    if ece < 0.05:
        print("   -> Well calibrated (confidence is honest).")
    elif ece < 0.15:
        print("   -> Slightly off, but reasonable.")
    else:
        print("   -> Overconfident/underconfident — confidence not fully trustworthy.")

    regression_check(precision)
    print("\n=============================================================")


if __name__ == "__main__":
    main()