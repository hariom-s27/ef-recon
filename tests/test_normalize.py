"""Tests for SP-03 normalization: units must convert correctly."""
from normalize import normalize_unit, clean_text


def test_mwh_converts_to_kwh():
    qty, unit, note = normalize_unit(36.098, "MWh")
    assert qty == 36098          # 36.098 × 1000
    assert unit == "kWh"

def test_kilolitre_converts_to_litre():
    qty, unit, note = normalize_unit(1.49, "KL")
    assert qty == 1490           # 1.49 × 1000
    assert unit == "litre"

def test_kwh_stays_kwh():
    qty, unit, note = normalize_unit(500, "kWh")
    assert qty == 500
    assert unit == "kWh"

def test_unknown_unit_is_flagged_not_guessed():
    qty, unit, note = normalize_unit(1, "lot")
    assert note is not None       # must flag, not silently convert

def test_labels_are_lowercased():
    assert clean_text("Electricity") == "electricity"
    assert clean_text("  DIESEL ") == "diesel"