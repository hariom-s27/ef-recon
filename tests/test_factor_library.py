"""ADR-003 efl-1 selection, provenance/status and consumer regression checks."""
import ast
import csv
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

import config
import match
import factor_library as library
from paths import DATA_DIR

GRID = "EF-IN-ELEC-GRID"
CM = GRID + "-CM"

# Independent snapshot of the original eleven-row order and exact numeric strings.
ORIGINAL = [
    (GRID, "0.7117"),
    (CM, "0.7383"),
    ("EF-DIESEL-L", "2.51"),
    ("EF-PETROL-L", "2.09"),
    ("EF-NATGAS-M3", "2.04"),
    ("EF-NATGAS-KWH", "0.18290"),
    ("EF-LPG-L", "1.557"),
    ("EF-CNG-KG", "2.54"),
    ("EF-COAL-T", "2380"),
    ("EF-IN-ELEC-SOLAR", "0"),
    ("EF-PNG-KWH", "0.18290"),
]


def _by_locator(rows, locator):
    return next(row for row in rows if row["source_locator"] == locator)


def _write_rows(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_row_ids_are_unique():
    rows = library.read_rows()
    assert len(rows) == 19
    assert len({row["row_id"] for row in rows}) == len(rows)


def test_active_ids_keep_original_order():
    """KC #21: GRID before SOLAR and every other original tie order is retained."""
    selected = library.select_active(library.read_rows(), config.REPORTING_FY)
    assert [row["factor_id"] for row in selected] == [pair[0] for pair in ORIGINAL]


def test_default_uses_current_including_imports_AA14():
    rows = library.read_rows()
    before = deepcopy(rows)
    selected = library.select_active(rows, config.REPORTING_FY)
    assert config.REPORTING_FY == "2025-26"
    assert len(selected) == len({row["factor_id"] for row in rows}) == 11
    expected = _by_locator(rows, "Results!AA14")
    chosen = next(row for row in selected if row["factor_id"] == GRID)
    assert chosen == expected
    assert chosen["factor_kgco2e_per_unit"] == expected["factor_kgco2e_per_unit"]
    assert chosen["factor_kgco2e_per_unit"] != "0.7117"
    assert chosen["source_locator"] == "Results!AA14"
    assert chosen["variant"] == "incl_imports"
    assert chosen["value_status"] == "PRIMARY"
    assert rows == before


def test_previous_fy_uses_current_v22_restatement():
    rows = library.read_rows()
    selected = library.select_active(rows, "2024-25")
    chosen = next(row for row in selected if row["factor_id"] == GRID)
    assert chosen == _by_locator(rows, "Results!Z14")
    assert chosen["source_version"] == "v22.0"
    assert chosen["known_to"] == ""
    assert rows[0]["known_to"] == "2026-08"


@pytest.mark.parametrize("fy", ["2023-24", "2026-27"])
def test_missing_fy_raises(fy):
    with pytest.raises(ValueError, match="expected exactly one active row"):
        library.select_active(library.read_rows(), fy)


def test_ambiguous_current_default_raises():
    rows = library.read_rows()
    duplicate = dict(_by_locator(rows, "Results!AA14"), row_id="duplicate-current-row")
    with pytest.raises(ValueError, match="found 2"):
        library.select_active(rows + [duplicate], "2025-26")


def test_no_default_raises():
    rows = library.read_rows()
    for row in rows:
        if row["factor_id"] == GRID:
            row["is_default"] = "0"
    with pytest.raises(ValueError, match="found 0"):
        library.select_active(rows, "2025-26")


@pytest.mark.parametrize("fy", ["2025", "FY2025-26", "2025-27"])
def test_invalid_fy_raises(fy):
    with pytest.raises(ValueError, match="Invalid reporting FY"):
        library.select_active(library.read_rows(), fy)


@pytest.mark.parametrize("start,end", [
    ("2025-04-01", ""), ("", "2026-03-31"),
    ("20250401", "2026-03-31"), ("2026-04-01", "2025-03-31"),
])
def test_malformed_validity_raises(start, end):
    rows = library.read_rows()
    row = _by_locator(rows, "Results!AA14")
    row.update(valid_from=start, valid_to=end)
    with pytest.raises(ValueError):
        library.select_active(rows, "2025-26")


def test_blank_validity_non_cea_rows_always_active():
    rows = [r for r in library.read_rows() if r["factor_id"] not in (GRID, CM)]
    assert library.select_active(rows, "1990-91") == rows
    assert library.select_active(rows, "2030-31") == rows


def test_original_ids_and_value_strings_unchanged():
    rows = library.read_rows()
    assert [(r["factor_id"], r["factor_kgco2e_per_unit"]) for r in rows[:11]] == ORIGINAL


def test_no_regional_wording_in_csv():
    assert "regional" not in (DATA_DIR / "emission_factors.csv").read_text(encoding="utf-8").lower()


def test_projection_preserves_row_status_and_reporting_fy(monkeypatch):
    monkeypatch.setattr(config, "REPORTING_FY", "2024-25")
    projected = match.read_factor_rows()
    assert [r["factor_id"] for r in projected] == [p[0] for p in ORIGINAL]
    raw = _by_locator(library.read_rows(), "Results!Z14")
    chosen = next(r for r in projected if r["factor_id"] == GRID)
    assert chosen["row_id"] == raw["row_id"]
    assert chosen["value_status"] == raw["value_status"]
    assert chosen["reporting_fy"] == "2024-25"
    assert chosen["valid_from"] == "2024-04-01"
    assert chosen["valid_to"] == "2025-03-31"
    assert chosen["source_locator"] == "Results!Z14"
    assert all(r["vector"] is None for r in projected)


def test_factor_bases_uses_active_rows(tmp_path):
    from totals import factor_bases
    rows = library.read_rows()
    for row in rows:
        if row["factor_id"] == GRID and row["source_locator"] != "Results!AA14":
            row["gas_basis"] = "NOT_ACTIVE"
    path = tmp_path / "factors.csv"
    _write_rows(path, rows)
    assert factor_bases(path)[GRID] == ("CO2", "CO2")


def test_cache_key_changes_with_fy_release_and_csv_content(tmp_path):
    path = tmp_path / "data" / "emission_factors.csv"
    path.parent.mkdir()
    original = (DATA_DIR / "emission_factors.csv").read_bytes()
    path.write_bytes(original)
    default = library.cache_path(path, "2025-26")
    previous = library.cache_path(path, "2024-25")
    path.write_bytes(original + b"\n")
    changed = library.cache_path(path, "2025-26")
    assert len({default, previous, changed}) == 3
    assert "efl-1" in default.name
    assert default.name != "factors_cache.pkl"
    assert not default.exists() and not previous.exists() and not changed.exists()


@pytest.mark.parametrize("activity,unit,status", [
    ("electricity", "kWh", "PRIMARY"), ("diesel", "litre", "TO_CONFIRM"),
])
def test_api_exposes_status_and_factor_row_id(api_client, activity, unit, status):
    response = api_client.post("/compute", json={"activity": activity, "quantity": 100, "unit": unit})
    assert response.status_code == 200
    body = response.json()
    assert body["value_status"] == status
    selected = library.read_active()
    raw = next(r for r in selected if r["factor_id"] == body["factor_id"])
    assert body["factor_row_id"] == raw["row_id"]
    assert "value_status=" + status in body["trace"]
    assert "REPORTING_FY=2025-26" in body["trace"]
    if activity == "electricity":
        assert "2025-04-01..2026-03-31" in body["trace"]
        expected = float(raw["factor_kgco2e_per_unit"])
        assert body["factor_value"] == expected


@pytest.mark.parametrize("activity,unit", [("furnace oil", "litre"), ("stationery", "lot")])
def test_no_factor_result_still_has_null_status_fields(api_client, activity, unit):
    response = api_client.post("/compute", json={"activity": activity, "quantity": 10, "unit": unit})
    assert response.status_code == 200
    body = response.json()
    assert body["factor_id"] is None
    assert body["value_status"] is None
    assert body["factor_row_id"] is None


def test_generator_uses_active_rows_and_only_writes_tmp_path(tmp_path, monkeypatch):
    import generate_synthetic_bills as gen
    expected = library.read_active()
    output = tmp_path / "generated"
    gen.main(output)
    assert list(gen.FACTORS) == [p[0] for p in ORIGINAL]
    assert gen.FACTORS[GRID]["row_id"] == _by_locator(expected, "Results!AA14")["row_id"]
    assert gen.FACTORS == {r["factor_id"]: r for r in expected}
    with open(output / "gold_labels.csv", newline="", encoding="utf-8") as stream:
        generated = [r for r in csv.DictReader(stream) if r["correct_factor_id"] == GRID]
    assert generated
    factor = float(gen.FACTORS[GRID]["factor_kgco2e_per_unit"])
    for row in generated:
        expected_kg = round(float(row["canonical_qty"]) * factor, 3)
        assert Decimal(row["expected_kgco2e"]) == Decimal(str(expected_kg))


def _dashboard_process():
    """Load only the pure pipeline function; do not launch Streamlit or its LLM flows."""
    import compute
    import dedup
    import extract
    import normalize
    tree = ast.parse((Path(match.__file__).parent / "app.py").read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "process")
    namespace = {
        "extract_with_rules": extract.extract_with_rules,
        "normalize_line": normalize.normalize_line,
        "match_line": match.match_line, "resolve_decision": match.resolve_decision,
        "compute_emissions": compute.compute_emissions,
        "fingerprint": dedup.fingerprint, "get_site": dedup.get_site,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), "app.process", "exec"), namespace)
    return namespace["process"]


def _diesel_record():
    return {"source_type": "csv", "source_file": "fixture.csv", "source_row": 2,
            "raw": {"line_id": "DIESEL-T1", "Product": "Diesel", "Quantity": "100",
                    "Qty Unit": "litre", "Vendor": "Test", "Invoice Date": "01-Jun-2025"}}


def test_dashboard_retains_status_on_accepted_duplicate_and_no_factor():
    diesel = _diesel_record()
    noise = {"source_type": "csv", "source_file": "fixture.csv", "source_row": 4,
             "raw": {"line_id": "NOISE-T1", "GL Description": "Stationery",
                     "Quantity": "1", "Unit": "lot"}}
    rows = _dashboard_process()([diesel, deepcopy(diesel), noise], match.read_factor_rows())
    assert [r["decision"] for r in rows] == ["accept", "duplicate", "refuse"]
    for row in rows[:2]:
        assert row["value_status"] == "TO_CONFIRM"
        assert row["factor_row_id"] == "EF-DIESEL-L@DEFRA GHG conversion factors"
    assert rows[2]["value_status"] is None and rows[2]["factor_row_id"] is None


def test_compute_prints_status_with_unchanged_csv_header(tmp_path, monkeypatch, capsys):
    import compute
    record = _diesel_record()
    monkeypatch.setattr(compute, "load_factors", match.read_factor_rows)
    monkeypatch.setattr(compute, "ingest_csv",
                        lambda path: [record] if path.name == "diesel_invoices.csv" else [])
    monkeypatch.setattr(compute, "ingest_pdf", lambda path: [])
    monkeypatch.setattr(compute, "OUTPUT_DIR", tmp_path)
    compute.main()
    assert "value_status=TO_CONFIRM" in capsys.readouterr().out
    with open(tmp_path / "computed_emissions.csv", newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == [
            "line_id", "activity", "quantity", "unit", "factor_id", "factor_value",
            "emissions_kgco2e", "match_type", "source"]
        assert len(list(reader)) == 1

