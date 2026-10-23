# ADR-004 amendment 23 Oct 2026 (c): `near_miss` column is required in TEST/VAL

- **Amends:** spec §7 (columns) and ADR-004 §6 (schema). ADR-004 and the spec are not edited, and `spec_sha256` stays the hash of the frozen spec.
- **Written:** Claude (working chat), 23 Oct 2026, during review of P05a Part A. Approved by Shyam.

## Gap
- ADR-004 §10 requires near-miss refusal recall to be reported separately on TEST.
- Spec §6 requires at least 10 near-misses in TEST stratum C and at least 4 in VAL stratum C.
- But spec §7 has no column that marks a row as a near-miss. Without one, the minimum can't be checked by the validator, and the §10 metric can't be computed without guessing from keywords, which spec §6 forbids.

## Decision
1. TEST and VAL rows carry a **20th column, `near_miss`**, after `canary`.
   - Values: `1` for a stratum-C row that the writer judged a near-miss under spec §6 (by accounting meaning).
   - `0` for every other row, including all A, B and D rows.
2. The writer sets it **when writing the row**, before any hashing, and it is part of the frozen label.
3. `gold_tools validate` requires the column for TEST/VAL and enforces two things:
   - `near_miss = 1` only on C rows;
   - the minimum counts: TEST C ≥ 10, VAL C ≥ 4.
4. DEV v2 already carries `near_miss` (P05a plan), in its 22-column DEV order.
5. VAL agreement stays on `expected_decision` (ADR-004 §7). Agreement on the `near_miss` flag is not measured.

## Why
- This is the cheapest way to make §6 and §10 measurable without keyword inference. It is decided before any TEST/VAL row exists, so there is no leakage or tuning effect.
