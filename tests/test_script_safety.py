"""P02: scripts can never silently destroy data — generator never writes data/,
calibrate never overwrites the baseline unasked, hard_cases.csv mirrors the gold HARD rows."""
import csv
import hashlib
import importlib.util
import json

import pytest

import calibrate
import generate_synthetic_bills as gen
from paths import DATA_DIR

CSV_OUTPUTS = {"electricity_bills.csv", "diesel_invoices.csv", "erp_spend_export.csv", "gold_labels.csv"}


def _data_hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(DATA_DIR.iterdir()) if p.is_file()}


# ---------- generator ----------
def test_generator_refuses_data_dir(tmp_path):
    before = _data_hashes()

    with pytest.raises(SystemExit):
        gen.main(DATA_DIR)
    with pytest.raises(SystemExit):
        gen.main(DATA_DIR / "sub")
    assert not (DATA_DIR / "sub").exists()

    out = tmp_path / "gen"
    gen.main(out)
    expected = set(CSV_OUTPUTS)
    if importlib.util.find_spec("reportlab") is not None:
        expected.add("electricity_bill_sample.pdf")
    assert {p.name for p in out.iterdir()} == expected

    assert _data_hashes() == before


def test_generator_refuses_existing_files(tmp_path):
    (tmp_path / "gold_labels.csv").write_bytes(b"keep")

    with pytest.raises(SystemExit):
        gen.main(tmp_path)

    assert (tmp_path / "gold_labels.csv").read_bytes() == b"keep"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["gold_labels.csv"]


# ---------- calibrate baseline ----------
def test_calibrate_does_not_overwrite_baseline(tmp_path, monkeypatch):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"precision": 0.9}, indent=2))
    monkeypatch.setattr(calibrate, "BASELINE_FILE", baseline)
    original = baseline.read_bytes()

    assert calibrate.regression_check(0.5, update_baseline=True) == "FAIL"
    assert baseline.read_bytes() == original

    assert calibrate.regression_check(0.95) == "PASS"
    assert baseline.read_bytes() == original

    assert calibrate.regression_check(0.95, update_baseline=True) == "PASS"
    assert json.loads(baseline.read_text()) == {"precision": 0.95}


def test_calibrate_no_baseline_not_created(tmp_path, monkeypatch):
    baseline = tmp_path / "baseline.json"
    monkeypatch.setattr(calibrate, "BASELINE_FILE", baseline)

    assert calibrate.regression_check(0.8) == "NO_BASELINE"
    assert not baseline.exists()


# ---------- data/hard_cases.csv ----------
def test_hard_cases_match_gold():
    with open(DATA_DIR / "gold_labels.csv", newline="", encoding="utf-8") as f:
        gold = [(r["line_id"], r["raw_description"]) for r in csv.DictReader(f)
                if r["line_id"].startswith("HARD-")]
    with open(DATA_DIR / "hard_cases.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == ["line_id", "raw_description"]
        hard = [(r["line_id"], r["raw_description"]) for r in reader]

    assert len(gold) == 13
    assert hard == gold
