"""
totals.py — ADR-002: the ONE place emissions are summed.
Never silently mixes CO2-only (CEA) with CO2e AR5 (DESNZ): totals are split per
gas/GWP basis, and a mixed total is flagged and labelled as such. Decimal only.
"""

from decimal import Decimal

from paths import DATA_DIR
from factor_library import read_active

UNKNOWN = "UNKNOWN"


def factor_bases(csv_path=None):
    """{factor_id: (gas_basis, gwp_basis)} for the same active rows as the matcher."""
    if csv_path is None:
        csv_path = DATA_DIR / "emission_factors.csv"
    return {row["factor_id"]: ((row.get("gas_basis") or "").strip(),
                               (row.get("gwp_basis") or "").strip())
            for row in read_active(csv_path)}


def basis_key(gas, gwp):
    """'CO2/CO2', 'CO2e/AR5', ... ; a missing half -> UNKNOWN."""
    gas, gwp = (gas or "").strip(), (gwp or "").strip()
    if not gas or not gwp:
        return UNKNOWN
    return f"{gas}/{gwp}"


def _describe(key):
    """How one basis is named inside a MIXED label."""
    if key == "CO2/CO2":
        return "CO2-only"
    if key == UNKNOWN:
        return UNKNOWN
    return key.replace("/", " ")          # 'CO2e/AR5' -> 'CO2e AR5'


def _label(keys, mixed):
    if not keys:
        return "kg (no lines)"
    if mixed:
        named = " + ".join(_describe(k) for k in keys)
        return f"kg — MIXED basis ({named}); not a single-GWP total"
    key = keys[0]
    if key == "CO2/CO2":
        return "kgCO2 (CO2-only)"
    gas, gwp = key.split("/", 1)
    return f"kg{gas} ({gwp})"             # 'CO2e/AR5' -> 'kgCO2e (AR5)'


def sum_by_basis(lines):
    """lines: mappings with emissions_kg, gas_basis, gwp_basis.
    Returns {total_kg, by_basis, basis_mixed, label} (ADR-002). Lines are never dropped."""
    total = Decimal("0")
    by_basis = {}
    for line in lines:
        kg = Decimal(str(line["emissions_kg"]))      # str() first -> no binary float error
        key = basis_key(line.get("gas_basis"), line.get("gwp_basis"))
        by_basis[key] = by_basis.get(key, Decimal("0")) + kg
        total += kg

    keys = sorted(k for k in by_basis if k != UNKNOWN) + ([UNKNOWN] if UNKNOWN in by_basis else [])
    mixed = len(keys) > 1 or UNKNOWN in by_basis
    return {
        "total_kg": total,
        "by_basis": {k: by_basis[k] for k in keys},
        "basis_mixed": mixed,
        "label": _label(keys, mixed),
    }


def unit_label(gas, gwp):
    """Per-line unit from the factor's basis: 'kgCO₂' (CO2-only), 'kgCO₂e (AR5)', ..."""
    key = basis_key(gas, gwp)
    if key == UNKNOWN:
        return "kg (basis UNKNOWN)"
    if key == "CO2/CO2":
        return "kgCO₂"
    gas, gwp = key.split("/", 1)
    return f"kg{gas.replace('CO2', 'CO₂')} ({gwp})"


def report_lines(totals):
    """Printable summary for the scripts: per-basis subtotals, the label, the mixed flag."""
    out = [f"  {key:10} {kg} kg" for key, kg in totals["by_basis"].items()]
    out.append(f"  label: {totals['label']}")
    out.append(f"  basis_mixed: {totals['basis_mixed']}")
    return out
