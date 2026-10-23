# ADR-004: Gold set v2 (DEV v2, sealed TEST, VAL agreement set) and the sealing protocol

- **Status:** ACCEPTED, 23 Oct 2026 (Shyam: "i agree with all"; text = PROPOSED v3 unchanged). This file is never edited; changes go in `ADR-004-amendment-<YYYY-MM-DD>-<topic>.md`.
- **Supersedes:** the drafts ADR-004 v1 and v2 (proposed, never accepted).
- **Inputs:**
  - plans P05 v2–v5;
  - reviews in efrecon/reviews/ (23 Oct);
  - research 02 (sizes, Wilson), 03 (agreement), R04 (holdout and leakage, plus its evaluation);
  - ADR-001 (DEV scorecard protocol), ADR-003 (factor release efl-1).

## Context
- `data/gold_labels.csv` (45 rows) is all DEV (ADR-001). It feeds the frozen scorecards 6ddea50, 0b958f8 and 32aa5dd.
- Rules-only DEV at 32aa5dd [REPO]:
  - M1 = 37/38 [86.5–99.5];
  - M2 = 37/45 [68.7–90.7];
  - refusal 0/0, not measured (the two NO_FACTOR rows need the LLM).
- `run_scorecard.py` at ea7bd05 [REPO]:
  - `is_correct` compares at **factor_id**;
  - M1 = correct ÷ decided rows (drops `needs_llm`);
  - M2 = correct ÷ all rows.
- The engine refuses only when the activity is unknown or the unit is missing, AND no hint word (fuel / energy / consumption / utility) appears (`extract.py`, `match.py`) [REPO].
- R04 [RESEARCH]:
  - test writers should be disjoint from the writers whose phrasing the system was fitted to (Geva 2019, P);
  - write with no model in the loop (Gardner 2020, P);
  - Krippendorff α with a bootstrap CI (Zapf 2016, P);
  - AC1 is not a κ substitute (Vach & Gerke 2023, P);
  - near-duplicates inflate scores (Lewis 2021, P);
  - no published near-dup threshold for short strings;
  - no venue rule to commit a hash.

## Decision

### 1. Sets and sizes
| Set | Rows | Written by | Purpose | Committed? |
|---|---|---|---|---|
| DEV v2 | 45 − 1 (ELEC-0015 to the dedup check) + 1 (PDF-0001) + 12 new refusal rows = **57** | existing rows + 12 refusal rows proposed by the P05a agent and approved by Shyam | tuning, provisional scorecards | yes, as `data/gold_dev_v2.csv`. `data/gold_labels.csv` stays unchanged (the frozen scorecards hash it) |
| TEST | **180** | writer A1 (Shyam) 120, writer A2 (mentor) 60, i.e. one third of every stratum | the single final run | **no**: sealed folder; only hashes in the manifest |
| VAL | **80**, mirroring the TEST stratum mix (A 40 · B 13 · C 13 · D 14) | A1 54, A2 26 | inter-rater agreement only; never scored by the engine, never used for tuning | **no**: sealed folder |

Writer codes A1 and A2 appear in public files. Names never do.

### 2. TEST strata (per spec §2)
| Stratum | Rows | Content | In headline M1 |
|---|---|---|---|
| A | 90 | Accepts: electricity 30 · diesel 20 · petrol 10 · LPG litre 10 · piped/natural gas m³ 10 · CNG kg 10 | yes |
| B | 30 | Escalations: fuels with no factor, units not convertible without outside data (incl. gallons of unstated type), mixed-fuel spend | yes |
| C | 30 | Refusals: non-energy, non-combustion spend; **≥ 10 near-misses** | yes |
| D | 30 | Raw-text rows: qty and unit only in the text | no (Block 2 end-to-end) |

- Each writer covers each stratum in proportion (A2: A 30 · B 10 · C 10 · D 10).
- **Excluded until Block 1:** natural gas or PNG priced in kWh (KC #19, HARD-0007); solar (KC #19); coal (TO_CONFIRM); the combined margin (special use).

### 3. One spec, hashed first
- There is ONE spec: `data/gold_spec_v2.md` (public). It covers strata, label rules, labeller access, schema, period rule, near-miss *types*, and the overlap and drift checks.
- There is no sealed spec part. The sealed content is just the TEST and VAL CSVs.
- `spec_sha256` on every row = the git-blob/sha256 of `data/gold_spec_v2.md` at acceptance.

### 4. Hash timing (two moments)
1. **At acceptance:** the sha256 of `data/gold_spec_v2.md` and of the efl-1 factor-list file are recorded in a short `ADR-004-amendment-<date>-hashes.md`. That file is written by the P05a agent, because the spec file is created in the repo there. No row is written before this.
2. **At sealing:**
   - `data/gold_manifest.json` records the sha256 of TEST, VAL and the 7-Zip backup, plus row counts per set, stratum and writer, the canary GUID, the seed for drift sampling, and the creation date.
   - It is committed, and its sha256 is emailed to the mentor as an outside, timestamped witness.

### 5. Writers and labeller access (both writers)
- **Allowed:** the public spec; the frozen efl-1 **factor_id list with each factor's unit**.
- **Forbidden:** DEV rows, aliases, `ACTIVITY_KEYWORDS`, `AMBIGUOUS_HINTS`, `UNSUPPORTED_FUELS`, normalize tables, any engine run or output, and Claude/agents (no AI help in writing or labelling TEST/VAL rows).
- Rows are synthetic, written from the spec.
  - No real customer text, names or numbers.
  - No CarbonTatva data. This applies to A2 too.
  - Bill field names may follow the public Forum of Regulators standard bill (field names only).
- Each row's label comes from the spec rule chosen by its accounting meaning, before any engine output exists.

### 6. Schema (TEST and VAL)
`line_id` (T-0001… / V-0001…), `set`, `stratum`, `raw_description`, `source_file` (synthetic file name), `period` (or blank), `expected_decision` (accept | escalate | refuse), `expected_factor_id` (accept only), `expected_factor_row_id` (accept only), `canonical_qty`, `canonical_unit`, `qty_source` (column | text), `expected_category` (optional), `category_status` (stated | blank), `rule_id`, `label_rationale`, `author` (A1 | A2), `spec_sha256`, `canary`.

- A, B and C rows: `qty_source = column`; `canonical_qty` and `canonical_unit` are required.
- D rows: `qty_source = text`.
- Period rule: dated TEST/VAL rows fall in **FY 2025-26** (1 Apr 2025 – 31 Mar 2026); undated rows take the FY 2025-26 default row (ADR-003).
- Gallons of unstated type → escalate, `R-ESC-UNIT`; the rationale must say "gallon type unstated".

DEV v2 uses the same columns (`set = DEV`, `author` = DEV-legacy or A1). The mapping from the old labels is factor_id → accept (+ row ID), ESCALATE → escalate, NO_FACTOR → refuse. A test asserts that the mapping is one-to-one.

DEV period truth: the 3 DEV electricity rows billed Jan–Mar 2025 (ELEC-0003, -0007, -0013 [REPO]) get the FY 2024-25 v22 row as `expected_factor_row_id`. This is the truth by period. M1 is unaffected (factor-level). It becomes a Block 1 tripwire.

### 7. Agreement (VAL)
- Every VAL row gets two labels: its writer's, and the other writer's blind label (cross-labelling).
- The second labeller sees only the public spec, the factor_id list and `raw_description`, plus qty/unit for A/B/C.
- **Reported:**
  - **primary**: Krippendorff α (nominal, on `expected_decision`), bootstrap 95% CI, B = 10,000, seed recorded;
  - raw agreement (Wilson CI);
  - per-class agreement;
  - Cohen's κ and Gwet AC1, shown **without** verbal bands on AC1;
  - the full 3×3 confusion table.
- At n = 80 the CI may still be wide, and it is reported as such.
- The factor-level label is compared on accept-accept pairs, with k/n reported.
- TEST labels are frozen (hashed) **before** agreement is computed.
- Disagreements go to `adjudication_log` (sealed folder; counts in the manifest).
- A spec change after that goes in a dated amendment, and touches only rows not yet hashed. Hashed rows are never edited.
- The word "κ" may appear in outputs only after this agreement is persisted in an amendment (KC #4).

### 8. Overlap and drift checks (before sealing)
- **Near-duplicates:** TEST and VAL vs DEV v2, and within TEST and VAL.
  - Normalisation: lowercase, digits → `#`, whitespace collapsed.
  - (a) Normalised exact duplicates: **0 allowed**.
  - (b) Character 3-gram Jaccard **≥ 0.80**: flagged, and the writer rewrites before sealing. 0.80 is **our pre-registered choice**; no published threshold exists for short lines (R04).
  - The script prints only counts and line_id pairs, never row text.
- **Drift:** each writer re-labels a seeded random 20% of their own TEST rows (A1 24, A2 12) at least 7 days after writing. They are blind to the first labels and see no engine output.
  - Report agreement with self (raw + α).
  - Disagreements are resolved by the spec rule and logged.

### 9. Seal
- TEST, VAL and logs live in `D:\sem_iitk\summer_3\intern_report\_sealed\ef-recon\` (outside the repo and `_audit`). Claude and agents never open it.
- **Canary:** one GUID, generated by Shyam, in the `canary` column of every TEST/VAL row and in the manifest. Before the final run, logs, `runs/`, `_audit/` and the Project are grepped for it; any hit is reported.
- **Backup:** 7-Zip AES-256. The password lives in a password manager, never in the repo, Project, chat or screenshots. The backup sha256 goes in the manifest.
- **Runner:** refuses TEST unless `--final --adr ADR-004` is given and the file's sha256 equals the manifest. The TEST path is a command-line argument, read only in the `--final` branch.
- **Tripwire test:** fails if any file under `src/` or `tests/` contains the sealed folder name `_sealed` or the TEST/VAL filenames. Two paths are excluded by name: the runner's single config constant file, and the tripwire test itself.
- Helper scripts run by Shyam (validation, overlap, drift sampling, agreement) take the path as an argument and print only counts, ids and statistics.
- **Honest limit (for the paper):** the seal is procedural plus code checks, not cryptography. Anyone with disk access can read the files.

### 10. Metrics and stopping rules (pre-registered for the single final TEST run)
- **M1_TEST (headline):** determination accuracy (gold qty/unit given), over A+B+C, denominator fixed at the actual A+B+C count (150 unless short).
  - A `needs_llm` on an A/B/C row = wrong, and is also counted as a spec violation.
  - Wilson 95% CI.
- **M1_decided (secondary):** decided rows only (DEV-style). Labelled "not comparable to DEV M1 without this note".
- **coverage_ABC:** decided ÷ A+B+C (Wilson).
- **D-count:** D rows reaching `needs_llm`. Reported; not in M1.
- **Escalation recall** and **refusal recall** (Wilson; one-sided Clopper–Pearson when 0 misses), plus the escalate/refuse/accept confusion table. Near-miss refusal recall is reported separately.
- **Per-writer M1** (A1 vs A2, Wilson each). This measures author effect, not claims it.
- **Per-stratum and per-rule_id slices:** k/n + Wilson; slices with n < 10 are merged.
- **Weighted metrics:** rows whose factor is TO_CONFIRM are excluded from or flagged in any kg/tCO₂e-weighted metric. Expected kg is computed at scoring time from `expected_factor_row_id` (Decimal), with the release recorded.
- **Shortfall:** report it; never top up after sealing.
- **No tuning:** if the M1_TEST Wilson lower bound is < 0.90, the paper says it is below that bar. No rule change after sealing; any change means a new TEST, and the paper says so.
- No expected accuracy number is stated in this ADR.
- **When:** the final run happens once, when the engine is frozen for the paper. Its exact engine commit is recorded in an amendment just before the run.

### 11. DEV v2 and its pre-registered scorecard (P05a)
- **Changes:**
  - restore PDF-0001 as a raw-text row (FY 2025-26; PDF sha256 `3760aebe…2c276e4a`, verified on Shyam's machine);
  - move ELEC-0015 to a dedup check;
  - replace `expected_kgco2e` with `expected_factor_row_id` (old values kept in `data/gold_labels.csv`, unchanged);
  - add 12 refusal rows (≥ 4 near-miss types per the spec);
  - map labels.
- **Expected (pre-registered):**
  - on the 44 retained original rows, per-row outcomes are identical to `scorecard-2026-10-22-32aa5dd.json`;
  - PDF-0001 = `needs_llm`;
  - the 12 new rows are measured, not predicted; refusal becomes measurable on DEV.
  - Any difference on retained rows → STOP and explain.
- The new DEV scorecard is a new dated file. The frozen scorecards stay.

### 12. Cost and calendar [INFERENCE]
- A1: about 2.5 days (120 TEST + 54 VAL rows, labels, rationales, plus cross-labelling 26 and a drift re-label of 24).
- A2: about 1.5–2 days (60 TEST + 26 VAL, plus cross-labelling 54 and a drift re-label of 12).
- Calendar: about 2 weeks from acceptance to sealing; no deadline set.
- No money; no cloud LLM.

### 13. Hard-undo actions (each needs a backup, a dry run with counts, Shyam's yes, and a hash check)
- Creating TEST/VAL.
- Writing and committing the manifest.
- Committing anything derived from TEST/VAL beyond hashes and counts.
- Unsealing TEST.
- Releasing TEST/VAL publicly.
- Re-freezing after sealing (only through an amendment).

## Alternatives considered (rejected)
- 84 rows.
- Single writer only (A1), rejected on R04/Geva grounds.
- Mentor labels TEST rows (would break the seal).
- 36-row VAL (too small for any α rule of thumb).
- κ/AC1 as the headline (contested).
- Embedding-based near-dup check (adds a model).
- Pre-registering gas-kWh as known misses.
- Typed kg values.
- TEST in the repo or `data_raw/`.
- A sealed spec part (circular).
- M2 on TEST (capped at 83.3% by design).

## Consequences
- The headline rests on 150 rows written by two writers, with author effect measured.
- Refusal becomes measurable on DEV and TEST.
- Block 2 gets a sealed end-to-end set (D).
- Block 1 inherits: period selection (DEV FY 2024-25 rows), gas-kWh, solar, coal, and categories for rows with `category_status = blank`.
- Next free ADR number after acceptance: **ADR-005**.
