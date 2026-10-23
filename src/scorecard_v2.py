"""ADR-004 v2 rules-only scoring; legacy scoring and engine policy are unchanged."""
import argparse
from collections import defaultdict
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import subprocess

from statsmodels.stats.proportion import proportion_confint

from factor_library import RELEASE, read_rows
from gold_tools import DEV_COLUMNS, HOLDOUT_COLUMNS
from paths import BASE_DIR, DATA_DIR
from run_scorecard import (
    M1, M2, MODE, _git_state, metric, read_factor_rows, run_engine,
)


SCHEMA = "efrecon-scorecard/3"
PROTOCOL = "ADR-004"
FIXED = "determination_accuracy_gold_qty_unit_given__ABC_fixed"
DECIDED = "determination_accuracy_gold_qty_unit_given__decided"
COMPARABILITY_NOTE = "not comparable to DEV M1 without this note"
GRANDFATHER_NOTE = (
    "3 quantity-only template groups (7 rows) grandfathered, amendment 2026-10-23b"
)
DECISIONS = ("accept", "escalate", "refuse", "needs_llm")
RULE_DECISIONS = {
    "R-ACC": "accept", "R-ESC-GAP": "escalate", "R-ESC-UNIT": "escalate",
    "R-ESC-MIX": "escalate", "R-REF": "refuse",
}
ROW_KEYS = ("line_id", "stratum", "rule_id", "author", "decision", "factor_id", "outcome")
META_KEYS = (
    "label", "commit", "tree_clean", "generated_utc", "python", "inputs",
    "manifest_sha256", "shortfall", "headline_wilson_lower_below_0_90",
)
CLIENT_TZ = timezone(timedelta(hours=5, minutes=30))


class InputRefused(ValueError):
    """A fixed reason code, never an input value or exception representation."""


@dataclass(frozen=True)
class FactorContext:
    engine_rows: list[dict]
    by_row_id: dict[str, dict]


def load_factor_context(path: Path) -> FactorContext:
    physical = read_rows(path)
    by_id = {row["row_id"]: row for row in physical}
    if len(by_id) != len(physical):
        raise InputRefused("FACTOR_ROW_DUPLICATE")
    return FactorContext(read_factor_rows(path), by_id)


def _decimal(value):
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        raise InputRefused("QTY_INVALID") from None
    if not number.is_finite():
        raise InputRefused("QTY_INVALID")
    return number


def _validate_rows(rows, population):
    """Structural admission only; pre-seal target counts belong to the helper CLI."""
    seen = set()
    for row in rows:
        identity = row["line_id"]
        if not re.fullmatch(r"[A-Z][A-Z0-9]*-\d{4}", identity) or identity in seen:
            raise InputRefused("LINE_ID")
        if population == "TEST" and not re.fullmatch(r"T-\d{4}", identity):
            raise InputRefused("LINE_ID")
        seen.add(identity)
        if row["set"] != population or row["stratum"] not in "ABCD" or len(row["stratum"]) != 1:
            raise InputRefused("ROW_SCHEMA")
        decision = row["expected_decision"]
        if decision not in DECISIONS[:3] or RULE_DECISIONS.get(row["rule_id"]) != decision:
            raise InputRefused("RULE_DECISION")
        if row["stratum"] in "ABC" and decision != {
                "A": "accept", "B": "escalate", "C": "refuse"}[row["stratum"]]:
            raise InputRefused("STRATUM_DECISION")
        authors = {"DEV-legacy", "P05a-agent"} if population == "DEV" else {"A1", "A2"}
        if row["author"] not in authors:
            raise InputRefused("AUTHOR")
        if row["near_miss"] not in {"0", "1"}:
            raise InputRefused("NEAR_MISS_ENUM")
        if row["near_miss"] == "1" and row["stratum"] != "C":
            raise InputRefused("NEAR_MISS_STRATUM")
        if row["qty_source"] != ("text" if row["stratum"] == "D" else "column"):
            raise InputRefused("QTY_SOURCE")
        required_qty = population != "DEV" or decision == "accept" or row["stratum"] == "D"
        if required_qty and (not row["canonical_qty"] or not row["canonical_unit"]):
            raise InputRefused("QTY_REQUIRED")
        if row["canonical_qty"]:
            _decimal(row["canonical_qty"])
        if decision == "accept":
            if not row["expected_factor_id"] or not row["expected_factor_row_id"]:
                raise InputRefused("FACTOR_REQUIRED")
        elif row["expected_factor_id"] or row["expected_factor_row_id"]:
            raise InputRefused("FACTOR_FORBIDDEN")
        if not row["raw_description"] or not row["label_rationale"]:
            raise InputRefused("ROW_REQUIRED")


def _manifest_match(path, file_sha):
    try:
        raw = Path(path).read_bytes()
        manifest = json.loads(raw.decode("utf-8"))
        expected = manifest["sets"]["TEST"]["sha256"]
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
            raise InputRefused("MANIFEST_INVALID")
    except FileNotFoundError:
        raise InputRefused("MANIFEST_MISSING") from None
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        raise InputRefused("MANIFEST_INVALID") from None
    if expected.lower() != file_sha:
        raise InputRefused("MANIFEST_HASH_MISMATCH")
    return hashlib.sha256(raw).hexdigest()


def preflight_gold(path: Path, *, final: bool, adr: str | None, manifest_path: Path) -> dict:
    """Inspect set metadata first; no engine or output side effect until admission.

    The captured bytes are used for both manifest verification and subsequent scoring.
    """
    try:
        data = Path(path).read_bytes()
        text = data.decode("utf-8")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        headers = next(reader)
        if headers.count("set") != 1:
            raise InputRefused("CSV_HEADER")
        set_index = headers.index("set")
        populations = set()
        count = 0
        for values in reader:
            if len(values) != len(headers):
                raise InputRefused("CSV_SHAPE")
            populations.add(values[set_index])
            count += 1
    except (OSError, UnicodeError, csv.Error):
        raise InputRefused("FILE_READ_ERROR") from None
    except StopIteration:
        raise InputRefused("EMPTY_FILE") from None
    if "VAL" in populations:
        raise InputRefused("VAL_NEVER_SCORED")
    if count == 0:
        raise InputRefused("EMPTY_FILE")
    if len(populations) != 1 or not populations <= {"DEV", "TEST"}:
        raise InputRefused("SET_MIXED_OR_UNKNOWN")
    population = next(iter(populations))
    expected_headers = DEV_COLUMNS if population == "DEV" else HOLDOUT_COLUMNS
    if tuple(headers) != expected_headers:
        raise InputRefused("CSV_HEADER")
    file_sha = hashlib.sha256(data).hexdigest()
    manifest_sha = None
    if population == "TEST":
        if not final or adr != PROTOCOL:
            raise InputRefused("TEST_FINAL_ADR_REQUIRED")
        manifest_sha = _manifest_match(manifest_path, file_sha)
    # Full row dictionaries are materialized for scoring only after the set/hash gate.
    rows = list(csv.DictReader(io.StringIO(text, newline=""), strict=True))
    _validate_rows(rows, population)
    return {"data": data, "rows": rows, "set": population,
            "manifest_sha256": manifest_sha}


def metric_with_perfect_recall_lower(k: int, n: int) -> dict:
    result = metric(k, n)
    result["clopper_pearson_one_sided_lower_95"] = None
    if n > 0 and k == n:
        # For k=n, L=(0.05)**(1/n). beta(alpha=.10) uses lower tail alpha/2=.05:
        # its lower endpoint is therefore the one-sided 95% Clopper-Pearson bound.
        result["clopper_pearson_one_sided_lower_95"] = float(
            proportion_confint(k, n, method="beta", alpha=0.10)[0])
    return result


def slice_metrics(rows: list[dict], field: str) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[row[field]].append(row)
    merged = sorted(key for key, group in groups.items() if len(group) < 10)
    pooled = []
    for key in merged:
        pooled.extend(groups.pop(key))
    if pooled:
        groups["other_small"] = pooled
    return {
        "population": "ABC",
        "merged_slices": merged,
        "slices": {key: metric(sum(r["outcome"] == "correct" for r in group), len(group))
                   for key, group in sorted(groups.items())},
    }


def _expected_weights(rows, factors):
    weights = {}
    with localcontext() as context:
        context.prec = 100
        for row in rows:
            if row["expected_decision"] != "accept":
                continue
            factor = factors.by_row_id.get(row["expected_factor_row_id"])
            if factor is None or factor["factor_id"] != row["expected_factor_id"]:
                raise InputRefused("FACTOR_ROW_MISMATCH")
            status = factor["value_status"]
            if status not in {"PRIMARY", "TO_CONFIRM"}:
                raise InputRefused("FACTOR_STATUS")
            value = _decimal(factor["factor_kgco2e_per_unit"])
            weights[row["line_id"]] = {
                "kg": _decimal(row["canonical_qty"]) * value,
                "value_status": status,
                "basis": factor["gas_basis"] + "/" + factor["gwp_basis"],
            }
    return weights


def _weighted(weights, outcomes):
    result = {}
    with localcontext() as context:
        context.prec = 100
        for status in ("PRIMARY", "TO_CONFIRM"):
            entries = [(identity, value) for identity, value in weights.items()
                       if value["value_status"] == status]
            by_basis = {}
            for basis in sorted({value["basis"] for _, value in entries}):
                part = [(identity, value) for identity, value in entries if value["basis"] == basis]
                by_basis[basis] = {
                    "rows": len(part),
                    "expected_kgco2e": str(sum((value["kg"] for _, value in part), Decimal(0))),
                }
            result[status] = {
                "rows": len(entries),
                "expected_kgco2e": str(sum((value["kg"] for _, value in entries), Decimal(0))),
                "correct_expected_kgco2e": str(sum(
                    (value["kg"] for identity, value in entries if outcomes[identity] == "correct"),
                    Decimal(0))),
                "by_basis": by_basis,
                "excluded_from_PRIMARY": status == "TO_CONFIRM",
            }
    return {"release": RELEASE, "by_value_status": result,
            "to_confirm_ids": sorted(identity for identity, value in weights.items()
                                     if value["value_status"] == "TO_CONFIRM")}


def summarize_v2(per_row: list[dict], gold_rows: list[dict], expected_weights: dict) -> dict:
    combined = [{**gold, **got} for gold, got in zip(gold_rows, per_row, strict=True)]
    abc = [row for row in combined if row["stratum"] in "ABC"]
    decided = [row for row in abc if row["decision"] != "needs_llm"]
    d_rows = [row for row in combined if row["stratum"] == "D"]
    correct = sum(row["outcome"] == "correct" for row in abc)
    violations = [row["line_id"] for row in abc if row["decision"] == "needs_llm"]
    secondary = metric(correct, len(decided))
    secondary["note"] = COMPARABILITY_NOTE
    confusion = {expected: {got: 0 for got in DECISIONS} for expected in DECISIONS}
    for row in combined:
        confusion[row["expected_decision"]][row["decision"]] += 1
    result = {
        FIXED: metric(correct, len(abc)),
        "abc_needs_llm_spec_violations": {"count": len(violations), "line_ids": violations},
        DECIDED: secondary,
        "coverage_ABC": metric(len(decided), len(abc)),
        "d_count_needs_llm": metric(sum(r["decision"] == "needs_llm" for r in d_rows), len(d_rows)),
        "confusion": confusion,
        "per_writer": slice_metrics(abc, "author"),
        "per_stratum": slice_metrics(abc, "stratum"),
        "per_rule_id": slice_metrics(abc, "rule_id"),
        "weighted": _weighted(expected_weights, {r["line_id"]: r["outcome"] for r in combined}),
    }
    for expected in ("escalate", "refuse"):
        group = [row for row in combined if row["expected_decision"] == expected]
        name = "escalation_recall" if expected == "escalate" else "refusal_recall"
        result[name] = metric_with_perfect_recall_lower(
            sum(row["decision"] == expected for row in group), len(group))
    if gold_rows and all("near_miss" in row for row in gold_rows):
        near = [r for r in combined if r["stratum"] == "C"
                and r["expected_decision"] == "refuse" and r["near_miss"] == "1"]
        result["near_miss_refusal_recall"] = metric(
            sum(r["decision"] == "refuse" for r in near), len(near))
    if gold_rows and all(row["set"] == "DEV" for row in gold_rows):
        all_decided = [r for r in combined if r["decision"] != "needs_llm"]
        all_correct = sum(r["outcome"] == "correct" for r in combined)
        result["dev_v2"] = {
            "label": "dev_v2",
            "comparison_note": "not comparable to 32aa5dd: rows changed",
            M1: metric(all_correct, len(all_decided)),
            M2: metric(all_correct, len(combined)),
        }
    return result


def score_rows_v2(rows: list[dict], factors: FactorContext) -> dict:
    """Pure rules-only scoring. D deliberately receives neither fallback field."""
    if any(row.get("set") == "VAL" for row in rows):
        raise InputRefused("VAL_NEVER_SCORED")
    weights = _expected_weights(rows, factors)
    per_row = []
    for row in rows:
        if row["stratum"] == "D":
            qty, unit = None, None
        else:
            qty = float(row["canonical_qty"]) if row["canonical_qty"] else None
            unit = row["canonical_unit"] or None
        decision, factor = run_engine(
            row["raw_description"], factors.engine_rows, qty, unit, allow_llm=False)
        if decision not in DECISIONS:
            raise InputRefused("ENGINE_DECISION")
        factor_id = factor["factor_id"] if factor else None
        expected = row["expected_decision"]
        correct = (decision == "accept" and factor_id == row["expected_factor_id"]
                   if expected == "accept" else decision == expected)
        outcome = "needs_llm" if decision == "needs_llm" else "correct" if correct else "wrong"
        per_row.append({
            "line_id": row["line_id"], "stratum": row["stratum"], "rule_id": row["rule_id"],
            "author": row["author"], "decision": decision, "factor_id": factor_id,
            "outcome": outcome,
        })
    return {
        "metrics": summarize_v2(per_row, rows, weights),
        "needs_llm_ids": [row["line_id"] for row in per_row if row["outcome"] == "needs_llm"],
        "per_row": per_row,
    }


def input_blob_entry(data: bytes, *, public_path: str | None = None) -> dict:
    normalized = data.replace(b"\r\n", b"\n")
    result = {
        "git_blob": hashlib.sha1(
            b"blob " + str(len(normalized)).encode("ascii") + b"\0" + normalized).hexdigest(),
        "sha256": hashlib.sha256(normalized).hexdigest(),
        "file_sha256": hashlib.sha256(data).hexdigest(),
    }
    if public_path is not None:
        result["path"] = public_path
    return result


def write_scorecard_v2(result: dict, out_path: Path, meta: dict) -> Path:
    out_path = Path(out_path)
    if out_path.exists():
        raise FileExistsError
    if any(key not in meta for key in ("label", "commit", "generated_utc", "python", "inputs")):
        raise InputRefused("SCORECARD_METADATA")
    # Allowlist fields rather than passing through an arbitrary source-row dictionary.
    per_row = [{key: row[key] for key in ROW_KEYS} for row in result["per_row"]]
    doc = {
        "schema": SCHEMA, "protocol": PROTOCOL, "mode": MODE,
        **{key: meta[key] for key in META_KEYS if key in meta},
        "metrics": result["metrics"], "needs_llm_ids": result["needs_llm_ids"],
        "per_row": per_row,
    }
    serialized = json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(serialized)
    return out_path


def _run_time(text):
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00")) if text else datetime.now(
            timezone.utc)
        if result.tzinfo is None or result.utcoffset() != timedelta(0):
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise InputRefused("RUN_TIME_INVALID") from None


def _shortfalls(rows, population):
    if population != "TEST":
        return None
    expected = {"A": 90, "B": 30, "C": 30, "D": 30}
    actual = {key: sum(r["stratum"] == key for r in rows) for key in expected}
    return {"expected_rows": 180, "actual_rows": len(rows),
            "by_stratum": {key: {"expected": n, "actual": actual[key],
                                "shortfall": max(0, n - actual[key])}
                           for key, n in expected.items()},
            "no_top_up_after_sealing": True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ADR-004 v2 rules-only scorecard")
    parser.add_argument("--gold-v2", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--final", action="store_true")
    parser.add_argument("--adr")
    parser.add_argument("--run-at", help="shared evaluation-batch timestamp, ISO UTC")
    args = parser.parse_args(argv)
    try:
        admission = preflight_gold(
            args.gold_v2, final=args.final, adr=args.adr,
            manifest_path=DATA_DIR / "gold_manifest.json")
        rows, population = admission["rows"], admission["set"]
        now = _run_time(args.run_at)
        commit, clean = _git_state()
        client_date = now.astimezone(CLIENT_TZ)
        suffix = "dev-v2" if population == "DEV" else "final"
        out = args.out or BASE_DIR / "output" / "scorecards" / (
            f"scorecard-{client_date:%Y-%m-%d}-{commit[:7]}-{suffix}.json")
        if out.exists():
            raise InputRefused("OUTPUT_EXISTS")
        spec_data = (DATA_DIR / "gold_spec_v2.md").read_bytes()
        spec_entry = input_blob_entry(spec_data, public_path="data/gold_spec_v2.md")
        if any(row["spec_sha256"] != spec_entry["sha256"] for row in rows):
            raise InputRefused("SPEC_SHA")
        factor_path = DATA_DIR / "emission_factors.csv"
        context = load_factor_context(factor_path)
        # All entry modes call only the rules-only scorer.
        result = score_rows_v2(rows, context)
        gold_entry = input_blob_entry(admission["data"])
        gold_entry["set"] = population
        inputs = {
            "gold": gold_entry, "spec": spec_entry,
            "factors": input_blob_entry(factor_path.read_bytes(),
                                        public_path="data/emission_factors.csv"),
            "factor_release": RELEASE,
        }
        if population == "DEV":
            label = (f"post-internship ({client_date:%d %b %Y}, {commit[:7]}), DEV v2, "
                     f"rules-only, provisional; {GRANDFATHER_NOTE}")
        else:
            label = f"final {PROTOCOL}; manifest_sha256={admission['manifest_sha256']}"
        lower = result["metrics"][FIXED]["ci95_wilson"]
        meta = {
            "label": label, "commit": commit, "tree_clean": clean,
            "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "python": platform.python_version(), "inputs": inputs,
            "manifest_sha256": admission["manifest_sha256"],
            "shortfall": _shortfalls(rows, population),
            "headline_wilson_lower_below_0_90": lower[0] < 0.90 if lower else None,
        }
        write_scorecard_v2(result, out, meta)
        print("SCORECARD", PROTOCOL, population, "rows", len(rows))
        print(json.dumps(result["metrics"], sort_keys=True))
        print("SCORECARD_WRITTEN")
        return 0
    except InputRefused as error:
        print("REFUSED", str(error))
        return 2
    except FileExistsError:
        print("REFUSED OUTPUT_EXISTS")
        return 2
    except (OSError, UnicodeError, csv.Error, ValueError, KeyError, TypeError,
            OverflowError, subprocess.CalledProcessError):
        # Never echo input text, paths, gold labels, or a raw exception.
        print("REFUSED INPUT_OR_SCORING_ERROR")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
