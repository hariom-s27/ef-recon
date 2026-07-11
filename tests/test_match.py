"""Tests for SP-04/09 matching: correct factor, and the bugs we fixed must NEVER return."""
from match import load_factors, exact_match
from normalize import NormalizedLine

FACTORS = load_factors()

def _line(activity, unit):
    return NormalizedLine(activity=activity, unit=unit, quantity=1)

def test_electricity_matches_grid_factor():
    fac = exact_match(_line("electricity", "kwh"), FACTORS)
    assert fac is not None
    assert fac["factor_id"] == "EF-IN-ELEC-GRID"

def test_diesel_matches_diesel_factor():
    fac = exact_match(_line("diesel", "litre"), FACTORS)
    assert fac["factor_id"] == "EF-DIESEL-L"

# --- BUG GUARDS: these lock out bugs we already fixed ---
def test_petrol_does_NOT_match_lpg():
    """Regression guard for the petrol->LPG bug (both are 'litre')."""
    fac = exact_match(_line("petrol", "litre"), FACTORS)
    assert fac["factor_id"] == "EF-PETROL-L"     # must be petrol, NOT lpg

def test_electricity_does_NOT_match_gas():
    """Regression guard for the electricity->natural gas bug."""
    fac = exact_match(_line("electricity", "kwh"), FACTORS)
    assert "NATGAS" not in fac["factor_id"]       # must never be gas