# EF-Recon gold set v2: writing and labelling spec (public)

- **Status:** FROZEN with ADR-004 (accepted 23 Oct 2026). Text = draft v3 unchanged. Its hash is recorded in `docs/adr/ADR-004-amendment-2026-10-23-hashes.md` before any TEST/VAL row is written. Changes only through a dated ADR-004 amendment.
- **Readers:** both writers (A1, A2), the second labeller, and paper readers.

## 1. What this spec is for
TEST and VAL rows are written and labelled **from this spec only**, with no engine in the loop. A label is the answer a careful carbon accountant would give, under one of the rules in §5. Rows are written before anyone runs the engine on them.

## 2. Sets and strata
**TEST: 180 rows**
- **A: 90 accepts.** Electricity 30 · diesel 20 · petrol 10 · LPG in litres 10 · piped/natural gas in m³ 10 · CNG in kg 10.
- **B: 30 escalations.** Fuels with no factor; units that can't be converted without outside data (including gallons of unstated type); mixed-fuel spend.
- **C: 30 refusals.** Non-energy, non-combustion spend, with at least 10 near-misses.
- **D: 30 raw-text rows.** Quantity and unit appear only inside the text.

**VAL: 80 rows**, same mix (A 40 · B 13 · C 13 · D 14). Used only for agreement between labellers.

**Writers:** A1 writes two thirds and A2 one third of **each stratum**. TEST: A1 120, A2 60. VAL: A1 54, A2 26.

**Not used until Block 1:** gas or PNG priced in kWh; solar or rooftop power; coal; the grid "combined margin".

## 3. What a writer may and may not use
**Allowed**
- This spec.
- The factor list below.
- General knowledge of Indian bills and invoices.
- Field names from the public Forum of Regulators standard electricity bill (e.g. "Units Consumed", "KWH").

**Not allowed**
- DEV rows.
- The engine's code, aliases, keyword lists or any engine output.
- AI tools (Claude, ChatGPT, Copilot) for writing or labelling.
- Real customer bills, names or numbers.
- Anything from CarbonTatva.

All rows are **synthetic**. Use invented vendors and sites.

**Factor list (frozen, release efl-1)**

| factor_id | unit | use in TEST |
|---|---|---|
| EF-IN-ELEC-GRID | kWh | yes (electricity) |
| EF-DIESEL-L | litre | yes |
| EF-PETROL-L | litre | yes |
| EF-LPG-L | litre | yes |
| EF-NATGAS-M3 | m³ | yes (piped or natural gas by volume) |
| EF-CNG-KG | kg | yes |
| EF-NATGAS-KWH, EF-PNG-KWH | kWh | not used (Block 1) |
| EF-IN-ELEC-SOLAR | kWh | not used (Block 1) |
| EF-COAL-T | tonne | not used |
| EF-IN-ELEC-GRID-CM | kWh | never a correct answer for company reporting |

"Supported" means "in this list with a usable unit". It never means "the engine can match it".

## 4. Writing rules
- Write lines the way they appear on real Indian bills, invoices and ERP exports: abbreviations, header variants, MWh vs kWh, kilolitres, Hindi-English mixes, typos.
- **A, B and C rows** must have the quantity and unit in their own columns (`canonical_qty`, `canonical_unit`, `qty_source = column`).
- **D rows** put the quantity and unit only inside `raw_description` (`qty_source = text`). The canonical fields are still filled for scoring.
- **Dates:** if a row has a billing or invoice date, it must fall between 1 Apr 2025 and 31 Mar 2026. Undated rows are fine.
- No two rows may be the same after normalisation (§9). Vary vendors, sites, wording and numbers.
- Paste the canary GUID (given by Shyam) into the `canary` column of every row.

## 5. Label rules (pick exactly one `rule_id` per row)

| rule_id | Situation | expected_decision |
|---|---|---|
| R-ACC | Energy or fuel used, in a unit that matches a usable factor above (or converts by a fixed constant, e.g. MWh→kWh, kL→L) | accept, plus `expected_factor_id` and `expected_factor_row_id` |
| R-ESC-GAP | Energy or fuel used, but no usable factor in the list (e.g. furnace oil, pet coke, biomass, HFO) | escalate |
| R-ESC-UNIT | Energy or fuel in a unit that can't be converted without outside data (LPG in kg, CNG in m³, gallons of unstated type) | escalate |
| R-ESC-MIX | Spend that could be more than one fuel, and the line can't be split | escalate |
| R-REF | Not combustion or energy use: equipment rental, maintenance or AMC contracts, fuel transport and handling charges, taxes or surcharges shown as separate lines, energy audits or consultancy, stationery, services | refuse |

- **Gallons:** if the US vs imperial gallon is not stated, use R-ESC-UNIT, and the rationale must say "gallon type unstated".
- **`expected_factor_row_id`:**
  - Electricity uses `EF-IN-ELEC-GRID@v22.0@FY2025-26@incl_imports`.
  - Fuels use their single release row, e.g. `EF-DIESEL-L@DEFRA GHG conversion factors`.
- **`label_rationale`:** one sentence naming the accounting reason, never a keyword.
- **`expected_category`** (optional): one of classified, cannot_classify, context_dependent, source_ambiguous, guidance_ambiguous, unsupported. Fill it only if you are sure, and set `category_status = stated`; otherwise leave it blank with `category_status = blank`.

## 6. Near-misses (stratum C)
A near-miss is a line whose words overlap with an energy or fuel term, but whose accounting meaning is R-REF (e.g. renting equipment that uses fuel, servicing a generator, transporting fuel, a fuel-bill surcharge line). Judge it by meaning. Never check a draft against keyword lists. At least 10 of the 30 C rows (and 4 of the 13 VAL C rows) are near-misses.

## 7. Columns
`line_id` · `set` · `stratum` · `raw_description` · `source_file` · `period` · `expected_decision` · `expected_factor_id` · `expected_factor_row_id` · `canonical_qty` · `canonical_unit` · `qty_source` · `expected_category` · `category_status` · `rule_id` · `label_rationale` · `author` (A1 | A2) · `spec_sha256` · `canary`

## 8. Agreement and drift
- **VAL:** each row is labelled by its writer, then blind-labelled by the other writer. The second labeller sees only this spec, the factor list, `raw_description`, and the qty/unit columns for A, B and C rows. The statistics are listed in ADR-004 §7.
- **Drift:** at least 7 days after writing, each writer re-labels a random 20% of their own TEST rows (ids chosen by a seeded script), without looking at their first labels.

## 9. Overlap check (before sealing)
- **Normalisation:** lowercase, every digit → `#`, spaces collapsed.
- **Exact duplicates** (TEST, VAL and DEV v2 together): not allowed.
- **Near-duplicates:** character 3-gram Jaccard ≥ 0.80. Flagged rows are rewritten by their writer. This threshold is our own pre-registered choice; no published threshold exists for short lines.
- The check script prints counts and line_id pairs only.

## 10. After writing
- TEST labels are hashed (frozen) before VAL agreement is computed.
- Rows are never edited after hashing. Disagreements go to the adjudication log in the sealed folder.
- The files live only in the sealed folder, plus one encrypted backup.
