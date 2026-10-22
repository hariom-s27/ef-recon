# ADR-003 — Factor library release 1: versioned CEA rows (v21 + v22) and how one row is chosen

- **Status:** ACCEPTED 23 Oct 2026 (Shyam, "ADR-003 ok", before P04b Part A was approved).
- **Context:** P04b (Block 0).
- **Change rule:** this file is never edited after ACCEPTED. Changes go in `ADR-003-amend-<date>.md`.

## Context
- `data/emission_factors.csv` (at 8ed946c) has **one row per factor_id**. The CEA rows hold `0.7117` (EF-IN-ELEC-GRID) and `0.7383` (EF-IN-ELEC-GRID-CM), both labelled "CEA v21.0, FY2024-25". There are no validity dates, no variant, and no page/cell citation.
- **The CEA v22.0 database (Aug 2026), read at full precision** [PRIMARY; research R03, Results sheet]:
  - FY 2025-26: 0.6750986831448641 incl. imports (AA14); 0.6780328931474631 excl. imports (O14).
  - FY 2024-25, restated: 0.7101023036210137 incl. (Z14); 0.7121402774099946 excl. (N14).
  - Combined margin: AA17 / O17 / Z17 / N17.
- **Locked decisions:**
  - factor changes are new versioned rows (valid_from/valid_to, known_from), never edits in place;
  - CEA is CO₂-only;
  - CEA's headline is the incl.-imports variant (KC #3);
  - a value that isn't confirmed is TO_CONFIRM and is never used in measured results.
- **Sources** (KC #26): v21 guide `…/view-pdf/en/78`; v22 guide `…/en/82`; v22 Excel `…/en/83`.
- **The matcher** (`match_line` → `exact_match`) expects **one candidate row per factor_id**. More rows with the same id would create ties.

## Decision
1. **New columns** (appended; existing columns unchanged):
   - `row_id` (unique);
   - `variant` (`incl_imports` | `excl_imports` | `n/a`);
   - `is_default` (1/0);
   - `valid_from`, `valid_to` (ISO dates; the FY is 1 Apr – 31 Mar);
   - `known_from`, `known_to` (publication month; `known_to` is blank while current);
   - `source_version`, `source_url`, `source_locator` (Excel cell or PDF table + page);
   - `value_status` (`PRIMARY` | `TO_CONFIRM`).
2. **CEA rows added** (factor_id unchanged; all `CO2/CO2`; `value_status=PRIMARY`):
   - EF-IN-ELEC-GRID, FY 2025-26: incl. (default) and excl.
   - EF-IN-ELEC-GRID, FY 2024-25 restated by v22: incl. (default) and excl.
   - The same 4 rows for EF-IN-ELEC-GRID-CM (it stays SPECIAL_USE, never auto-applied).
   - Values are stored exactly as read from the v22 Excel cells. **No rounding.**
3. **The existing v21 rows are kept, not edited.**
   - Their value stays as it is.
   - The new columns are filled: `known_from=2025-11`, `known_to=2026-08` (superseded by v22's restatement), `source_url=…/en/78`.
   - `variant` and `source_locator` are **confirmed from the v21 guide** (table + page) in P04b Part A. If the guide does not show 0.7117 or 0.7383 explicitly, the row keeps `value_status=TO_CONFIRM`.
4. **Which row the engine uses (release 1, deliberately simple).** The loader returns **exactly one row per factor_id**:
   - the `is_default=1` row
   - whose validity contains the configured **`REPORTING_FY`**,
   - with `known_to` blank (current knowledge).

   `REPORTING_FY` lives in `config.py` and defaults to **2025-26**, the latest FY CEA has published. `match_line` receives the same shape as today, so **decision logic is not changed**.
5. **`value_status` travels with each result.** The API, compute and dashboard expose it. The DEFRA/IPCC fuel rows get `TO_CONFIRM` (the DESNZ flat files are still pending, research 04), so their emissions are visibly flagged, not silently trusted.
6. **Not in this release** (Block 1):
   - choosing the row by each bill's own period;
   - the determination record;
   - the NATGAS gross/net CV label (needs the DESNZ flat file; its note becomes "CV basis TO_CONFIRM").
7. **Notes cleaned before the first release:** the CEA `verify_before_audit` text "use regional grid factor…" is removed (locked: no regional CEA factor). This is allowed only because the library has never been released. From this ADR on, the library is **release `efl-1`** and released rows are never edited.
8. **Expected scorecard (pre-registered):**
   - `factor_id` choices do not change, so M1, M2, the components, per_row and needs_llm_ids are **identical to 0b958f8**.
   - Only emission values change; electricity uses 0.6750986831448641 instead of 0.7117.
   - Any metric difference → STOP and explain.

## Options considered
- **Selection rule:**
  - **A. REPORTING_FY default (chosen).** Simple, matches today's one-row shape, and is documented.
  - **B. Escalate every line without a period.** Rejected: almost every line would escalate, because gold and API inputs rarely carry periods.
  - **C. Choose by bill period now.** Correct long-term, but it changes the decision path; that's Block 1.
- **Default FY:**
  - **2025-26 (chosen):** the latest published.
  - 2024-25: would match the BRSR filing year in README §7, but it is older.
- **Variant:**
  - **incl. imports (chosen):** CEA's headline (KC #3).
  - excl. imports: kept as the alternative row.

## Worst case and undo
- **Worst case:** a bill from FY 2024-25 is computed with the FY 2025-26 factor (0.6751 instead of 0.7101, about 5% low). Guard: `REPORTING_FY` and the row's `valid_from/valid_to` appear in each result's trace, and README states the limitation. Block 1 fixes it.
- **Undo:** easy. New rows plus a config value, and the v21 rows are untouched.

## Later blocks affected
- **Block 1** adds per-period selection and the determination record (row_id).
- **The gold `expected_kgco2e` column** was computed at 0.7117. It is not used by the scorecard; P04b Part A checks whether anything else uses it.
- **README §7 (BRSR, FY 2024-25)** still uses the 0.7117 constant inside `brsr_ingest.py`. That moves to library lookup in Block 3.

## Research gate
None open.
- Values: R03 (Excel), with the v21 guide checked in Part A.
- Variant default: KC #3 / research 04.
- No regional factor: KC #1.
