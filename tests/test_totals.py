"""P04a A1 (ADR-002): totals never silently mix CO2-only (CEA) and CO2e AR5 (DESNZ)."""
from decimal import Decimal

import match
from totals import factor_bases, sum_by_basis, unit_label, UNKNOWN

CO2 = {"gas_basis": "CO2", "gwp_basis": "CO2"}
AR5 = {"gas_basis": "CO2e", "gwp_basis": "AR5"}
MIXED_LABEL = "kg — MIXED basis (CO2-only + CO2e AR5); not a single-GWP total"


def test_single_co2_only_basis():
    t = sum_by_basis([{"emissions_kg": Decimal("711.700"), **CO2},
                      {"emissions_kg": 100, **CO2}])
    assert t["total_kg"] == Decimal("811.700")
    assert t["by_basis"] == {"CO2/CO2": Decimal("811.700")}
    assert t["basis_mixed"] is False
    assert t["label"] == "kgCO2 (CO2-only)"


def test_single_ar5_basis():
    t = sum_by_basis([{"emissions_kg": "251.000", **AR5}])
    assert t["by_basis"] == {"CO2e/AR5": Decimal("251.000")}
    assert t["basis_mixed"] is False
    assert t["label"] == "kgCO2e (AR5)"


def test_mixed_bases_flagged_and_split():
    t = sum_by_basis([{"emissions_kg": Decimal("711.700"), **CO2},
                      {"emissions_kg": Decimal("251.000"), **AR5},
                      {"emissions_kg": Decimal("0.300"), **CO2}])
    assert t["basis_mixed"] is True
    assert t["label"] == MIXED_LABEL
    assert t["by_basis"] == {"CO2/CO2": Decimal("712.000"), "CO2e/AR5": Decimal("251.000")}
    assert t["total_kg"] == Decimal("963.000")


def test_missing_basis_is_unknown_and_forces_mixed():
    t = sum_by_basis([{"emissions_kg": 5, **AR5},
                      {"emissions_kg": 2, "gas_basis": "CO2e", "gwp_basis": ""},
                      {"emissions_kg": 1}])
    assert t["basis_mixed"] is True
    assert t["by_basis"] == {"CO2e/AR5": Decimal("5"), UNKNOWN: Decimal("3")}
    assert t["total_kg"] == Decimal("8")          # never dropped
    assert "MIXED" in t["label"] and UNKNOWN in t["label"]
    assert sum_by_basis([{"emissions_kg": 1}])["basis_mixed"] is True   # UNKNOWN alone is mixed too


def test_decimal_exactness():
    t = sum_by_basis([{"emissions_kg": 0.1, **AR5}, {"emissions_kg": 0.2, **AR5}])
    assert t["total_kg"] == Decimal("0.3")
    assert 0.1 + 0.2 != 0.3                       # the float bug this avoids


def test_every_factor_has_a_known_basis():
    rows = match.read_factor_rows()
    bases = factor_bases()
    assert rows and {r["factor_id"] for r in rows} <= set(bases)
    for r in rows:
        gas, gwp = bases[r["factor_id"]]
        t = sum_by_basis([{"emissions_kg": 1, "gas_basis": gas, "gwp_basis": gwp}])
        assert UNKNOWN not in t["by_basis"], r["factor_id"]


def test_unit_label_per_line():
    assert unit_label("CO2", "CO2") == "kgCO₂"
    assert unit_label("CO2e", "AR5") == "kgCO₂e (AR5)"
    assert unit_label("CO2e", "AR2") == "kgCO₂e (AR2)"
    assert unit_label("CO2e", "") == "kg (basis UNKNOWN)"
    # ELEC-0001's factor is CO2-only -> never shown as kgCO₂e
    assert unit_label(*factor_bases()["EF-IN-ELEC-GRID"]) == "kgCO₂"


def test_batch_mixed_electricity_and_diesel(api_client):
    r = api_client.post("/batch", json=[
        {"activity": "electricity", "unit": "kWh", "quantity": 1000},
        {"activity": "diesel", "unit": "litre", "quantity": 100},
    ])
    assert r.status_code == 200, r.text
    body = r.json()
    elec, diesel = body["results"]
    assert (elec["decision"], diesel["decision"]) == ("accept", "accept")

    # old fields still there
    for key in ("total_kgco2e", "total_tco2e", "lines_received", "lines_accepted", "results"):
        assert key in body
    assert body["lines_accepted"] == 2
    assert abs(body["total_kgco2e"] - (elec["emissions_kgco2e"] + diesel["emissions_kgco2e"])) <= 1e-9

    # new fields
    assert body["basis_mixed"] is True
    assert body["total_label"] == MIXED_LABEL
    by = body["totals_by_basis"]
    assert set(by) == {"CO2/CO2", "CO2e/AR5"}
    assert Decimal(by["CO2/CO2"]) == Decimal(str(elec["emissions_kgco2e"]))
    assert Decimal(by["CO2e/AR5"]) == Decimal(str(diesel["emissions_kgco2e"]))
