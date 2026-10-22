"""P01 contract: every module decides through ONE function, match.match_line(),
and maps 'escalate_or_refuse' through ONE helper, match.resolve_decision()."""
import ast
import csv
from pathlib import Path

import pytest

import match
from extract import ExtractedLine
from normalize import normalize_line
from paths import DATA_DIR

SRC_DIR = Path(match.__file__).parent

# (activity, unit, quantity) -> target (decision, factor_id)
# NOTE: the two natural-gas rows reflect the CURRENT tie behaviour (EF-PNG-KWH beats
# EF-NATGAS-KWH). Block 1 will change them; that is a deliberate later change.
CONTRACT = [
    pytest.param("electricity", "kWh", 1000, "accept", "EF-IN-ELEC-GRID", id="electricity"),
    pytest.param("diesel", "litre", 100, "accept", "EF-DIESEL-L", id="diesel"),
    pytest.param("furnace oil", "litre", 100, "escalate", None, id="furnace-oil"),
    pytest.param("pet coke", "tonne", 5, "escalate", None, id="pet-coke"),
    pytest.param("lpg", "kg", 10, "escalate", None, id="lpg-kg"),
    pytest.param("solar", "kWh", 500, "escalate", None, id="solar"),
    pytest.param("natural gas", "kWh", 1000, "accept", "EF-PNG-KWH", id="natural-gas"),
    pytest.param("png", "kWh", 1000, "accept", "EF-PNG-KWH", id="png"),
    # gasket: 'unit' is kWh only for electricity -> no unit -> escalate_or_refuse -> not ambiguous -> refuse
    pytest.param("gasket", "unit", 3, "refuse", None, id="gasket"),
]

ALL_INPUTS = [pytest.param(*p.values[:3], id=p.id) for p in CONTRACT]


def _post(client, activity, unit, quantity):
    r = client.post("/compute", json={"activity": activity, "unit": unit, "quantity": quantity})
    assert r.status_code == 200, r.text
    return r.json()


def _calls_or_constants(name, kind):
    """file:line of every call to `name` (kind='call') or string constant `name` (kind='const') in src/."""
    hits = []
    for path in sorted(SRC_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if kind == "call" and isinstance(node, ast.Call):
                fn = node.func
                found = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
            elif kind == "const" and isinstance(node, ast.Constant):
                found = node.value
            else:
                continue
            if found == name:
                hits.append((path.name, node.lineno))
    return hits


# ---------- T1 ----------
@pytest.mark.parametrize("activity,unit,quantity,decision,factor_id", CONTRACT)
def test_api_decision_contract(api_client, activity, unit, quantity, decision, factor_id):
    body = _post(api_client, activity, unit, quantity)
    assert (body["decision"], body["factor_id"]) == (decision, factor_id)
    if decision != "accept":
        assert body["match_type"] == "none"
        assert body["confidence"] is None          # never -1.0


# ---------- T2 ----------
@pytest.mark.parametrize("activity,unit,quantity", ALL_INPUTS)
def test_api_matches_match_line(api_client, factors, activity, unit, quantity):
    from match import resolve_decision
    norm = normalize_line(ExtractedLine(activity=activity, quantity=quantity, unit=unit, period=None))
    decision, fac = match.match_line(norm, factors, raw_text=f"{activity} {unit}")
    decision = resolve_decision(decision, {"raw": {"activity": activity, "unit": unit}})
    expected = (decision, fac["factor_id"] if fac else None)

    body = _post(api_client, activity, unit, quantity)
    assert (body["decision"], body["factor_id"]) == expected


# ---------- T3 ----------
@pytest.mark.parametrize("activity,unit,quantity", [
    pytest.param("furnace oil", "litre", 100, id="furnace-oil"),
    pytest.param("widgets", "kg", 5, id="widgets"),
])
def test_api_never_accepts_by_cosine(api_client, monkeypatch, factors, activity, unit, quantity):
    import api
    diesel = next(f for f in factors if f["factor_id"] == "EF-DIESEL-L")

    def _fake_semantic(norm, facs):
        return diesel, 0.99

    monkeypatch.setattr(match, "semantic_match", _fake_semantic)
    monkeypatch.setattr(api, "semantic_match", _fake_semantic, raising=False)
    body = _post(api_client, activity, unit, quantity)
    assert body["decision"] != "accept"


# ---------- T4 ----------
def test_semantic_match_not_used_for_decisions():
    offenders = [f"{f}:{n}" for f, n in _calls_or_constants("semantic_match", "call") if f != "match.py"]
    assert offenders == []


# ---------- T5 ----------
def test_batch_counts_only_accepted(api_client):
    r = api_client.post("/batch", json=[
        {"activity": "electricity", "unit": "kWh", "quantity": 1000},
        {"activity": "furnace oil", "unit": "litre", "quantity": 100},
    ])
    assert r.status_code == 200, r.text
    body = r.json()
    elec = body["results"][0]
    assert elec["decision"] == "accept"
    assert body["lines_accepted"] == 1
    assert abs(body["total_kgco2e"] - elec["emissions_kgco2e"]) <= 1e-9


# ---------- T6 ----------
@pytest.mark.parametrize("activity,unit,quantity,expected_unit", [
    pytest.param("electricity", "units", 10, "kWh", id="electricity-units"),
    pytest.param("gasket", "unit", 3, None, id="gasket-unit"),
])
def test_unit_word_means_kwh_only_for_electricity(activity, unit, quantity, expected_unit):
    norm = normalize_line(ExtractedLine(activity=activity, quantity=quantity, unit=unit, period=None))
    assert norm.unit == expected_unit


# ---------- T7 ----------
def test_read_factor_rows_is_pure(_no_cache_no_network):
    rows = match.read_factor_rows()
    with open(DATA_DIR / "emission_factors.csv", newline="", encoding="utf-8") as f:
        csv_ids = list(dict.fromkeys(row["factor_id"] for row in csv.DictReader(f)))

    assert len(rows) == 11
    assert all(r["vector"] is None for r in rows)
    assert [r["factor_id"] for r in rows] == csv_ids
    assert _no_cache_no_network == []


# ---------- T8: resolve_decision, both record shapes ----------
@pytest.mark.parametrize("decision", ["accept", "escalate", "refuse"])
def test_resolve_decision_passes_through(decision):
    assert match.resolve_decision(decision, {"raw": {"activity": "fuel"}}) == decision


@pytest.mark.parametrize("record,expected", [
    # the shape api.py builds
    pytest.param({"raw": {"activity": "gasket", "unit": "unit"}}, "refuse", id="api-gasket"),
    pytest.param({"raw": {"activity": "fuel expenses", "unit": "litre"}}, "escalate", id="api-fuel"),
    # the full ingest_csv record app.py / compute.py / evaluate.py pass (erp_spend_export.csv rows)
    pytest.param({"source_file": "erp_spend_export.csv", "source_row": 8, "source_type": "csv",
                  "raw": {"line_id": "ERP-0007", "GL Description": "Fuel expenses (mixed vehicles)",
                          "Quantity": 489, "Unit": "litre"}}, "escalate", id="ingest-csv-fuel"),
    pytest.param({"source_file": "erp_spend_export.csv", "source_row": 6, "source_type": "csv",
                  "raw": {"line_id": "ERP-0005", "GL Description": "Printer cartridges & stationery",
                          "Quantity": 1, "Unit": "lot"}}, "refuse", id="ingest-csv-noise"),
    # an ingest_pdf record has no 'raw' key -> nothing ambiguous to read -> refuse (current app.py behaviour)
    pytest.param({"source_file": "electricity_bill_sample.pdf", "source_page": 1, "source_type": "pdf",
                  "raw_text": "some page text"}, "refuse", id="ingest-pdf"),
])
def test_resolve_decision_record_shapes(record, expected):
    assert match.resolve_decision("escalate_or_refuse", record) == expected


# ---------- T9 ----------
def test_escalate_or_refuse_mapped_only_in_match():
    offenders = [f"{f}:{n}" for f, n in _calls_or_constants("escalate_or_refuse", "const") if f != "match.py"]
    assert offenders == []
