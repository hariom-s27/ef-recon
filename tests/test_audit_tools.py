"""ADR-004 amendment 2026-11-03: audit-sample / audit-apply on synthetic tmp_path scorecards only."""
import csv
import random
import re
from math import sqrt

import pytest

import gold_tools as gt
import run_scorecard as legacy
import scorecard_v2 as v2

SEED = 20261103
MARKER = "ZZLEAKZZ"
CORR_COLS = list(gt.CORRECTION_COLUMNS)
DEFAULT_DECISION = {"A": "accept", "B": "escalate", "C": "refuse", "D": "accept"}
RULE = {"A": "R-ACC", "B": "R-ESC-GAP", "C": "R-REF", "D": "R-ACC"}


def prow(number, stratum="A", outcome="correct", *, decision=None, factor=None, author="A1"):
    decision = decision or ("needs_llm" if outcome == "needs_llm" else DEFAULT_DECISION[stratum])
    if factor is None and decision == "accept":
        factor = "EF-DIESEL-L"
    return {"line_id": f"T-{number:04d}", "stratum": stratum, "rule_id": RULE[stratum],
            "author": author, "decision": decision, "factor_id": factor, "outcome": outcome}


def base_rows():
    # Hand count: 30 correct A; D = {T-0031 A wrong, T-0032 B needs_llm, T-0033 C wrong};
    # two stratum-D rows (T-0034, T-0035) are outside A+B+C. ABC n = 33, k = 30.
    rows = [prow(i) for i in range(1, 31)]
    rows += [prow(31, "A", "wrong", decision="escalate"),
             prow(32, "B", "needs_llm"),
             prow(33, "C", "wrong", decision="accept", factor="EF-PETROL-L"),
             prow(34, "D", "wrong", decision="escalate"),
             prow(35, "D", "needs_llm")]
    return rows


def scorecard(path, per_row, *, headline=None, schema=None):
    abc = [r for r in per_row if r["stratum"] in ("A", "B", "C")]
    k = sum(r["outcome"] == "correct" for r in abc)
    metrics = {v2.FIXED: headline or legacy.metric(k, len(abc))}
    meta = {"label": "synthetic", "commit": "0" * 40, "generated_utc": "2026-11-03T00:00:00Z",
            "python": "3.12", "inputs": {}}
    v2.write_scorecard_v2({"metrics": metrics, "per_row": per_row, "needs_llm_ids": []}, path, meta)
    if schema is not None:
        path.write_text(path.read_text(encoding="utf-8").replace(v2.SCHEMA, schema), encoding="utf-8")
    return path


def corrections(path, rows, headers=CORR_COLS):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def run(capsys, *argv):
    ret = gt.main([str(a) for a in argv])
    cap = capsys.readouterr()
    return ret, cap.out, cap.err


def wilson(k, n):
    # Independent arithmetic, not another call to statsmodels.
    z = 1.959963984540054
    p = k / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [centre - half, centre + half]


def parse_apply(out):
    lines = out.splitlines()
    values = dict(line.split(": ", 1) for line in lines if ": " in line)
    ids = lines[lines.index("corrected_ids:") + 1:]
    return values, ids


def assert_ci(text, k, n):
    lo, hi = (float(x) for x in text.strip("[]").split(","))
    assert [lo, hi] == pytest.approx(wilson(k, n), abs=1e-12)


def test_audit_sets_hand_counted(tmp_path, capsys):
    rows = base_rows()
    sets = gt.audit_sets(rows)
    correct = [f"T-{i:04d}" for i in range(1, 31)]
    assert sets["D"] == ["T-0031", "T-0032", "T-0033"]
    assert len(sets["S"]) == 20 and set(sets["S"]) <= set(correct)
    assert sets["S"] == sorted(sets["S"])
    assert sorted(sets["audit_ids"]) == sorted(sets["D"] + sets["S"])
    assert not {"T-0034", "T-0035"} & set(sets["audit_ids"])
    expected = sorted(sets["D"] + sets["S"])
    random.Random(SEED).shuffle(expected)
    assert sets["audit_ids"] == expected

    ret, out, _ = run(capsys, "audit-sample", scorecard(tmp_path / "s.json", rows))
    assert ret == 0
    assert out.splitlines()[:4] == ["n_D: 3", "n_S: 20", "n_total: 23", f"seed: {SEED}"]


def test_audit_sample_deterministic_per_seed(tmp_path, capsys):
    rows = base_rows()
    first = run(capsys, "audit-sample", scorecard(tmp_path / "a.json", rows))
    again = run(capsys, "audit-sample", scorecard(tmp_path / "b.json", rows))
    reordered = run(capsys, "audit-sample", scorecard(tmp_path / "c.json", list(reversed(rows))))
    assert first == again == reordered


def test_audit_sample_other_seed_changes_sample(tmp_path):
    rows = base_rows()
    default, other = gt.audit_sets(rows, seed=SEED), gt.audit_sets(rows, seed=1)
    assert default["D"] == other["D"]
    assert default["S"] != other["S"]


def test_audit_sample_k_capped_by_correct_rows(tmp_path, capsys):
    few_correct = [prow(i, "A", "wrong", decision="escalate") for i in range(1, 26)]
    few_correct += [prow(i) for i in range(26, 31)]
    ret, out, _ = run(capsys, "audit-sample", scorecard(tmp_path / "few.json", few_correct))
    assert ret == 0
    assert out.splitlines()[:3] == ["n_D: 25", "n_S: 5", "n_total: 30"]
    # max(|D|, min) decides when enough correct rows exist; min > correct caps at all correct.
    assert len(gt.audit_sets(base_rows(), minimum=0)["S"]) == 3
    assert len(gt.audit_sets(base_rows(), minimum=50)["S"]) == 30


def test_audit_sample_output_has_no_membership_marker(tmp_path, capsys):
    rows = base_rows()
    ret, out, err = run(capsys, "audit-sample", scorecard(tmp_path / "s.json", rows))
    lines = out.splitlines()
    assert ret == 0 and err == ""
    assert lines[4] == "audit_ids:"
    assert lines[5:] == gt.audit_sets(rows)["audit_ids"]
    assert len(lines) == 5 + 23
    assert all(re.fullmatch(r"T-\d{4}", line) for line in lines[5:])


@pytest.mark.parametrize("case", ["wrong_schema", "no_per_row", "invalid_json"])
def test_audit_sample_rejects_bad_scorecard(tmp_path, capsys, case):
    path = tmp_path / "bad.json"
    if case == "wrong_schema":
        scorecard(path, base_rows(), schema="efrecon-scorecard/2")
    elif case == "no_per_row":
        path.write_text('{"schema": "efrecon-scorecard/3", "metrics": {}}', encoding="utf-8")
    else:
        path.write_text('{"schema": "efrecon-scorecard/3", "per_row": [' + MARKER, encoding="utf-8")
    fixes = corrections(tmp_path / "c.csv", [])
    for argv in (("audit-sample", path), ("audit-apply", path, fixes)):
        ret, out, err = run(capsys, *argv)
        assert ret == 2
        assert out.strip() == "SCORECARD_SCHEMA"
        assert MARKER not in out + err


def test_audit_apply_hand_arithmetic(tmp_path, capsys):
    rows = base_rows()
    card = scorecard(tmp_path / "s.json", rows)
    s_row = gt.audit_sets(rows)["S"][0]
    d_fix = ["T-0031", "escalate", "", "R-ESC-GAP"]  # engine escalated: D row flips to correct
    s_fix = [s_row, "refuse", "", "R-REF"]  # engine accepted: S row flips to wrong
    for name, fixes, k, in_d, in_s in [
        ("both", [d_fix, s_fix], 30, 1, 1),
        ("d_only", [d_fix], 31, 1, 0),
        ("s_only", [s_fix], 29, 0, 1),
    ]:
        ret, out, _ = run(capsys, "audit-apply", card, corrections(tmp_path / f"{name}.csv", fixes))
        assert ret == 0, name
        values, ids = parse_apply(out)
        assert values["as_labelled"] == "30/33"
        assert_ci(values["as_labelled_ci95_wilson"], 30, 33)
        assert values["audited"] == f"{k}/33"
        assert_ci(values["audited_ci95_wilson"], k, 33)
        assert (values["corrections_in_D"], values["corrections_in_S"]) == (str(in_d), str(in_s))
        assert ids == sorted(f[0] for f in fixes)


def test_audit_apply_needs_llm_stays_wrong_and_factor_must_match(tmp_path, capsys):
    card = scorecard(tmp_path / "s.json", base_rows())
    # T-0032 engine needs_llm: stays wrong. T-0033 engine accept EF-PETROL-L: factor must match.
    mismatch = corrections(tmp_path / "m.csv", [
        ["T-0032", "escalate", "", "R-ESC-GAP"], ["T-0033", "accept", "EF-DIESEL-L", "R-ACC"]])
    match = corrections(tmp_path / "ok.csv", [["T-0033", "accept", "EF-PETROL-L", "R-ACC"]])
    ret, out, _ = run(capsys, "audit-apply", card, mismatch)
    assert ret == 0 and parse_apply(out)[0]["audited"] == "30/33"
    ret, out, _ = run(capsys, "audit-apply", card, match)
    assert ret == 0 and parse_apply(out)[0]["audited"] == "31/33"


ERROR_CASES = {
    "header_wrong": (dict(headers=["line_id", "corrected_decision", "spec_rule", "corrected_factor_id"]),
                     [], "CSV_HEADER", None),
    "empty_file": (None, None, "CSV_HEADER", None),
    "decision_invalid": ({}, [["T-0031", "Accept", "EF-DIESEL-L", "R-ACC"]], "LABEL_INVALID", "T-0031"),
    "accept_without_factor": ({}, [["T-0031", "accept", "", "R-ACC"]], "LABEL_INVALID", "T-0031"),
    "factor_on_non_accept": ({}, [["T-0031", "escalate", "EF-DIESEL-L", "R-ESC-GAP"]], "LABEL_INVALID", "T-0031"),
    "spec_rule_unknown": ({}, [["T-0031", "escalate", "", "R-ESC-OTHER"]], "LABEL_INVALID", "T-0031"),
    "rule_decision": ({}, [["T-0031", "escalate", "", "R-REF"]], "RULE_DECISION", "T-0031"),
    "not_in_audit_list": ({}, [["T-0034", "escalate", "", "R-ESC-GAP"]], "NOT_IN_AUDIT_LIST", "T-0034"),
    "duplicate_id": ({}, [["T-0031", "escalate", "", "R-ESC-GAP"]] * 2, "DUPLICATE_ID", "T-0031"),
    "scorecard_schema": ({}, [], "SCORECARD_SCHEMA", None),
    "headline_mismatch": ({}, [], "SCORECARD_SCHEMA detail=headline_mismatch", None),
}


@pytest.mark.parametrize("case", list(ERROR_CASES))
def test_audit_apply_error_codes(tmp_path, capsys, case):
    kwargs, fix_rows, code, bad_id = ERROR_CASES[case]
    rows = base_rows()
    headline = legacy.metric(29, 33) if case == "headline_mismatch" else None
    schema = "efrecon-scorecard/2" if case == "scorecard_schema" else None
    card = scorecard(tmp_path / "s.json", rows, headline=headline, schema=schema)
    fixes = tmp_path / "c.csv"
    if kwargs is None:
        fixes.write_text("", encoding="utf-8")
    else:
        corrections(fixes, fix_rows, **kwargs)
    ret, out, _ = run(capsys, "audit-apply", card, fixes)
    assert ret == 2
    assert out.splitlines()[0].startswith(code)
    if bad_id:
        assert bad_id in out
    assert "audited" not in out and "as_labelled" not in out


def test_audit_apply_accepts_bom_corrections(tmp_path, capsys):
    card = scorecard(tmp_path / "s.json", base_rows())
    plain = corrections(tmp_path / "plain.csv", [["T-0031", "escalate", "", "R-ESC-GAP"]])
    bom = tmp_path / "bom.csv"
    bom.write_bytes(b"\xef\xbb\xbf" + plain.read_bytes())
    expected = run(capsys, "audit-apply", card, plain)
    assert expected[0] == 0
    assert run(capsys, "audit-apply", card, bom) == expected


def test_audit_commands_redact_row_text(tmp_path, capsys):
    rows = base_rows()
    for r in rows:
        if r["decision"] == "accept":
            r["factor_id"] = MARKER + "-factor"
    card = scorecard(tmp_path / "s.json", rows)
    label_words = re.compile(r"\b(accept|escalate|refuse|needs_llm|correct|wrong|R-[A-Z-]+)\b")

    ret, out, err = run(capsys, "audit-sample", card)
    assert ret == 0 and MARKER not in out + err and not label_words.search(out)

    good = corrections(tmp_path / "good.csv", [["T-0031", "accept", MARKER + "-factor", "R-ACC"]])
    ret, out, err = run(capsys, "audit-apply", card, good)
    assert ret == 0 and MARKER not in out + err and not label_words.search(out)

    bad = corrections(tmp_path / "bad.csv", [[MARKER + " secret row text", "refuse", MARKER, MARKER]])
    ret, out, err = run(capsys, "audit-apply", card, bad)
    assert ret == 2 and MARKER not in out + err
    assert "ROW_1" in out


def test_audit_constants_match_scorecard_v2():
    assert gt.SCORECARD_SCHEMA_ID == v2.SCHEMA
    assert gt.ABC_FIXED_KEY == v2.FIXED
    assert set(gt.SCORECARD_ROW_KEYS) <= set(v2.ROW_KEYS)
    assert gt.SPEC_RULE_DECISIONS == v2.RULE_DECISIONS
