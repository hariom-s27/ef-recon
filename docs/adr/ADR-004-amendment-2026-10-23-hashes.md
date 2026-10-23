# ADR-004 amendment, 23 Oct 2026: acceptance hashes, one correction, six clarifications

- **Amends:** ADR-004 (accepted 23 Oct 2026). ADR-004 itself is not edited.
- **Written:** by Claude (working chat) on 23 Oct 2026. The P05a agent fills in §1 only (computed values) and changes nothing else.
- **Why now:** ADR-004 §4.1 says the spec and factor-list hashes are recorded at acceptance, before any TEST/VAL row is written.

## 1. Hashes at acceptance (filled in by P05a Part B)
"Hash of the committed content" means sha256 over the bytes of the git blob (`git cat-file -p <blob>`), which is LF-normalised. This is the same rule as scorecard schema 2 (KC #25).

| File | git blob | sha256 of blob content |
|---|---|---|
| `data/gold_spec_v2.md` | `b40f16eab6ddc03a89f9dcf8d4853f1960b585ad` | `76297c7ad1ccb20d710db99cf3955ba893372c7915b89c91b0192cc51c09c780` |
| `data/emission_factors.csv` (release efl-1) | `08e02b8fb8ee365c71c54858a1df77861259da67` (expected `08e02b8fb8ee365c71c54858a1df77861259da67`) | `75ac6b815d8e8c85c33214910e16d635f960540018e0ff4beb68b4af48f4cd73` (expected `75ac6b815d8e8c85c33214910e16d635f960540018e0ff4beb68b4af48f4cd73`) |
| `docs/adr/ADR-004-gold-set-v2-split.md` | `d3f00625efc3c70141614544352b2735d1ef0f85` | `d1a078e8d15401de7cc97a14c3dfd891b17b30744bf7f7a0113b26d09222b1ad` |

- Every TEST/VAL row's `spec_sha256` = the `data/gold_spec_v2.md` sha256 above.
- Recorded at base commit `ea7bd05`, before any TEST/VAL row exists.

## 2. Correction (KC #27): refusal in rules-only mode
- **ADR-004 §11 and its Consequences say** "refusal becomes measurable on DEV" once refusal rows are added.
- **That is wrong for the rules-only scorecard** [REPO, Claude's probe at `ea7bd05`]:
  - `run_scorecard.run_engine(..., allow_llm=False)` returns `needs_llm` whenever `canonical_activity(description)` is None, so a non-energy line can never reach the refuse branch.
  - In a probe of 7 refusal-type strings, none refused: 4 were `needs_llm`, 2 escalated ("DG set rental charges", "Energy audit consultancy fee") and 1 was **accepted** ("Diesel transportation charges" → diesel).
- **Corrected text for §11:**
  - The 12 new DEV refusal rows are measured, not predicted.
  - In rules-only mode most are expected to be `needs_llm` or wrong. They stay in DEV as Block 1 tripwires, for the terminal OTHERWISE → refuse row of the DMN cascade.
  - Refusal becomes measurable once Block 1 adds that row.
- **No other decision changes.**
  - The headline M1_TEST rule (`needs_llm` on A/B/C = wrong) stays.
  - The final TEST run happens at engine freeze. Its mode (rules-only or with LLM extraction) is fixed in the pre-run amendment.

## 3. Clarifications (no change of intent)
1. **DEV `author` values.**
   - `DEV-legacy`: the 44 retained rows plus PDF-0001.
   - `P05a-agent`: the 12 new refusal rows (proposed by the agent, approved by A1).
   - §6 said "DEV-legacy or A1". `P05a-agent` is more honest. TEST/VAL stay A1 | A2 only.
2. **No config constant for the sealed path.** The TEST/VAL path is a command-line argument only. The tripwire test therefore excludes **one** path (itself), which is stricter than §9's two.
3. **D rows are scored without** `canonical_qty`/`canonical_unit`, to mimic text-only input. A/B/C rows are scored with them, as DEV is today.
4. **Sealed filenames are fixed:** `gold_test_v2.csv`, `gold_val_v2.csv`, `adjudication_log.csv`, `drift_relabel.csv`, `val_second_labels.csv`. They live in the sealed folder only. `.gitignore` blocks `data/gold_test*`, `data/gold_val*` and `_sealed/`.
5. **DEV v2 strata** follow `expected_decision` (accept → A, escalate → B, refuse → C). Only rows whose quantity exists solely in text (PDF-0001) are D. Retained rows keep their canonical fields exactly as in `data/gold_labels.csv`, so their scoring is unchanged. DEV is exempt from the "A/B/C must have qty" rule. It applies to TEST/VAL.
6. **DEV `period`** is taken from the source CSV for each line_id where a date exists. Otherwise it is blank, which means the FY 2025-26 default row.
