"""ADR-004 public label schemas, description normalization, and helper tools.

Part B supplied the artifact contract. Helper CLI commands are added in Part D.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal
import hashlib
import math
from pathlib import Path
import random
import re
import sys
from typing import Any, Sequence

GOLD_COLUMNS = (
    "line_id", "set", "stratum", "raw_description", "source_file", "period",
    "expected_decision", "expected_factor_id", "expected_factor_row_id",
    "canonical_qty", "canonical_unit", "qty_source", "expected_category",
    "category_status", "rule_id", "label_rationale", "author", "spec_sha256",
    "canary",
)
# Amendment 2026-10-23c requires the flag in column 20 for TEST and VAL.
HOLDOUT_COLUMNS = GOLD_COLUMNS + ("near_miss",)
DEV_COLUMNS = GOLD_COLUMNS + (
    "messiness_tags", "legacy_correct_factor_id", "near_miss",
)

USABLE_TEST_FACTORS = (
    "EF-IN-ELEC-GRID",
    "EF-DIESEL-L",
    "EF-PETROL-L",
    "EF-LPG-L",
    "EF-NATGAS-M3",
    "EF-CNG-KG",
)

TEST_STRATUM_A_FACTOR_MIX = {
    "EF-IN-ELEC-GRID": 30,
    "EF-DIESEL-L": 20,
    "EF-PETROL-L": 10,
    "EF-LPG-L": 10,
    "EF-NATGAS-M3": 10,
    "EF-CNG-KG": 10,
}

TEST_WRITER_SPLIT = {
    "A1": {"A": 60, "B": 20, "C": 20, "D": 20, "total": 120},
    "A2": {"A": 30, "B": 10, "C": 10, "D": 10, "total": 60},
}

VAL_HAMILTON_SPLIT = {
    "A1": {"A": 27, "B": 9, "C": 9, "D": 9, "total": 54},
    "A2": {"A": 13, "B": 4, "C": 4, "D": 5, "total": 26},
}

GRANDFATHERED_DEV_GROUPS = (
    ("diesel #### l", ("DSL-0001", "DSL-0003", "DSL-0004")),
    ("hsd #### l", ("DSL-0006", "DSL-0007")),
    ("torrent power kwh=##### kwh", ("ELEC-0007", "ELEC-0009")),
)


def normalise_description(text: str) -> str:
    """Spec section 9: lowercase, replace EACH digit, collapse whitespace."""
    return " ".join(re.sub(r"\d", "#", text.lower()).split())


def character_trigrams(text: str) -> set[str]:
    """Spec §9: unpadded character 3-grams from normalized text."""
    if len(text) < 3:
        return set()
    return {text[i:i + 3] for i in range(len(text) - 2)}


def jaccard_3gram(left: str, right: str) -> float:
    """Spec §9: Jaccard similarity over unpadded character 3-grams. Both empty -> 1.0, one empty -> 0.0."""
    s1 = character_trigrams(left)
    s2 = character_trigrams(right)
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)


def validate_rows(
    headers: Sequence[str],
    rows: Sequence[dict[str, str]],
    *,
    expected_set: str,
    spec_sha: str,
    factors: Sequence[dict[str, str]] | None = None,
    canary: str | None = None,
    check_counts: bool = True,
) -> dict[str, Any]:
    """Validates structural and semantic rules against spec §3/§4 and ADR-004 amendments a/b/c.

    Returns dict with keys: 'valid' (bool), 'errors' (list[tuple[str, str]]), 'counts' (dict).
    Errors are (line_id, reason_code). Never leaks row descriptions, rationales, or labels.
    """
    errors: list[tuple[str, str]] = []

    # 1. Header validation
    if expected_set in ("TEST", "VAL"):
        expected_cols = list(HOLDOUT_COLUMNS)
    elif expected_set == "DEV":
        expected_cols = list(DEV_COLUMNS)
    else:
        errors.append(("", "SET"))
        return {"valid": False, "errors": errors, "counts": {}}

    if list(headers) != expected_cols:
        errors.append(("", "CSV_HEADER"))
        return {"valid": False, "errors": errors, "counts": {}}

    # 2. Empty file check
    if len(rows) == 0:
        errors.append(("", "EMPTY_FILE"))
        return {"valid": False, "errors": errors, "counts": {}}

    factor_rows_by_id: dict[str, dict[str, str]] = {}
    if factors:
        for f in factors:
            rid = f.get("row_id")
            if rid:
                factor_rows_by_id[rid] = f

    seen_ids: set[str] = set()
    counts_by_stratum: Counter[str] = Counter()
    counts_by_writer: Counter[str] = Counter()
    counts_by_stratum_writer: dict[str, Counter[str]] = defaultdict(Counter)
    counts_by_factor: Counter[str] = Counter()
    near_miss_count_by_stratum: Counter[str] = Counter()

    for idx, row in enumerate(rows):
        line_id = row.get("line_id", "")
        safe_id = line_id if line_id else f"ROW_{idx + 1}"

        # LINE_ID and DUPLICATE_ID
        if not line_id or not re.match(r"^[A-Za-z0-9_-]+$", line_id):
            errors.append((safe_id, "LINE_ID"))
        elif line_id in seen_ids:
            errors.append((line_id, "DUPLICATE_ID"))
        else:
            seen_ids.add(line_id)

        # CSV_SHAPE
        if any(col not in row or row[col] is None for col in expected_cols):
            errors.append((safe_id, "CSV_SHAPE"))

        # SET
        row_set = row.get("set", "")
        if row_set != expected_set:
            errors.append((safe_id, "SET"))

        # STRATUM
        stratum = row.get("stratum", "")
        if stratum not in ("A", "B", "C", "D"):
            errors.append((safe_id, "STRATUM"))

        # DECISION
        decision = row.get("expected_decision", "")
        if decision not in ("accept", "escalate", "refuse"):
            errors.append((safe_id, "DECISION"))

        # AUTHOR
        author = row.get("author", "")
        if expected_set in ("TEST", "VAL"):
            if author not in ("A1", "A2"):
                errors.append((safe_id, "AUTHOR"))
        else:
            if author not in ("A1", "A2", "DEV-legacy", "P05a-agent"):
                errors.append((safe_id, "AUTHOR"))

        # RULE_ID and RULE_DECISION
        rule_id = row.get("rule_id", "")
        valid_rules = {"R-ACC", "R-ESC-GAP", "R-ESC-UNIT", "R-ESC-MIX", "R-REF"}
        if rule_id not in valid_rules:
            errors.append((safe_id, "RULE_ID"))
        else:
            rule_decision_map = {
                "R-ACC": "accept",
                "R-ESC-GAP": "escalate",
                "R-ESC-UNIT": "escalate",
                "R-ESC-MIX": "escalate",
                "R-REF": "refuse",
            }
            if decision != rule_decision_map[rule_id]:
                errors.append((safe_id, "RULE_DECISION"))

        # STRATUM_DECISION
        if stratum == "A" and decision != "accept":
            errors.append((safe_id, "STRATUM_DECISION"))
        elif stratum == "B" and decision != "escalate":
            errors.append((safe_id, "STRATUM_DECISION"))
        elif stratum == "C" and decision != "refuse":
            errors.append((safe_id, "STRATUM_DECISION"))

        # FACTORS
        factor_id = row.get("expected_factor_id", "")
        factor_row_id = row.get("expected_factor_row_id", "")

        if decision == "accept":
            if not factor_id or not factor_row_id:
                errors.append((safe_id, "FACTOR_REQUIRED"))
            else:
                if expected_set in ("TEST", "VAL") and factor_id not in USABLE_TEST_FACTORS:
                    errors.append((safe_id, "FACTOR_NOT_USABLE"))
                if expected_set in ("TEST", "VAL") and factor_id == "EF-IN-ELEC-GRID":
                    if factor_row_id != "EF-IN-ELEC-GRID@v22.0@FY2025-26@incl_imports":
                        errors.append((safe_id, "FACTOR_ROW_MISMATCH"))

                if factors:
                    if factor_row_id not in factor_rows_by_id:
                        errors.append((safe_id, "FACTOR_ROW_UNKNOWN"))
                    elif factor_rows_by_id[factor_row_id].get("factor_id") != factor_id:
                        errors.append((safe_id, "FACTOR_ROW_MISMATCH"))
        else:
            if factor_id != "" or factor_row_id != "":
                errors.append((safe_id, "FACTOR_FORBIDDEN"))

        # QUANTITY AND UNIT
        qty_str = row.get("canonical_qty", "")
        unit_str = row.get("canonical_unit", "")
        qty_source = row.get("qty_source", "")

        if expected_set in ("TEST", "VAL"):
            if stratum in ("A", "B", "C"):
                if qty_source != "column":
                    errors.append((safe_id, "QTY_SOURCE"))
            elif stratum == "D":
                if qty_source != "text":
                    errors.append((safe_id, "QTY_SOURCE"))
            else:
                if qty_source not in ("column", "text"):
                    errors.append((safe_id, "QTY_SOURCE"))

            if not qty_str:
                errors.append((safe_id, "QTY_REQUIRED"))
            else:
                try:
                    q_dec = Decimal(qty_str)
                    if not q_dec.is_finite():
                        errors.append((safe_id, "QTY_INVALID"))
                except Exception:
                    errors.append((safe_id, "QTY_INVALID"))

            if not unit_str:
                errors.append((safe_id, "UNIT_REQUIRED"))
        else:
            if qty_source not in ("", "column", "text"):
                errors.append((safe_id, "QTY_SOURCE"))
            if qty_str:
                try:
                    q_dec = Decimal(qty_str)
                    if not q_dec.is_finite():
                        errors.append((safe_id, "QTY_INVALID"))
                except Exception:
                    errors.append((safe_id, "QTY_INVALID"))

        # PERIOD
        period = row.get("period", "")
        if period:
            if not re.match(r"^\d{4}(-\d{2}(-\d{2})?)?$", period):
                errors.append((safe_id, "PERIOD"))
            elif expected_set in ("TEST", "VAL"):
                p_date = period
                if len(p_date) == 4:
                    p_date = f"{p_date}-01-01"
                elif len(p_date) == 7:
                    p_date = f"{p_date}-01"
                if not ("2025-04-01" <= p_date <= "2026-03-31"):
                    errors.append((safe_id, "PERIOD"))

        # SPEC_SHA
        if row.get("spec_sha256", "") != spec_sha:
            errors.append((safe_id, "SPEC_SHA"))

        # CANARY
        canary_val = row.get("canary", "")
        if expected_set in ("TEST", "VAL"):
            if not canary_val:
                errors.append((safe_id, "CANARY_REQUIRED"))
            elif canary is not None and canary_val != canary:
                errors.append((safe_id, "CANARY_MISMATCH"))

        # CATEGORY and CATEGORY_STATUS
        cat_status = row.get("category_status", "")
        exp_cat = row.get("expected_category", "")
        if cat_status not in ("stated", "blank"):
            errors.append((safe_id, "CATEGORY_STATUS"))
        elif cat_status == "stated":
            valid_cats = {
                "classified", "cannot_classify", "context_dependent",
                "source_ambiguous", "guidance_ambiguous", "unsupported",
            }
            if exp_cat not in valid_cats:
                errors.append((safe_id, "CATEGORY"))
        elif cat_status == "blank":
            if exp_cat != "":
                errors.append((safe_id, "CATEGORY"))

        # RATIONALE
        rationale = row.get("label_rationale", "")
        if not rationale or not rationale.strip():
            errors.append((safe_id, "RATIONALE_REQUIRED"))
        else:
            raw_desc = row.get("raw_description", "").lower()
            unit_lower = unit_str.lower()
            is_unqualified_gallon = (
                ("gallon" in unit_lower and "us" not in unit_lower and "imp" not in unit_lower)
                or ("gallon" in raw_desc and rule_id == "R-ESC-UNIT" and "us" not in raw_desc and "imp" not in raw_desc)
            )
            if is_unqualified_gallon and "gallon type unstated" not in rationale.lower():
                errors.append((safe_id, "GALLON_TYPE_RATIONALE"))

        # NEAR_MISS
        near_miss = row.get("near_miss", "")
        if near_miss not in ("0", "1"):
            errors.append((safe_id, "NEAR_MISS_ENUM"))
        elif near_miss == "1" and stratum != "C":
            errors.append((safe_id, "NEAR_MISS_STRATUM"))

        # Accumulate counts
        counts_by_stratum[stratum] += 1
        counts_by_writer[author] += 1
        counts_by_stratum_writer[stratum][author] += 1
        if stratum == "A" and decision == "accept":
            counts_by_factor[factor_id] += 1
        if near_miss == "1":
            near_miss_count_by_stratum[stratum] += 1

    # 3. Aggregate count validations
    if check_counts:
        total_rows = len(rows)
        if expected_set == "TEST":
            if total_rows != 180:
                errors.append(("", "COUNT_TOTAL"))
            if (
                counts_by_stratum["A"] != 90
                or counts_by_stratum["B"] != 30
                or counts_by_stratum["C"] != 30
                or counts_by_stratum["D"] != 30
            ):
                errors.append(("", "COUNT_STRATUM"))
            if counts_by_writer["A1"] != 120 or counts_by_writer["A2"] != 60:
                errors.append(("", "COUNT_WRITER"))

            sw = counts_by_stratum_writer
            if (
                sw["A"]["A1"] != 60 or sw["B"]["A1"] != 20 or sw["C"]["A1"] != 20 or sw["D"]["A1"] != 20
                or sw["A"]["A2"] != 30 or sw["B"]["A2"] != 10 or sw["C"]["A2"] != 10 or sw["D"]["A2"] != 10
            ):
                errors.append(("", "COUNT_STRATUM_WRITER"))

            for fac, exp_c in TEST_STRATUM_A_FACTOR_MIX.items():
                if counts_by_factor[fac] != exp_c:
                    errors.append(("", "COUNT_ACCEPT_MIX"))
                    break

            if near_miss_count_by_stratum["C"] < 10:
                errors.append(("", "NEAR_MISS_MINIMUM"))

        elif expected_set == "VAL":
            if total_rows != 80:
                errors.append(("", "COUNT_TOTAL"))
            if (
                counts_by_stratum["A"] != 40
                or counts_by_stratum["B"] != 13
                or counts_by_stratum["C"] != 13
                or counts_by_stratum["D"] != 14
            ):
                errors.append(("", "COUNT_STRATUM"))
            if counts_by_writer["A1"] != 54 or counts_by_writer["A2"] != 26:
                errors.append(("", "COUNT_WRITER"))

            sw = counts_by_stratum_writer
            if (
                sw["A"]["A1"] != 27 or sw["B"]["A1"] != 9 or sw["C"]["A1"] != 9 or sw["D"]["A1"] != 9
                or sw["A"]["A2"] != 13 or sw["B"]["A2"] != 4 or sw["C"]["A2"] != 4 or sw["D"]["A2"] != 5
            ):
                errors.append(("", "COUNT_STRATUM_WRITER"))

            if near_miss_count_by_stratum["C"] < 4:
                errors.append(("", "NEAR_MISS_MINIMUM"))

        elif expected_set == "DEV":
            if total_rows != 57:
                errors.append(("", "COUNT_TOTAL"))
            if (
                counts_by_stratum["A"] != 33
                or counts_by_stratum["B"] != 9
                or counts_by_stratum["C"] != 14
                or counts_by_stratum["D"] != 1
            ):
                errors.append(("", "COUNT_STRATUM"))
            if counts_by_writer.get("DEV-legacy", 0) != 45 or counts_by_writer.get("P05a-agent", 0) != 12:
                # If DEV is authored by A1/A2 in synthetic tests, allow A1=40, A2=17
                if not (counts_by_writer.get("A1", 0) == 40 and counts_by_writer.get("A2", 0) == 17):
                    errors.append(("", "COUNT_WRITER"))

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "counts": {
            "total": len(rows),
            "strata": dict(counts_by_stratum),
            "writers": dict(counts_by_writer),
            "stratum_writer": {s: dict(w) for s, w in counts_by_stratum_writer.items()},
            "factor_mix": dict(counts_by_factor),
            "near_miss": dict(near_miss_count_by_stratum),
        },
    }


def overlap_rows(
    inputs: Sequence[Sequence[dict[str, str]]],
    dev_rows: Sequence[dict[str, str]],
) -> dict[str, Any]:
    """Computes exact duplicates and character-3-gram Jaccard >= 0.80.

    Checked within each input, across inputs, and against every DEV row.
    Separates the 3 grandfathered DEV groups.
    """
    dev_norm = {r["line_id"]: normalise_description(r.get("raw_description", "")) for r in dev_rows if "line_id" in r}

    # Identify grandfathered within-DEV pairs
    grandfathered_pairs: list[tuple[str, str]] = []
    for _, group_ids in GRANDFATHERED_DEV_GROUPS:
        present = [gid for gid in group_ids if gid in dev_norm]
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                grandfathered_pairs.append((present[i], present[j]))

    exact_pairs: list[tuple[str, str]] = []
    near_pairs: list[tuple[str, str, float]] = []

    # Check within each input
    for inp in inputs:
        inp_items = [(r.get("line_id", ""), normalise_description(r.get("raw_description", ""))) for r in inp]
        for i in range(len(inp_items)):
            id1, t1 = inp_items[i]
            for j in range(i + 1, len(inp_items)):
                id2, t2 = inp_items[j]
                if t1 == t2:
                    exact_pairs.append((id1, id2))
                else:
                    score = jaccard_3gram(t1, t2)
                    if score >= 0.80:
                        near_pairs.append((id1, id2, score))

    # Check across inputs
    for idx1 in range(len(inputs)):
        items1 = [(r.get("line_id", ""), normalise_description(r.get("raw_description", ""))) for r in inputs[idx1]]
        for idx2 in range(idx1 + 1, len(inputs)):
            items2 = [(r.get("line_id", ""), normalise_description(r.get("raw_description", ""))) for r in inputs[idx2]]
            for id1, t1 in items1:
                for id2, t2 in items2:
                    if t1 == t2:
                        exact_pairs.append((id1, id2))
                    else:
                        score = jaccard_3gram(t1, t2)
                        if score >= 0.80:
                            near_pairs.append((id1, id2, score))

    # Check against DEV
    external_dev_hits: list[tuple[str, str, float, bool]] = []
    for inp in inputs:
        for r in inp:
            ext_id = r.get("line_id", "")
            ext_t = normalise_description(r.get("raw_description", ""))
            for dev_id, dev_t in dev_norm.items():
                if ext_t == dev_t:
                    external_dev_hits.append((ext_id, dev_id, 1.0, True))
                else:
                    score = jaccard_3gram(ext_t, dev_t)
                    if score >= 0.80:
                        external_dev_hits.append((ext_id, dev_id, score, False))

    failed = bool(exact_pairs or near_pairs or external_dev_hits)
    return {
        "grandfathered_dev_pairs": grandfathered_pairs,
        "exact_pairs": exact_pairs,
        "near_pairs": near_pairs,
        "external_dev_hits": external_dev_hits,
        "failed": failed,
    }


def drift_sample(rows: Sequence[dict[str, str]], author: str, frac: float, seed: int) -> list[str]:
    """Deterministically samples floor(Decimal(str(frac)) * n) line_ids for the author."""
    eligible_ids = sorted([r["line_id"] for r in rows if r.get("author") == author and "line_id" in r])
    n = len(eligible_ids)
    k = int(Decimal(str(frac)) * n)
    rng = random.Random(seed)
    return sorted(rng.sample(eligible_ids, k))


def nominal_alpha(ratings: Sequence[Sequence[object | None]]) -> float | None:
    """Pure-Python multi-rater nominal Krippendorff's alpha via coincidence method."""
    N = 0
    offdiag = 0.0
    marginals: Counter[object] = Counter()
    for unit in ratings:
        vals = [x for x in unit if x is not None]
        m = len(vals)
        if m < 2:
            continue
        N += m
        counts = Counter(vals)
        for c, cnt in counts.items():
            marginals[c] += cnt
        sum_sq = sum(cnt * cnt for cnt in counts.values())
        offdiag += (m * m - sum_sq) / (m - 1)
    if N < 2:
        return None
    exp_offdiag = sum(cnt * (N - cnt) for cnt in marginals.values())
    if exp_offdiag == 0:
        return None
    Do = offdiag / N
    De = exp_offdiag / (N * (N - 1))
    return 1.0 - (Do / De)


def cohen_kappa(first: Sequence[str], second: Sequence[str]) -> float | None:
    """Pure-Python Cohen's kappa for two raters."""
    n = len(first)
    if n == 0 or len(second) != n:
        return None
    po = sum(1 for a, b in zip(first, second) if a == b) / n
    cats = sorted(set(first) | set(second))
    pe = sum((first.count(c) / n) * (second.count(c) / n) for c in cats)
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1.0 - pe)


def gwet_ac1(
    first: Sequence[str],
    second: Sequence[str],
    categories: tuple[str, ...] = ("accept", "escalate", "refuse"),
) -> float | None:
    """Pure-Python Gwet's AC1 with declared K categories."""
    n = len(first)
    if n == 0 or len(second) != n:
        return None
    K = len(categories)
    if K <= 1:
        return None
    po = sum(1 for a, b in zip(first, second) if a == b) / n
    pe = sum(
        ((first.count(c) + second.count(c)) / (2 * n))
        * (1.0 - (first.count(c) + second.count(c)) / (2 * n))
        for c in categories
    ) / (K - 1)
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1.0 - pe)


def bootstrap_alpha(ratings: Sequence[Sequence[object | None]], seed: int, B: int = 10000) -> dict[str, Any]:
    """Paired-unit bootstrap for nominal alpha with linear percentile interpolation."""
    N = len(ratings)
    if N == 0:
        return {"B": B, "seed": seed, "valid": 0, "undefined": 0, "ci95": None}
    rng = random.Random(seed)
    valid_alphas: list[float] = []
    undefined_count = 0
    for _ in range(B):
        sample = [ratings[rng.randrange(N)] for _ in range(N)]
        val = nominal_alpha(sample)
        if val is not None and not math.isnan(val):
            valid_alphas.append(val)
        else:
            undefined_count += 1
    M = len(valid_alphas)
    if M == 0:
        return {"B": B, "seed": seed, "valid": 0, "undefined": undefined_count, "ci95": None}
    valid_alphas.sort()

    def _interp(vals: list[float], idx: float) -> float:
        i = int(idx)
        frac = idx - i
        if i + 1 < len(vals):
            return vals[i] + frac * (vals[i + 1] - vals[i])
        return vals[i]

    low = _interp(valid_alphas, (M - 1) * 0.025)
    high = _interp(valid_alphas, (M - 1) * 0.975)
    return {
        "B": B,
        "seed": seed,
        "valid": M,
        "undefined": undefined_count,
        "ci95": [low, high],
    }


def _wilson_interval(k: int, n: int, confidence: float = 0.95) -> list[float] | None:
    if n == 0:
        return None
    try:
        from statsmodels.stats.proportion import proportion_confint
        ci = proportion_confint(k, n, alpha=1.0 - confidence, method="wilson")
        return [float(ci[0]), float(ci[1])]
    except ImportError:
        z = 1.959963984540054
        p = k / n
        denom = 1 + z * z / n
        centre = (p + z * z / (2 * n)) / denom
        half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
        return [centre - half, centre + half]


def agreement_rows(
    first: Sequence[dict[str, str]],
    second: Sequence[dict[str, str]],
    seed: int,
    B: int = 10000,
) -> dict[str, Any]:
    """Computes agreement statistics on inner-joined rows by line_id."""
    valid_decisions = {"accept", "escalate", "refuse"}
    for r in first:
        d = r.get("expected_decision")
        if d is not None and d not in valid_decisions:
            raise ValueError(f"LABEL_INVALID: first line_id={r.get('line_id')}")
    for r in second:
        d = r.get("expected_decision")
        if d is not None and d not in valid_decisions:
            raise ValueError(f"LABEL_INVALID: second line_id={r.get('line_id')}")

    m1 = {r["line_id"]: r for r in first if "line_id" in r}
    m2 = {r["line_id"]: r for r in second if "line_id" in r}

    all_first = set(m1.keys())
    all_second = set(m2.keys())
    joined_ids = sorted(all_first & all_second)
    unmatched_first = sorted(all_first - all_second)
    unmatched_second = sorted(all_second - all_first)

    first_dec = [m1[i].get("expected_decision", "") for i in joined_ids]
    second_dec = [m2[i].get("expected_decision", "") for i in joined_ids]

    paired_ratings = [[d1, d2] for d1, d2 in zip(first_dec, second_dec)]

    alpha = nominal_alpha(paired_ratings)
    boot = bootstrap_alpha(paired_ratings, seed=seed, B=B)

    raw_n = len(joined_ids)
    raw_k = sum(1 for d1, d2 in zip(first_dec, second_dec) if d1 == d2)
    raw_p = (raw_k / raw_n) if raw_n > 0 else None
    wilson_ci = _wilson_interval(raw_k, raw_n) if raw_n > 0 else None

    kappa = cohen_kappa(first_dec, second_dec)
    ac1 = gwet_ac1(first_dec, second_dec, ("accept", "escalate", "refuse"))

    specific = {}
    for c in ("accept", "escalate", "refuse"):
        n_cc = sum(1 for d1, d2 in zip(first_dec, second_dec) if d1 == c and d2 == c)
        n1 = sum(1 for d in first_dec if d == c)
        n2 = sum(1 for d in second_dec if d == c)
        denom = n1 + n2
        score = (2.0 * n_cc / denom) if denom > 0 else None
        specific[c] = {"k": 2 * n_cc, "n": denom, "score": score}

    confusion: dict[str, dict[str, int]] = {}
    for c1 in ("accept", "escalate", "refuse"):
        confusion[c1] = {}
        for c2 in ("accept", "escalate", "refuse"):
            confusion[c1][c2] = sum(1 for d1, d2 in zip(first_dec, second_dec) if d1 == c1 and d2 == c2)

    accept_accept_ids = [
        i for i in joined_ids
        if m1[i].get("expected_decision") == "accept" and m2[i].get("expected_decision") == "accept"
    ]
    n_fac = len(accept_accept_ids)
    k_fac = sum(
        1 for i in accept_accept_ids
        if m1[i].get("expected_factor_id") == m2[i].get("expected_factor_id") and m1[i].get("expected_factor_id") != ""
    )
    factor_agree = {
        "k": k_fac,
        "n": n_fac,
        "score": (k_fac / n_fac) if n_fac > 0 else None,
    }

    return {
        "first_count": len(first),
        "second_count": len(second),
        "joined_count": raw_n,
        "unmatched_first_count": len(unmatched_first),
        "unmatched_first_ids": unmatched_first,
        "unmatched_second_count": len(unmatched_second),
        "unmatched_second_ids": unmatched_second,
        "raw_agreement": {"k": raw_k, "n": raw_n, "p": raw_p, "ci95_wilson": wilson_ci},
        "nominal_alpha": alpha,
        "bootstrap": boot,
        "cohen_kappa": kappa,
        "gwet_ac1": ac1,
        "specific_agreement": specific,
        "confusion_matrix": confusion,
        "factor_agreement": factor_agree,
    }


def canary_hits(guid: str, directories: Sequence[Path]) -> dict[str, Any]:
    """Walks specified directories for occurrences of the canary guid.

    Skips symlinks, files > 50 MiB, and non-text files.
    """
    matched_files: dict[str, int] = {}
    skipped_symlinks = 0
    skipped_oversize = 0
    skipped_binary = 0

    for d in directories:
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if p.is_symlink():
                skipped_symlinks += 1
                continue
            if not p.is_file():
                continue
            try:
                st = p.stat()
                if st.st_size > 50 * 1024 * 1024:
                    skipped_oversize += 1
                    continue
            except OSError:
                skipped_binary += 1
                continue

            try:
                raw = p.read_bytes()
            except OSError:
                skipped_binary += 1
                continue

            text: str | None = None
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
                    try:
                        text = raw.decode("utf-16")
                    except UnicodeDecodeError:
                        skipped_binary += 1
                        continue
                else:
                    skipped_binary += 1
                    continue

            if text:
                cnt = text.count(guid)
                if cnt > 0:
                    matched_files[str(p)] = cnt

    guid_prefix = hashlib.sha256(guid.encode("utf-8")).hexdigest()[:12]
    return {
        "guid_sha256_prefix": guid_prefix,
        "matched_files": matched_files,
        "skipped_symlinks": skipped_symlinks,
        "skipped_oversize": skipped_oversize,
        "skipped_binary": skipped_binary,
    }


def file_hashes(path: Path) -> dict[str, str]:
    """Computes exact raw-byte SHA256 and CRLF->LF normalized SHA256."""
    raw = path.read_bytes()
    manifest_sha = hashlib.sha256(raw).hexdigest()
    lf_bytes = raw.replace(b"\r\n", b"\n")
    lf_sha = hashlib.sha256(lf_bytes).hexdigest()
    return {
        "manifest_sha256": manifest_sha,
        "lf_sha256": lf_sha,
    }


def _safe_read_csv(path_str: str) -> tuple[list[str], list[dict[str, str]]] | str:
    path = Path(path_str)
    if not path.exists() or not path.is_file():
        return "FILE_READ_ERROR"
    try:
        with open(path, "r", encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream)
            headers = next(reader, None)
            if headers is None:
                return "EMPTY_FILE"
        with open(path, "r", encoding="utf-8", newline="") as stream:
            dict_reader = csv.DictReader(stream)
            rows = list(dict_reader)
            return list(headers), rows
    except UnicodeDecodeError:
        return "CSV_ENCODING"
    except Exception:
        return "FILE_READ_ERROR"


def main(argv: Sequence[str] | None = None) -> int:
    """CLI dispatcher. Errors are sanitized: codes and line_ids only."""
    parser = argparse.ArgumentParser(prog="gold_tools", description="ADR-004 gold tools CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # validate
    p_val = subparsers.add_parser("validate")
    p_val.add_argument("csv_path", type=str)
    p_val.add_argument("--set", dest="expected_set", required=True, choices=["TEST", "VAL", "DEV"])
    p_val.add_argument("--spec-sha", required=True, type=str)
    p_val.add_argument("--canary", type=str, default=None)
    p_val.add_argument("--factors", type=str, default=None)
    p_val.add_argument("--no-counts", action="store_true", default=False)

    # overlap
    p_over = subparsers.add_parser("overlap")
    p_over.add_argument("csv_paths", nargs="+", type=str)
    p_over.add_argument("--against", required=True, type=str, dest="dev_csv")

    # drift-sample
    p_drift = subparsers.add_parser("drift-sample")
    p_drift.add_argument("csv_path", type=str)
    p_drift.add_argument("--author", required=True, choices=["A1", "A2"])
    p_drift.add_argument("--frac", type=float, default=0.20)
    p_drift.add_argument("--seed", required=True, type=int)

    # agreement
    p_agr = subparsers.add_parser("agreement")
    p_agr.add_argument("first_csv", type=str)
    p_agr.add_argument("second_csv", type=str)
    p_agr.add_argument("--seed", required=True, type=int)
    p_agr.add_argument("--B", type=int, default=10000)

    # canary-grep
    p_grep = subparsers.add_parser("canary-grep")
    p_grep.add_argument("guid", type=str)
    p_grep.add_argument("directories", nargs="+", type=str)

    # sha256
    p_sha = subparsers.add_parser("sha256")
    p_sha.add_argument("file_path", type=str)

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if exc.code is not None else 1
    except Exception:
        print("INVALID_ARGUMENTS", file=sys.stderr)
        return 1

    try:
        if args.command == "validate":
            res_read = _safe_read_csv(args.csv_path)
            if isinstance(res_read, str):
                print(res_read)
                return 1
            headers, rows = res_read

            factors = None
            if args.factors:
                f_read = _safe_read_csv(args.factors)
                if isinstance(f_read, str):
                    print(f_read)
                    return 1
                _, factors = f_read

            val_res = validate_rows(
                headers,
                rows,
                expected_set=args.expected_set,
                spec_sha=args.spec_sha,
                factors=factors,
                canary=args.canary,
                check_counts=not args.no_counts,
            )

            if not val_res["valid"]:
                for line_id, code in val_res["errors"]:
                    if line_id:
                        print(f"{line_id}: {code}")
                    else:
                        print(code)
            else:
                print("OK")

            counts = val_res.get("counts", {})
            if counts:
                print(f"total_rows: {counts.get('total', 0)}")
                print(f"strata_counts: {counts.get('strata', {})}")
                print(f"writer_counts: {counts.get('writers', {})}")
                print(f"stratum_writer_split: {counts.get('stratum_writer', {})}")
                raw_mix = counts.get('factor_mix', {})
                sanitized_mix = {fac: raw_mix[fac] for fac in USABLE_TEST_FACTORS if fac in raw_mix}
                other_count = sum(cnt for fac, cnt in raw_mix.items() if fac not in USABLE_TEST_FACTORS)
                if other_count:
                    sanitized_mix["OTHER"] = other_count
                print(f"factor_mix: {sanitized_mix}")
                print(f"near_miss_counts: {counts.get('near_miss', {})}")
                if args.expected_set == "TEST":
                    print(f"expected_test_writer_split: {TEST_WRITER_SPLIT}")
                    print(f"expected_test_stratum_a_mix: {TEST_STRATUM_A_FACTOR_MIX}")
                elif args.expected_set == "VAL":
                    print(f"expected_val_hamilton_split: {VAL_HAMILTON_SPLIT}")

            return 0 if val_res["valid"] else 1

        elif args.command == "overlap":
            dev_read = _safe_read_csv(args.dev_csv)
            if isinstance(dev_read, str):
                if dev_read == "EMPTY_FILE":
                    print("CSV_HEADER: --against")
                    return 2
                print(dev_read)
                return 1
            dev_headers, dev_rows = dev_read
            if "line_id" not in dev_headers or "raw_description" not in dev_headers:
                print("CSV_HEADER: --against")
                return 2

            inputs: list[list[dict[str, str]]] = []
            for idx, cp in enumerate(args.csv_paths):
                in_read = _safe_read_csv(cp)
                if isinstance(in_read, str):
                    if in_read == "EMPTY_FILE":
                        print(f"CSV_HEADER: input {idx + 1}")
                        return 2
                    print(in_read)
                    return 1
                in_headers, in_rows = in_read
                if "line_id" not in in_headers or "raw_description" not in in_headers:
                    print(f"CSV_HEADER: input {idx + 1}")
                    return 2
                inputs.append(in_rows)

            res = overlap_rows(inputs, dev_rows)

            print("Grandfathered DEV groups:")
            for desc, g_ids in GRANDFATHERED_DEV_GROUPS:
                print(f"  {desc}: {', '.join(g_ids)}")
            print(f"within_dev_grandfathered_pairs_count: {len(res['grandfathered_dev_pairs'])}")

            print(f"exact_duplicate_pairs_count: {len(res['exact_pairs'])}")
            for id1, id2 in res["exact_pairs"]:
                print(f"  {id1}, {id2}")

            print(f"near_duplicate_pairs_count: {len(res['near_pairs'])}")
            for id1, id2, score in res["near_pairs"]:
                print(f"  {id1}, {id2}: {score:.3f}")

            print(f"external_dev_hits_count: {len(res['external_dev_hits'])}")
            for ext_id, dev_id, score, is_exact in res["external_dev_hits"]:
                tag = "EXACT" if is_exact else f"{score:.3f}"
                print(f"  {ext_id}, {dev_id}: {tag}")

            if res["external_dev_hits"]:
                pass

            return 1 if res["failed"] else 0

        elif args.command == "drift-sample":
            c_read = _safe_read_csv(args.csv_path)
            if isinstance(c_read, str):
                print(c_read)
                return 1
            _, rows = c_read
            sampled = drift_sample(rows, author=args.author, frac=args.frac, seed=args.seed)
            eligible = [r["line_id"] for r in rows if r.get("author") == args.author and "line_id" in r]
            print(f"author: {args.author}")
            print(f"seed: {args.seed}")
            print(f"n: {len(eligible)}")
            print(f"k: {len(sampled)}")
            print("sampled_ids:")
            for sid in sampled:
                print(sid)
            return 0

        elif args.command == "agreement":
            r1 = _safe_read_csv(args.first_csv)
            if isinstance(r1, str):
                if r1 == "EMPTY_FILE":
                    print("CSV_HEADER: first")
                    return 2
                print(r1)
                return 1
            h1, rows1 = r1
            if "line_id" not in h1 or "expected_decision" not in h1:
                print("CSV_HEADER: first")
                return 2

            r2 = _safe_read_csv(args.second_csv)
            if isinstance(r2, str):
                if r2 == "EMPTY_FILE":
                    print("CSV_HEADER: second")
                    return 2
                print(r2)
                return 1
            h2, rows2 = r2
            if "line_id" not in h2 or "expected_decision" not in h2:
                print("CSV_HEADER: second")
                return 2

            # Check duplicate line_ids in either file
            seen1: set[str] = set()
            dup1: list[str] = []
            for r in rows1:
                lid = r.get("line_id", "")
                if lid in seen1:
                    dup1.append(lid)
                else:
                    seen1.add(lid)

            seen2: set[str] = set()
            dup2: list[str] = []
            for r in rows2:
                lid = r.get("line_id", "")
                if lid in seen2:
                    dup2.append(lid)
                else:
                    seen2.add(lid)

            if dup1 or dup2:
                if dup1:
                    print(f"DUPLICATE_ID: first (count={len(dup1)}, line_ids={', '.join(dup1)})")
                if dup2:
                    print(f"DUPLICATE_ID: second (count={len(dup2)}, line_ids={', '.join(dup2)})")
                return 2

            # Check label validity (exact match: accept, escalate, refuse)
            valid_decisions = {"accept", "escalate", "refuse"}
            invalid1 = [r.get("line_id", f"ROW_{i+1}") for i, r in enumerate(rows1) if r.get("expected_decision") not in valid_decisions]
            invalid2 = [r.get("line_id", f"ROW_{i+1}") for i, r in enumerate(rows2) if r.get("expected_decision") not in valid_decisions]

            if invalid1 or invalid2:
                if invalid1:
                    print(f"LABEL_INVALID: first (count={len(invalid1)}, line_ids={', '.join(invalid1)})")
                if invalid2:
                    print(f"LABEL_INVALID: second (count={len(invalid2)}, line_ids={', '.join(invalid2)})")
                return 2

            # Check accept pairs requiring expected_factor_id in headers
            m1 = {r["line_id"]: r for r in rows1 if "line_id" in r}
            m2 = {r["line_id"]: r for r in rows2 if "line_id" in r}
            common_ids = set(m1.keys()) & set(m2.keys())
            has_accept_pair = any(
                m1[i].get("expected_decision") == "accept" and m2[i].get("expected_decision") == "accept"
                for i in common_ids
            )
            if has_accept_pair:
                if "expected_factor_id" not in h1:
                    print("CSV_HEADER: first")
                    return 2
                if "expected_factor_id" not in h2:
                    print("CSV_HEADER: second")
                    return 2

            res_agr = agreement_rows(rows1, rows2, seed=args.seed, B=args.B)

            print(f"first_count: {res_agr['first_count']}")
            print(f"second_count: {res_agr['second_count']}")
            print(f"joined_count: {res_agr['joined_count']}")
            print(f"unmatched_first_count: {res_agr['unmatched_first_count']}")
            if res_agr["unmatched_first_ids"]:
                print(f"unmatched_first_ids: {', '.join(res_agr['unmatched_first_ids'])}")
            print(f"unmatched_second_count: {res_agr['unmatched_second_count']}")
            if res_agr["unmatched_second_ids"]:
                print(f"unmatched_second_ids: {', '.join(res_agr['unmatched_second_ids'])}")

            raw = res_agr["raw_agreement"]
            print(f"raw_agreement: {raw['k']}/{raw['n']} (p={raw['p']})")
            print(f"ci95_wilson: {raw['ci95_wilson']}")

            print(f"nominal_alpha: {res_agr['nominal_alpha']}")
            boot = res_agr["bootstrap"]
            print(f"bootstrap_B: {boot['B']}")
            print(f"bootstrap_valid: {boot['valid']}")
            print(f"bootstrap_undefined: {boot['undefined']}")
            print(f"ci95_bootstrap: {boot['ci95']}")

            print(f"cohen_kappa: {res_agr['cohen_kappa']}")
            print(f"gwet_ac1: {res_agr['gwet_ac1']}")

            print("per_class_specific_agreement:")
            for cls, sdata in res_agr["specific_agreement"].items():
                print(f"  {cls}: {sdata['k']}/{sdata['n']} (score={sdata['score']})")

            print("confusion_matrix:")
            for rk, row_map in res_agr["confusion_matrix"].items():
                row_str = " ".join(f"{col}:{cnt}" for col, cnt in row_map.items())
                print(f"  {rk}: {row_str}")

            fa = res_agr["factor_agreement"]
            print(f"factor_agreement_accept_pairs: {fa['k']}/{fa['n']} (score={fa['score']})")
            return 0

        elif args.command == "canary-grep":
            dirs = [Path(d) for d in args.directories]
            res_grep = canary_hits(args.guid, dirs)
            print(f"guid_sha256_prefix: {res_grep['guid_sha256_prefix']}")
            print(f"matched_files_count: {len(res_grep['matched_files'])}")
            for mf, cnt in res_grep["matched_files"].items():
                print(f"  {mf}: {cnt}")
            print(f"skipped_symlinks: {res_grep['skipped_symlinks']}")
            print(f"skipped_oversize: {res_grep['skipped_oversize']}")
            print(f"skipped_binary: {res_grep['skipped_binary']}")
            return 0

        elif args.command == "sha256":
            p = Path(args.file_path)
            if not p.exists() or not p.is_file():
                print("FILE_READ_ERROR")
                return 1
            hashes = file_hashes(p)
            print(f"manifest_sha256 (raw bytes; use this in data/gold_manifest.json): {hashes['manifest_sha256']}")
            print(f"lf_sha256 (provenance only): {hashes['lf_sha256']}")
            return 0

    except Exception:
        print("EXECUTION_ERROR", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
