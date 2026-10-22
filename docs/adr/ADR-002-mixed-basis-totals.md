# ADR-002 — Totals that mix gas/GWP bases: flag and split, never silently sum

- **Status:** ACCEPTED 22 Oct 2026 (Shyam, "ADR-002 ok", before P04a Part A was approved).
- **Context:** P04a (Block 0, the parts that need no download).
- **Change rule:** this file is never edited after ACCEPTED. Changes go in `ADR-002-amend-<date>.md`.

## Context
- Every factor row already stores `gas_basis` and `gwp_basis` [REPO, `data/emission_factors.csv` at e2fea7d]:
  - CEA grid rows are `CO2/CO2`, meaning CO₂-only;
  - DESNZ/DEFRA fuel rows are `CO2e/AR5`;
  - BEE CCTS (planned) will be `CO2e/AR2` [RESEARCH 09].
- **Locked decision:** never sum CO₂-only, AR5 and AR2 values without a disclosure flag. Scope 2 from CEA is reported as tCO₂, CO₂-only.
- **Today this rule is broken in four places.** Each sums every accepted line into one "kgCO₂e" number:
  - the API `/batch` (`total_kgco2e`, computed with **float**);
  - `compute.main()`;
  - `dedup.py`;
  - the dashboard headline (`app.py:120`).

## Decision
1. **One helper does all summing.** A new module `src/totals.py` provides `sum_by_basis(lines)`. It returns:
   - `total_kg`: Decimal, the plain sum (kept for backward compatibility);
   - `by_basis`: `{"CO2/CO2": Decimal, "CO2e/AR5": Decimal, …}`;
   - `basis_mixed`: bool;
   - `label`, which is:
     - `kgCO2 (CO2-only)` when every line is CO2/CO2;
     - `kgCO2e (AR5)` when every line is CO2e/AR5;
     - `kg — MIXED basis (CO2-only + CO2e AR5); not a single-GWP total` when the bases are mixed.
   - All arithmetic is Decimal (locked: "Decimal, not float").
2. **A line with a missing or unknown basis** is added under `UNKNOWN` and forces `basis_mixed = true`. It is never dropped.
3. **The API `/batch` stays backward compatible.** It keeps `total_kgco2e` and `total_tco2e` and adds `basis_mixed`, `totals_by_basis` and `total_label`. The README documents that `total_*` is a plain sum, and that when `basis_mixed` is true, the per-basis subtotals are the reportable figures.
4. **`compute.main`, `dedup` and the dashboard** print and show the per-basis subtotals and the mixed flag. When the bases are mixed, the headline no longer says "kgCO₂e" alone.
5. **Out of scope:** no conversion between bases. A CO₂-only factor can't be turned into CO₂e without CH₄/N₂O data that CEA does not publish.

## Options considered
- **A. Keep as is.** Rejected: it breaks a locked decision, and the dashboard shows a mislabelled total.
- **B. Refuse to sum mixed bases** (return no total). Rejected: it breaks API clients, and a plain sum is still useful when it is flagged.
- **C. Flag and split (chosen).** Backward compatible and honest. Reporters use the per-basis subtotals.
- **D. Convert everything to one basis.** Not possible without data CEA does not publish; it would invent numbers.

## Worst case and undo
- **Worst case:** a client ignores `basis_mixed` and reports `total_kgco2e` as CO₂e. Guard: the field is documented, and `total_label` says "MIXED".
- **Undo:** easy. These are additive response fields and one helper.

## Later blocks affected
- **P04b** (CEA v22 rows) keeps the CO2/CO2 basis on the CEA rows.
- **BEE AR2 rows** (later) will show up as a third basis automatically.
- **The paper:** totals are reported per basis.

## Research gate
None needed. The rule is a locked decision [RESEARCH 09: BEE uses AR2, DESNZ uses AR5, CEA is CO₂-only].
