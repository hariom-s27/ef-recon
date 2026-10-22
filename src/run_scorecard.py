"""
run_scorecard.py — the HONEST accuracy number.

Default (LLM) mode — runs each gold_labels.csv description through the engine, then measures:
  - Precision@1 (judge)  : of ACCEPTED matches, how many the judge says are right (+ Wilson CI)
  - Precision@1 (gold)   : cross-check against the known correct_factor_id
  - Coverage             : of should-match rows, how many the engine attempted
  - Escalation / Refusal : did it correctly decline the ESCALATE / NO_FACTOR rows?
Run:  python src/run_scorecard.py   (takes a few minutes — one LLM call per row)

Rules-only mode (ADR-001) — no LLM, no judge, gold qty/unit given; rows the rules can't
resolve are 'needs_llm' and not scored. Writes a NEW dated file, never overwrites:
Run:  python src/run_scorecard.py --no-llm [--out-dir output/scorecards]   (needs a clean git tree)
"""
import argparse
import csv
import json
import hashlib
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from statsmodels.stats.proportion import proportion_confint

from paths import DATA_DIR, BASE_DIR
from extract import extract_with_llm, ExtractedLine
from normalize import normalize_line
from match import load_factors, read_factor_rows
from judge import judge_one

# ---------- judge cache (judge is deterministic at temp=0, so cache by (line, factor)) ----------
_JUDGE_CACHE = DATA_DIR.parent / "output" / "judge_cache.json"
_cache = None


def _judge_cache():
    """Lazy: create output/ and read the judge cache only when the judge path first needs it."""
    global _cache
    if _cache is None:
        _JUDGE_CACHE.parent.mkdir(exist_ok=True)
        _cache = json.load(open(_JUDGE_CACHE)) if _JUDGE_CACHE.exists() else {}
    return _cache


def cached_judge(desc, factor):
    cache = _judge_cache()
    key = hashlib.md5(f"{desc}|{factor['id']}".encode()).hexdigest()
    if key in cache:
        return cache[key]
    v = judge_one(desc, factor).verdict
    cache[key] = v
    json.dump(cache, open(_JUDGE_CACHE, "w"))
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


def run_engine(description, factors, fb_qty=None, fb_unit=None, allow_llm=True):
    """extract -> normalize -> match via the ONE policy. Returns (decision, factor_or_None).
    allow_llm=False: if the rules fast path can't resolve the row, return ('needs_llm', None)."""
    from normalize import has_unsupported_fuel
    if has_unsupported_fuel(description):
        return "escalate", None          # named fuel we don't cover -> honest escalation

    # fast path: if the gold row already gives us activity via canonical alias, skip the LLM
    from normalize import canonical_activity
    guess = canonical_activity(description)
    if guess and fb_unit:
        ex = ExtractedLine(activity=guess, quantity=fb_qty, unit=fb_unit, period=None)
    elif not allow_llm:
        return "needs_llm", None         # rules-only mode: never call the LLM
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

    from match import match_line, resolve_decision
    decision, fac = match_line(norm, factors, raw_text=description)
    decision = resolve_decision(decision, {"raw": {"description": description}})
    return decision, fac


# ================= rules-only scorecard (ADR-001) =================
SCHEMA = "efrecon-scorecard/1"
PROTOCOL = "ADR-001"
MODE = "rules-only (no LLM, no judge)"
M1 = "determination_accuracy_gold_qty_unit_given__rule_resolvable"
M2 = "determination_accuracy_gold_qty_unit_given__all_rows"
P_AT_1 = "precision_at_1_accepted"
COVERAGE = "coverage_should_match"
ESCALATION = "escalation_accuracy"
REFUSAL = "refusal_accuracy"
METRIC_NAMES = [M1, M2, P_AT_1, COVERAGE, ESCALATION, REFUSAL]


def gold_kind(gold):
    """'escalate' | 'refuse' | 'match' for a correct_factor_id value."""
    if gold == "ESCALATE":
        return "escalate"
    if gold in ("NO_FACTOR", ""):
        return "refuse"
    return "match"


def is_correct(gold, decision, factor_id):
    kind = gold_kind(gold)
    if kind == "match":
        return decision == "accept" and factor_id == gold
    return decision == kind


def metric(k, n):
    """k, n, p and the 95% Wilson CI; p and CI are None when n == 0."""
    if n == 0:
        return {"k": k, "n": n, "p": None, "ci95_wilson": None}
    lo, hi = proportion_confint(k, n, alpha=0.05, method="wilson")
    return {"k": k, "n": n, "p": k / n, "ci95_wilson": [float(lo), float(hi)]}


def score_rows(gold_rows, factors, allow_llm=False):
    """Score gold rows per ADR-001. Pure: no judge, no file I/O."""
    per_row = []
    for row in gold_rows:
        desc = row["raw_description"]
        gold = (row["correct_factor_id"] or "").strip()
        fb_qty = row.get("canonical_qty") or None
        fb_unit = row.get("canonical_unit") or None
        fb_qty = float(fb_qty) if fb_qty else None

        decision, fac = run_engine(desc, factors, fb_qty, fb_unit, allow_llm=allow_llm)
        factor_id = fac["factor_id"] if fac else None
        if decision == "needs_llm":
            outcome = "needs_llm"
        else:
            outcome = "correct" if is_correct(gold, decision, factor_id) else "wrong"
        per_row.append({"line_id": row["line_id"], "gold": gold, "decision": decision,
                        "factor_id": factor_id, "outcome": outcome})

    decided = [r for r in per_row if r["outcome"] != "needs_llm"]
    correct = sum(r["outcome"] == "correct" for r in decided)
    accepted = [r for r in decided if r["decision"] == "accept"]
    should_match = [r for r in decided if gold_kind(r["gold"]) == "match"]
    should_esc = [r for r in decided if gold_kind(r["gold"]) == "escalate"]
    should_ref = [r for r in decided if gold_kind(r["gold"]) == "refuse"]

    metrics = {
        M1: metric(correct, len(decided)),
        M2: metric(correct, len(per_row)),
        P_AT_1: metric(sum(r["factor_id"] == r["gold"] for r in accepted), len(accepted)),
        COVERAGE: metric(sum(r["decision"] == "accept" for r in should_match), len(should_match)),
        ESCALATION: metric(sum(r["decision"] == "escalate" for r in should_esc), len(should_esc)),
        REFUSAL: metric(sum(r["decision"] == "refuse" for r in should_ref), len(should_ref)),
    }
    return {"metrics": metrics,
            "needs_llm_ids": [r["line_id"] for r in per_row if r["outcome"] == "needs_llm"],
            "per_row": per_row}


def write_scorecard(result, out_dir, commit_sha, meta):
    """Write scorecard-<YYYY-MM-DD>-<shortsha>.json into out_dir. Raises if it already exists.
    meta: label, generated_utc (ISO, UTC), python, inputs."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"scorecard-{meta['generated_utc'][:10]}-{commit_sha[:7]}.json"
    doc = {
        "schema": SCHEMA,
        "protocol": PROTOCOL,
        "label": meta["label"],
        "commit": commit_sha,
        "generated_utc": meta["generated_utc"],
        "python": meta["python"],
        "mode": MODE,
        "inputs": meta["inputs"],
        "metrics": result["metrics"],
        "needs_llm_ids": result["needs_llm_ids"],
        "per_row": result["per_row"],
    }
    text = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with open(path, "x", encoding="utf-8", newline="\n") as f:   # 'x': never overwrite
        f.write(text)
    return path


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git(*args):
    return subprocess.run(["git", *args], cwd=BASE_DIR, capture_output=True,
                          text=True, check=True).stdout


def _git_state():
    """(full HEAD sha, tree is clean). Clean = `git status --porcelain` is empty."""
    return _git("rev-parse", "HEAD").strip(), _git("status", "--porcelain") == ""


def _tripwire(name):
    def _fail(*args, **kwargs):
        raise RuntimeError(f"--no-llm: {name} must never be called")
    return _fail


def _fmt(name, m):
    if m["n"] == 0:
        return f"{name}: {m['k']}/{m['n']}  (n=0, undefined)"
    lo, hi = m["ci95_wilson"]
    return f"{name}: {m['k']}/{m['n']} = {m['p']:.1%}  (95% Wilson CI {lo:.1%}-{hi:.1%})"


def main_no_llm(out_dir):
    global extract_with_llm, judge_one, load_factors
    commit_sha, clean = _git_state()
    if not clean:
        sys.exit("refusing: git tree is not clean (git status --porcelain is not empty)")

    # tripwires: rules-only mode must never reach the LLM, the judge, or the embedding cache
    extract_with_llm = _tripwire("extract_with_llm")
    judge_one = _tripwire("judge_one")
    load_factors = _tripwire("load_factors")

    gold_path = DATA_DIR / "gold_labels.csv"
    factors_path = DATA_DIR / "emission_factors.csv"
    lock_path = BASE_DIR / "requirements-lock.txt"
    with open(gold_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    result = score_rows(rows, read_factor_rows(factors_path), allow_llm=False)

    now = datetime.now(timezone.utc)
    meta = {
        "label": f"post-internship ({now:%Y-%m-%d}, {commit_sha[:7]}) · provisional · DEV-only (pre-split)",
        "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python": platform.python_version(),
        "inputs": {
            "gold": {"path": "data/gold_labels.csv", "sha256": _sha256(gold_path)},
            "factors": {"path": "data/emission_factors.csv", "sha256": _sha256(factors_path)},
            "requirements_lock": {"path": "requirements-lock.txt", "sha256": _sha256(lock_path)},
        },
    }
    path = write_scorecard(result, out_dir, commit_sha, meta)

    print("SCORECARD — " + MODE + f" — {len(rows)} gold rows")
    for name in METRIC_NAMES:
        print(_fmt(name, result["metrics"][name]))
    print(f"needs_llm ({len(result['needs_llm_ids'])}): {', '.join(result['needs_llm_ids'])}")
    print(f"\nSaved -> {path}")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="EF-Recon scorecard")
    ap.add_argument("--no-llm", action="store_true",
                    help="rules-only scorecard (ADR-001): no LLM, no judge; writes a new dated file")
    ap.add_argument("--out-dir", default=str(BASE_DIR / "output" / "scorecards"),
                    help="where --no-llm writes its scorecard (default output/scorecards)")
    args = ap.parse_args(argv)
    if args.no_llm:
        return main_no_llm(args.out_dir)
    return main_llm()


def main_llm():
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
