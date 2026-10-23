"""ADR-004 C: synthetic tmp_path v2 fixtures; never score the public DEV v2 artifact."""
import csv
from decimal import Decimal
import hashlib
import json
from math import sqrt
from pathlib import Path
import shutil

import pytest

from gold_tools import DEV_COLUMNS, HOLDOUT_COLUMNS
import run_scorecard as legacy
import scorecard_v2 as v2


STAMP = "2026-10-23T00:00:00Z"
SHA = "1234567" + "a" * 33
MARKER = "ZZLEAKZZ"
SPEC_BYTES = b"# Synthetic fixture spec\n"
SPEC_SHA = hashlib.sha256(SPEC_BYTES).hexdigest()
REPO = Path(__file__).resolve().parents[1]


def row(number, stratum="A", tag="accept_right", *, population="DEV", author=None,
        near="0", qty="10", factor="EF-A", row_id="R-A"):
    decision = {"A": "accept", "B": "escalate", "C": "refuse", "D": "accept"}[stratum]
    result = {column: "" for column in DEV_COLUMNS}
    prefix = {"DEV": "S", "TEST": "T", "VAL": "V"}[population]
    result.update({
        "line_id": f"{prefix}-{number:04d}", "set": population, "stratum": stratum,
        "raw_description": MARKER + "-" + tag, "source_file": "synthetic.csv",
        "period": "2025-06-01", "expected_decision": decision,
        "canonical_qty": qty, "canonical_unit": "kWh",
        "qty_source": "text" if stratum == "D" else "column",
        "category_status": "blank", "rule_id": {
            "accept": "R-ACC", "escalate": "R-ESC-GAP", "refuse": "R-REF"}[decision],
        "label_rationale": MARKER + "-rationale",
        "author": author or ("DEV-legacy" if population == "DEV" else "A1"),
        "spec_sha256": SPEC_SHA, "canary": "" if population == "DEV" else "fixture-guid",
        "near_miss": near,
    })
    if decision == "accept":
        result["expected_factor_id"] = factor
        result["expected_factor_row_id"] = row_id
    return result


def write_rows(path, rows, columns=None):
    columns = columns or (DEV_COLUMNS if rows[0]["set"] == "DEV" else HOLDOUT_COLUMNS)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def assert_metric(value, k, n):
    assert (value["k"], value["n"]) == (k, n)
    if n == 0:
        assert value["p"] is None and value["ci95_wilson"] is None
        return
    # Independent Wilson arithmetic, not another call to the production metric().
    z = 1.959963984540054
    p = k / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    assert value["p"] == k / n
    assert value["ci95_wilson"] == pytest.approx([centre - half, centre + half], abs=1e-12)


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    factors = {
        "R-A": {"factor_id": "EF-A", "row_id": "R-A", "factor_kgco2e_per_unit": "0.2",
                "value_status": "PRIMARY", "gas_basis": "CO2", "gwp_basis": "CO2"},
        "R-B": {"factor_id": "EF-B", "row_id": "R-B", "factor_kgco2e_per_unit": "1.2",
                "value_status": "TO_CONFIRM", "gas_basis": "CO2e", "gwp_basis": "AR5"},
    }
    context = v2.FactorContext([{"factor_id": "EF-A"}], factors)
    mapping = {
        "accept_right": ("accept", {"factor_id": "EF-A"}),
        "accept_wrong": ("accept", {"factor_id": "EF-B"}),
        "A_needs": ("needs_llm", None), "D_needs": ("needs_llm", None),
        "escalate_right": ("escalate", None),
        "escalate_wrong": ("accept", {"factor_id": "EF-A"}),
        "refuse_right": ("refuse", None), "refuse_needs": ("needs_llm", None),
    }
    calls = []

    def engine(description, supplied_factors, fb_qty=None, fb_unit=None, allow_llm=True):
        assert allow_llm is False
        assert supplied_factors is context.engine_rows
        calls.append((description, fb_qty, fb_unit))
        assert description.startswith(MARKER + "-"), "nonfixture input reached v2 engine"
        return mapping[description.removeprefix(MARKER + "-")]

    def forbidden(*args, **kwargs):
        raise AssertionError("LLM, judge or embedding loader reached")

    monkeypatch.setattr(v2, "run_engine", engine)
    monkeypatch.setattr(legacy, "extract_with_llm", forbidden)
    monkeypatch.setattr(legacy, "judge_one", forbidden)
    monkeypatch.setattr(legacy, "load_factors", forbidden)
    rows = write_rows(tmp_path / "arithmetic.csv", [
        row(1), row(2, tag="accept_wrong"), row(3, tag="A_needs"),
        row(4, "B", "escalate_right"), row(5, "B", "escalate_wrong"),
        row(6, "C", "refuse_right", near="1"), row(7, "C", "refuse_needs"),
        row(8, "D", "D_needs"),
    ])
    return {"root": tmp_path, "rows": rows, "context": context, "calls": calls, "mapping": mapping}


@pytest.fixture
def cli(scenario, monkeypatch):
    root = scenario["root"]
    data = root / "data"
    data.mkdir()
    (data / "gold_spec_v2.md").write_bytes(SPEC_BYTES)
    (data / "emission_factors.csv").write_text("factor_id,value\nEF-A,0.2\n", encoding="utf-8")
    monkeypatch.setattr(v2, "DATA_DIR", data)
    monkeypatch.setattr(v2, "_git_state", lambda: (SHA, True))
    context_calls = []

    def load(path):
        context_calls.append(path)
        return scenario["context"]

    monkeypatch.setattr(v2, "load_factor_context", load)
    return {**scenario, "data": data, "context_calls": context_calls,
            "input": root / "input.csv", "out": root / "result.json"}


def populate(cli, population="DEV", rows=None):
    return write_rows(cli["input"], rows or [row(1, population=population)])


def manifest(cli, *, digest=None, population="TEST"):
    entry = digest or hashlib.sha256(cli["input"].read_bytes()).hexdigest()
    raw = (json.dumps({"sets": {population: {"sha256": entry}}}, sort_keys=True) + "\n").encode()
    (cli["data"] / "gold_manifest.json").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def run(cli, *extra):
    return v2.main(["--gold-v2", str(cli["input"]), "--out", str(cli["out"]),
                    "--run-at", STAMP, *extra])


def test_metrics_hand_computed_fixture(scenario):
    # ABC = 7, correct = 3 (A-right, B-right, C-right); 2 ABC need LLM.
    # Decided = 5. D needs LLM = 1/1. Both recalls = 1/2; near-miss = 1/1.
    result = v2.score_rows_v2(scenario["rows"], scenario["context"])
    metrics = result["metrics"]
    for name, k, n in [
        (v2.FIXED, 3, 7), (v2.DECIDED, 3, 5), ("coverage_ABC", 5, 7),
        ("d_count_needs_llm", 1, 1), ("escalation_recall", 1, 2),
        ("refusal_recall", 1, 2), ("near_miss_refusal_recall", 1, 1),
    ]:
        assert_metric(metrics[name], k, n)
    assert metrics[v2.DECIDED]["note"] == "not comparable to DEV M1 without this note"
    # D adds one needs_llm to expected accept: accept=(2 accept, 2 needs_llm).
    expected_confusion = {expected: {got: 0 for got in v2.DECISIONS} for expected in v2.DECISIONS}
    expected_confusion["accept"].update(accept=2, needs_llm=2)
    expected_confusion["escalate"].update(accept=1, escalate=1)
    expected_confusion["refuse"].update(refuse=1, needs_llm=1)
    assert metrics["confusion"] == expected_confusion
    assert_metric(metrics["dev_v2"][legacy.M1], 3, 5)
    assert_metric(metrics["dev_v2"][legacy.M2], 3, 8)
    assert metrics["dev_v2"]["label"] == "dev_v2"
    assert "not comparable" in metrics["dev_v2"]["comparison_note"]


def test_needs_llm_a_fixed_and_decided(scenario):
    rows = write_rows(scenario["root"] / "two.csv", [row(1), row(2, tag="A_needs")])
    metrics = v2.score_rows_v2(rows, scenario["context"])["metrics"]
    # One success and one needs_llm: fixed 1/2; decided 1/1; coverage 1/2.
    assert_metric(metrics[v2.FIXED], 1, 2)
    assert_metric(metrics[v2.DECIDED], 1, 1)
    assert_metric(metrics["coverage_ABC"], 1, 2)
    assert metrics["abc_needs_llm_spec_violations"] == {"count": 1, "line_ids": ["S-0002"]}


def test_d_omits_canonical_fields(scenario):
    rows = write_rows(scenario["root"] / "text.csv", [row(1, "D", "D_needs", qty="999")])
    result = v2.score_rows_v2(rows, scenario["context"])
    assert scenario["calls"][0][1:] == (None, None)
    assert result["per_row"][0]["outcome"] == "needs_llm"
    assert_metric(result["metrics"][v2.FIXED], 0, 0)
    assert_metric(result["metrics"]["d_count_needs_llm"], 1, 1)


def test_expected_kg_uses_decimal_and_status(scenario):
    # 0.1 * expected prior-row 0.2 = 0.02, not active-row 0.9 or binary float.
    # Second row: 2.5 * 1.2 = 3.00, flagged TO_CONFIRM and kept out of PRIMARY.
    context = scenario["context"]
    context.by_row_id["R-OLD"] = {**context.by_row_id["R-A"],
                                  "row_id": "R-OLD", "factor_kgco2e_per_unit": "0.2"}
    context.by_row_id["R-A"]["factor_kgco2e_per_unit"] = "0.9"
    rows = write_rows(scenario["root"] / "weights.csv", [
        row(1, qty="0.1", row_id="R-OLD"),
        row(2, tag="accept_wrong", qty="2.5", factor="EF-B", row_id="R-B"),
    ])
    result = v2.score_rows_v2(rows, context)
    weighted = result["metrics"]["weighted"]
    primary = weighted["by_value_status"]["PRIMARY"]
    provisional = weighted["by_value_status"]["TO_CONFIRM"]
    assert Decimal(primary["expected_kgco2e"]) == Decimal("0.02")
    assert Decimal(primary["correct_expected_kgco2e"]) == Decimal("0.02")
    assert Decimal(provisional["expected_kgco2e"]) == Decimal("3")
    assert provisional["excluded_from_PRIMARY"] is True
    assert weighted["to_confirm_ids"] == ["S-0002"]
    assert weighted["release"] == "efl-1"
    assert set(primary["by_basis"]) == {"CO2/CO2"}
    bad = [dict(rows[0], expected_factor_row_id="R-B")]
    with pytest.raises(v2.InputRefused, match="FACTOR_ROW_MISMATCH"):
        v2.score_rows_v2(bad, context)


def test_zero_denominators(scenario):
    # No units: no probability/CI, no claimed perfect-recall bound.
    (scenario["root"] / "empty.csv").write_text(",".join(DEV_COLUMNS) + "\n", encoding="utf-8")
    result = v2.score_rows_v2([], scenario["context"])
    for name in [v2.FIXED, v2.DECIDED, "coverage_ABC", "d_count_needs_llm",
                 "escalation_recall", "refusal_recall"]:
        assert_metric(result["metrics"][name], 0, 0)
    assert result["metrics"]["refusal_recall"]["clopper_pearson_one_sided_lower_95"] is None
    assert result["metrics"]["per_writer"]["slices"] == {}


def test_recall_perfect_adds_one_sided_beta(scenario):
    rows = write_rows(scenario["root"] / "perfect.csv", [
        row(1, "B", "escalate_right"), row(2, "B", "escalate_right")])
    value = v2.score_rows_v2(rows, scenario["context"])["metrics"]["escalation_recall"]
    assert_metric(value, 2, 2)
    # Both successes: the one-sided 95% lower bound solves L**2 = .05.
    assert value["clopper_pearson_one_sided_lower_95"] == pytest.approx(0.05 ** 0.5)
    assert v2.metric_with_perfect_recall_lower(1, 2)[
        "clopper_pearson_one_sided_lower_95"] is None


def test_small_slices_are_merged(scenario):
    # A1/A/R-ACC has n=10 and stays; A2 n=4, B/C and their rules n=2 each pool.
    rows = [row(n, population="TEST", author="A1") for n in range(1, 11)]
    rows += [row(11, "B", "escalate_right", population="TEST", author="A2"),
             row(12, "B", "escalate_right", population="TEST", author="A2"),
             row(13, "C", "refuse_right", population="TEST", author="A2"),
             row(14, "C", "refuse_right", population="TEST", author="A2")]
    rows = write_rows(scenario["root"] / "slices.csv", rows)
    assert len(HOLDOUT_COLUMNS) == 20 and all("near_miss" in r for r in rows)
    metrics = v2.score_rows_v2(rows, scenario["context"])["metrics"]
    for name, retained, merged in [
        ("per_writer", "A1", ["A2"]),
        ("per_stratum", "A", ["B", "C"]),
        ("per_rule_id", "R-ACC", ["R-ESC-GAP", "R-REF"]),
    ]:
        assert metrics[name]["merged_slices"] == merged
        assert_metric(metrics[name]["slices"][retained], 10, 10)
        assert_metric(metrics[name]["slices"]["other_small"], 4, 4)
    assert "dev_v2" not in metrics


def test_required_near_miss_schema(cli, capsys):
    populate(cli, "TEST")
    # An intentionally invalid schema drops column 20 from header AND rows.
    rows = [row(1, population="TEST")]
    write_rows(cli["input"], rows, HOLDOUT_COLUMNS[:-1])
    assert run(cli, "--final", "--adr", "ADR-004") == 2
    assert "CSV_HEADER" in capsys.readouterr().out
    populate(cli, "TEST", [row(1, population="TEST", near="1")])
    manifest(cli)
    assert run(cli, "--final", "--adr", "ADR-004") == 2
    assert "NEAR_MISS_STRATUM" in capsys.readouterr().out
    assert cli["calls"] == [] and cli["context_calls"] == []


def test_test_without_final_rejected_before_engine(cli, capsys):
    populate(cli, "TEST")
    for flags in [(), ("--final",), ("--final", "--adr", "ADR-OTHER")]:
        assert run(cli, *flags) == 2
        output = capsys.readouterr().out
        assert "TEST_FINAL_ADR_REQUIRED" in output and MARKER not in output
        assert not cli["out"].exists()
    assert cli["calls"] == [] and cli["context_calls"] == []


def test_test_final_without_manifest_rejected(cli, capsys):
    populate(cli, "TEST")
    assert run(cli, "--final", "--adr", "ADR-004") == 2
    assert "MANIFEST_MISSING" in capsys.readouterr().out
    assert cli["calls"] == [] and cli["context_calls"] == []
    assert not cli["out"].exists()


def test_test_final_hash_mismatch_rejected(cli, capsys):
    populate(cli, "TEST")
    manifest(cli, digest="0" * 64)
    assert run(cli, "--final", "--adr", "ADR-004") == 2
    assert "MANIFEST_HASH_MISMATCH" in capsys.readouterr().out
    assert cli["calls"] == [] and cli["context_calls"] == []
    assert not cli["out"].exists()
    # Invalid manifest syntax also fails closed without printing its contents.
    (cli["data"] / "gold_manifest.json").write_text(MARKER, encoding="utf-8")
    assert run(cli, "--final", "--adr", "ADR-004") == 2
    output = capsys.readouterr().out
    assert "MANIFEST_INVALID" in output and MARKER not in output


def test_val_final_rejected(cli, capsys):
    rows = populate(cli, "VAL")
    manifest(cli, population="VAL")
    assert run(cli, "--final", "--adr", "ADR-004") == 2
    assert "VAL_NEVER_SCORED" in capsys.readouterr().out
    assert cli["calls"] == [] and cli["context_calls"] == []
    assert not cli["out"].exists()
    with pytest.raises(v2.InputRefused, match="VAL_NEVER_SCORED"):
        v2.score_rows_v2(rows, cli["context"])
    assert cli["calls"] == []


def test_dev_only_cli_scores(cli, capsys):
    populate(cli)
    assert run(cli) == 0
    doc = json.loads(cli["out"].read_bytes())
    assert_metric(doc["metrics"][v2.FIXED], 1, 1)
    assert doc["per_row"][0]["outcome"] == "correct"
    assert cli["calls"][0][1:] == (10.0, "kWh")
    assert MARKER not in capsys.readouterr().out


def test_test_final_matching_manifest_scores_synthetic(cli, capsys):
    populate(cli, "TEST")
    manifest_sha = manifest(cli)
    assert run(cli, "--final", "--adr", "ADR-004") == 0
    doc = json.loads(cli["out"].read_bytes())
    assert doc["manifest_sha256"] == manifest_sha
    assert "ADR-004" in doc["label"] and manifest_sha in doc["label"]
    assert doc["inputs"]["gold"]["file_sha256"] == hashlib.sha256(cli["input"].read_bytes()).hexdigest()
    assert doc["shortfall"]["actual_rows"] == 1
    assert doc["shortfall"]["by_stratum"]["A"]["shortfall"] == 89
    assert doc["shortfall"]["no_top_up_after_sealing"] is True
    assert doc["headline_wilson_lower_below_0_90"] is True
    assert "dev_v2" not in doc["metrics"]
    assert MARKER not in capsys.readouterr().out


def test_mixed_sets_rejected(cli, capsys):
    populate(cli, rows=[row(1), row(2, population="TEST")])
    assert run(cli, "--final", "--adr", "ADR-004") == 2
    assert "SET_MIXED_OR_UNKNOWN" in capsys.readouterr().out
    assert cli["calls"] == [] and cli["context_calls"] == []


def test_scorecard_schema_inputs_and_no_text(cli, capsys):
    populate(cli)
    assert run(cli) == 0
    raw = cli["out"].read_bytes()
    doc = json.loads(raw)
    assert doc["schema"] == "efrecon-scorecard/3" and doc["protocol"] == "ADR-004"
    assert set(doc["per_row"][0]) == set(v2.ROW_KEYS)
    assert "raw_description" not in raw.decode() and "label_rationale" not in raw.decode()
    assert MARKER not in raw.decode() and MARKER not in capsys.readouterr().out
    for key, path in [("gold", cli["input"]), ("spec", cli["data"] / "gold_spec_v2.md")]:
        lf = path.read_bytes().replace(b"\r\n", b"\n")
        expected_blob = hashlib.sha1(b"blob " + str(len(lf)).encode() + b"\0" + lf).hexdigest()
        assert doc["inputs"][key]["git_blob"] == expected_blob
        assert doc["inputs"][key]["sha256"] == hashlib.sha256(lf).hexdigest()
    assert "path" not in doc["inputs"]["gold"]
    assert b"\r\n" not in raw and raw.endswith(b"\n")
    # Writer also drops accidental source fields rather than copying arbitrary row/meta dicts.
    result = {key: doc[key] for key in ("metrics", "per_row", "needs_llm_ids")}
    result["per_row"][0].update(raw_description=MARKER, label_rationale=MARKER)
    path = cli["root"] / "pruned.json"
    meta = {key: doc[key] for key in v2.META_KEYS}
    meta["raw_description"] = MARKER
    v2.write_scorecard_v2(result, path, meta)
    assert MARKER not in path.read_text(encoding="utf-8")


def test_existing_output_refused(cli, capsys):
    populate(cli, "TEST")
    manifest(cli)
    cli["out"].write_bytes(b"keep-existing")
    assert run(cli, "--final", "--adr", "ADR-004") == 2
    assert "OUTPUT_EXISTS" in capsys.readouterr().out
    assert cli["out"].read_bytes() == b"keep-existing"
    assert cli["calls"] == [] and cli["context_calls"] == []
    with pytest.raises(FileExistsError):
        v2.write_scorecard_v2({"per_row": [], "metrics": {}, "needs_llm_ids": []}, cli["out"], {})


def test_legacy_scores_match_frozen(scenario):
    # Public original synthetic DEV only: copy the 45-row inputs, never the v2 artifact.
    root = scenario["root"] / "legacy"
    root.mkdir()
    for relative in ["data/gold_labels.csv", "data/emission_factors.csv",
                     "output/scorecards/scorecard-2026-10-22-32aa5dd.json"]:
        destination = root / Path(relative).name
        shutil.copyfile(REPO / relative, destination)
    with (root / "gold_labels.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    factors = v2.load_factor_context(root / "emission_factors.csv")
    assert len(factors.by_row_id) == 19
    result = legacy.score_rows(rows, factors.engine_rows, allow_llm=False)
    frozen = json.loads((root / "scorecard-2026-10-22-32aa5dd.json").read_bytes())
    for key in ["metrics", "per_row", "needs_llm_ids"]:
        assert result[key] == frozen[key]
    for name, filename in [("gold", "gold_labels.csv"), ("factors", "emission_factors.csv")]:
        entry = v2.input_blob_entry((root / filename).read_bytes())
        for key in ("git_blob", "sha256"):
            assert entry[key] == frozen["inputs"][name][key]
    assert scenario["calls"] == []  # v2 engine was never called.


def test_bad_schema_is_sanitized(cli, capsys):
    for replacement in [
        {"expected_decision": MARKER}, {"line_id": MARKER},
        {"canonical_qty": "NaN"}, {"spec_sha256": MARKER},
    ]:
        populate(cli, rows=[{**row(1), **replacement}])
        assert run(cli) == 2
        assert MARKER not in capsys.readouterr().out
        assert not cli["out"].exists()
    cli["input"].write_bytes(b'set,raw_description\nTEST,"ZZLEAKZZ')
    assert run(cli) == 2
    assert MARKER not in capsys.readouterr().out
    assert cli["calls"] == [] and cli["context_calls"] == []


def test_grandfather_disclosure(cli, capsys):
    populate(cli)
    assert run(cli) == 0
    first = cli["out"].read_bytes()
    doc = json.loads(first)
    assert "3 quantity-only template groups (7 rows) grandfathered, amendment 2026-10-23b" in doc["label"]
    assert "post-internship (23 Oct 2026, 1234567), DEV v2, rules-only, provisional" in doc["label"]
    # Shared evaluation-batch timestamp gives byte-identical repeated synthetic runs.
    second = cli["root"] / "second.json"
    assert v2.main(["--gold-v2", str(cli["input"]), "--out", str(second),
                    "--run-at", STAMP]) == 0
    assert second.read_bytes() == first
    assert MARKER not in capsys.readouterr().out
