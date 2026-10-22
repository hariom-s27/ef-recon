"""P02: EXECUTE the P01 decision branches in the four scripts (evaluate, dedup, calibrate, compute).
Inputs are tiny CSVs in tmp_path; every DATA_DIR / OUTPUT_DIR is redirected there, the PDF
path is disabled, and factors come from the pure reader (cache/network guard in conftest.py)."""
import csv

import pytest

import calibrate
import compute
import dedup
import evaluate
from compute import compute_emissions

ELEC_HEADER = ["line_id", "DISCOM", "Site", "Billing Period", "Units Consumed", "Unit", "Amount (INR)"]
ELEC_ROW = ["ELEC-T1", "UPPCL", "Plant-1", "01-Jun-2025", 1000, "kWh", 8000]
ERP_HEADER = ["line_id", "GL Description", "Quantity", "Unit"]
FURNACE = ["ERP-T2", "Furnace oil 4200 L for boiler", 4200, "L"]
NOISE = ["ERP-T3", "Printer cartridges & stationery", 1, "lot"]
DIESEL_HEADER = ["line_id", "Vendor", "Invoice Date", "Product", "Quantity", "Qty Unit", "Rate (INR)"]

# today's output/computed_emissions.csv header
COMPUTED_HEADER = ["line_id", "activity", "quantity", "unit", "factor_id", "factor_value",
                   "emissions_kgco2e", "match_type", "source"]


def _write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _write_inputs(data_dir, elec_rows, erp_rows):
    data_dir.mkdir()
    _write_csv(data_dir / "electricity_bills.csv", ELEC_HEADER, elec_rows)
    _write_csv(data_dir / "diesel_invoices.csv", DIESEL_HEADER, [])
    _write_csv(data_dir / "erp_spend_export.csv", ERP_HEADER, erp_rows)


def _no_llm(*args, **kwargs):
    raise AssertionError("test reached extract_with_llm")


def _redirect(monkeypatch, mod, data_dir, out_dir, factors):
    """Point one script module at tmp inputs/outputs; no PDF, no LLM, no cache."""
    monkeypatch.setattr(mod, "DATA_DIR", data_dir)
    monkeypatch.setattr(mod, "ingest_pdf", lambda path: [])
    monkeypatch.setattr(mod, "extract_with_llm", _no_llm)
    if hasattr(mod, "load_factors"):
        monkeypatch.setattr(mod, "load_factors", lambda: factors)
    if hasattr(mod, "OUTPUT_DIR"):
        monkeypatch.setattr(mod, "OUTPUT_DIR", out_dir)


@pytest.fixture
def tmp_dirs(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    return tmp_path / "data", out_dir


def _grid_value(factors):
    return next(f["value"] for f in factors if f["factor_id"] == "EF-IN-ELEC-GRID")


# ---------- evaluate.predict() ----------
@pytest.mark.parametrize("source_file, header, row, expected", [
    pytest.param("electricity_bills.csv", ELEC_HEADER, ELEC_ROW,
                 ("ELEC-T1", "EF-IN-ELEC-GRID", "accept"), id="electricity-accept"),
    pytest.param("erp_spend_export.csv", ERP_HEADER, FURNACE,
                 ("ERP-T2", "ESCALATE", "escalate"), id="furnace-oil-escalate"),
    pytest.param("erp_spend_export.csv", ERP_HEADER, NOISE,
                 ("ERP-T3", "NO_FACTOR", "refuse"), id="noise-refuse"),
])
def test_evaluate_predict_decisions(factors, monkeypatch, source_file, header, row, expected):
    monkeypatch.setattr(evaluate, "extract_with_llm", _no_llm)
    record = {"source_file": source_file, "source_row": 2, "source_type": "csv",
              "raw": dict(zip(header, row))}
    result = evaluate.predict(record, factors)
    assert isinstance(result, tuple) and len(result) == 3
    assert result == expected


# ---------- dedup.build_lines() ----------
def test_dedup_build_lines_keeps_only_accepted(factors, monkeypatch, tmp_dirs):
    data_dir, out_dir = tmp_dirs
    _write_inputs(data_dir, [ELEC_ROW], [FURNACE, NOISE])
    _redirect(monkeypatch, dedup, data_dir, out_dir, factors)

    lines = dedup.build_lines()

    assert [ln["line_id"] for ln in lines] == ["ELEC-T1"]
    assert lines[0]["emissions"] == compute_emissions(1000, _grid_value(factors))


# ---------- calibrate.collect_predictions() ----------
def test_calibrate_scores_only_accepted(factors, monkeypatch, tmp_dirs):
    data_dir, out_dir = tmp_dirs
    _write_inputs(data_dir, [ELEC_ROW], [FURNACE, NOISE])
    _redirect(monkeypatch, calibrate, data_dir, out_dir, factors)
    # ERP-T2 is labelled mappable on purpose: only the accept filter may drop it
    gold = {"ELEC-T1": "EF-IN-ELEC-GRID", "ERP-T2": "EF-DIESEL-L", "ERP-T3": "NO_FACTOR"}

    data, precision, correct, total = calibrate.collect_predictions(factors, gold)

    assert data == [(1.0, True)]
    assert all(conf == 1.0 for conf, _ in data)
    assert (precision, correct, total) == (1.0, 1, 1)


# ---------- compute.main() ----------
def _read_out(out_dir):
    with open(out_dir / "computed_emissions.csv", newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def test_compute_main_writes_only_accepted(factors, monkeypatch, tmp_dirs):
    data_dir, out_dir = tmp_dirs
    _write_inputs(data_dir, [ELEC_ROW], [FURNACE])
    _redirect(monkeypatch, compute, data_dir, out_dir, factors)

    compute.main()

    rows = _read_out(out_dir)
    assert rows[0] == COMPUTED_HEADER
    assert len(rows) == 2
    body = dict(zip(rows[0], rows[1]))
    assert body["line_id"] == "ELEC-T1"
    assert body["factor_id"] == "EF-IN-ELEC-GRID"
    assert body["match_type"] == "exact"


@pytest.mark.xfail(strict=True, reason="compute.main indexes results[0]; crashes when no line is "
                                       "accepted — fix later (P03/Block 1)")
def test_compute_main_no_accepted_lines(factors, monkeypatch, tmp_dirs):
    data_dir, out_dir = tmp_dirs
    _write_inputs(data_dir, [], [FURNACE])
    _redirect(monkeypatch, compute, data_dir, out_dir, factors)

    compute.main()

    rows = _read_out(out_dir)
    assert len(rows) == 1      # header only, 0 data rows
