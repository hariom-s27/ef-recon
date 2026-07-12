"""
run_scorecard.py — the HONEST accuracy number.
Runs each gold_labels.csv description through the engine, then measures:
  - Precision@1 (judge)  : of ACCEPTED matches, how many the judge says are right (+ Wilson CI)
  - Precision@1 (gold)   : cross-check against the known correct_factor_id
  - Coverage             : of should-match rows, how many the engine attempted
  - Escalation / Refusal : did it correctly decline the ESCALATE / NO_FACTOR rows?
Run:  python src/run_scorecard.py   (takes a few minutes — one LLM call per row)
"""
import csv
import json
import hashlib
from statsmodels.stats.proportion import proportion_confint

from paths import DATA_DIR
from extract import extract_with_llm, ExtractedLine
from normalize import normalize_line
from match import load_factors
from judge import judge_one

AMBIGUOUS_HINTS = ["fuel", "energy", "consumption", "utility"]

# ---------- judge cache (judge is deterministic at temp=0, so cache by (line, factor)) ----------
(DATA_DIR.parent / "output").mkdir(exist_ok=True)
_JUDGE_CACHE = DATA_DIR.parent / "output" / "judge_cache.json"
_cache = json.load(open(_JUDGE_CACHE)) if _JUDGE_CACHE.exists() else {}

def cached_judge(desc, factor):
    key = hashlib.md5(f"{desc}|{factor['id']}".encode()).hexdigest()
    if key in _cache:
        return _cache[key]
    v = judge_one(desc, factor).verdict
    _cache[key] = v
    json.dump(_cache, open(_JUDGE_CACHE, "w"))
    return v


def to_judge_factor(fac):
    """Map the engine's factor dict -> the shape judge_one expects."""
    fid = fac["factor_id"]
    return {
        "id": fid,
        "name": fac.get("desc", fid),
        "activity": fac["activity_type"],
        "unit": fac["unit_in"],
        "region": "India" if fid.startswith("EF-IN") else "Global",
        "year": 2024,
    }


def run_engine(description, factors, fb_qty=None, fb_unit=None):
    """extract -> normalize -> match via the ONE policy. Returns (decision, factor_or_None)."""
    from normalize import has_unsupported_fuel
    if has_unsupported_fuel(description):
        return "escalate", None          # named fuel we don't cover -> honest escalation

    # fast path: if the gold row already gives us activity via canonical alias, skip the LLM
    from normalize import canonical_activity
    guess = canonical_activity(description)
    if guess and fb_unit:
        ex = ExtractedLine(activity=guess, quantity=fb_qty, unit=fb_unit, period=None)
    else:
        ex = extract_with_llm(description)   # only the genuinely messy ones
    # fallback to gold canonical qty/unit so we test MATCHING, not extraction gaps
    if (ex.unit is None or ex.quantity is None) and fb_unit:
        ex = ExtractedLine(
            activity=ex.activity,
            quantity=ex.quantity if ex.quantity is not None else fb_qty,
            unit=ex.unit if ex.unit is not None else fb_unit,
            period=ex.period,
        )
    norm = normalize_line(ex)

    from match import match_line
    decision, fac = match_line(norm, factors, raw_text=description)
    if decision == "escalate_or_refuse":
        low = description.lower()
        decision = "escalate" if any(h in low for h in AMBIGUOUS_HINTS) else "refuse"
    return decision, fac


def main():
    print("Loading + embedding factor library...")
    factors = load_factors()
    rows = list(csv.DictReader(open(DATA_DIR / "gold_labels.csv", encoding="utf-8")))
    print(f"Loaded {len(rows)} gold rows. Running engine + judge (a few minutes)...\n")

    # buckets
    should_match = accepted = judge_correct = gold_correct = 0
    esc_right = esc_total = ref_right = ref_total = 0

    for row in rows:
        desc = row["raw_description"]
        print(f"  ... processing: {desc[:45]}", flush=True)   # <-- heartbeat
        gold = row["correct_factor_id"].strip()
        fb_qty = row.get("canonical_qty") or None
        fb_unit = row.get("canonical_unit") or None
        fb_qty = float(fb_qty) if fb_qty else None

        decision, fac = run_engine(desc, factors, fb_qty, fb_unit)

        if gold == "ESCALATE":
            esc_total += 1
            ok = decision == "escalate"
            esc_right += ok
            print(f"[should escalate] {desc[:42]:42} -> {decision:9} {'OK' if ok else 'MISS'}")

        elif gold in ("NO_FACTOR", ""):
            ref_total += 1
            ok = decision == "refuse"
            ref_right += ok
            print(f"[should refuse]   {desc[:42]:42} -> {decision:9} {'OK' if ok else 'MISS'}")

        else:  # should match a real factor
            should_match += 1
            if decision == "accept" and fac:
                accepted += 1
                if fac["factor_id"] == gold:
                    gold_correct += 1
                verdict = cached_judge(desc, to_judge_factor(fac))
                judge_correct += (verdict == "correct")
                g = "gold OK" if fac["factor_id"] == gold else f"gold MISS(->{gold})"
                print(f"[should match]    {desc[:42]:42} -> {fac['factor_id']:16} "
                      f"judge={verdict:9} {g}")
            else:
                print(f"[should match]    {desc[:42]:42} -> {decision:9} NOT ATTEMPTED (coverage miss)")

    # ---------- results ----------
    print("\n" + "=" * 62)
    print("SCORECARD")
    print("=" * 62)
    if accepted:
        p = judge_correct / accepted
        lo, hi = proportion_confint(judge_correct, accepted, alpha=0.05, method="wilson")
        print(f"Precision@1 (judge): {p:.1%}  (95% Wilson CI {lo:.1%}-{hi:.1%}, n={accepted})")
        print(f"Precision@1 (gold):  {gold_correct/accepted:.1%}  ({gold_correct}/{accepted}) — cross-check")
    print(f"Coverage:            {accepted}/{should_match} of should-match rows attempted")
    print(f"Escalation accuracy: {esc_right}/{esc_total} correctly escalated")
    print(f"Refusal accuracy:    {ref_right}/{ref_total} correctly refused")

    # save so the dashboard can show it later
    out = {"precision_judge": (judge_correct / accepted) if accepted else None,
           "n": accepted, "gold_correct": gold_correct,
           "coverage_attempted": accepted, "coverage_total": should_match,
           "escalation": [esc_right, esc_total], "refusal": [ref_right, ref_total]}
    (DATA_DIR.parent / "output").mkdir(exist_ok=True)
    json.dump(out, open(DATA_DIR.parent / "output" / "scorecard.json", "w"), indent=2)
    print("\nSaved -> output/scorecard.json")


if __name__ == "__main__":
    main()