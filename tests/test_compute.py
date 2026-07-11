"""Tests for SP-05 compute: quantity × factor must be exact."""
from decimal import Decimal
from compute import compute_emissions

def test_electricity_emissions_are_exact():
    # 36098 kWh × 0.7117 = 25690.947 (exactly, via Decimal)
    result = compute_emissions(36098, 0.7117)
    assert result == Decimal("25690.947")

def test_diesel_emissions_are_exact():
    # 2076 litre × 2.51 = 5210.760
    result = compute_emissions(2076, 2.51)
    assert result == Decimal("5210.760")

def test_zero_quantity_gives_zero():
    assert compute_emissions(0, 0.7117) == Decimal("0.000")