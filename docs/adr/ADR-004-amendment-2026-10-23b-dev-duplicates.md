# ADR-004 amendment 23 Oct 2026 (b): existing DEV near-template rows

- **Amends:** ADR-004 §8 and spec §9 (exact-duplicate rule), for DEV v2 only. ADR-004 and the spec are not edited.
- **Written:** Claude (working chat), 23 Oct 2026, after the P05a Part A stop. Approved by Shyam.

## Evidence [REPO, `data/gold_labels.csv` at ea7bd05; found by the P05a agent and re-checked by Claude]
Spec §9 normalisation (lowercase, digits → `#`, spaces collapsed) folds 7 retained DEV rows into 3 groups. They differ only in quantity:
- `diesel #### l`: DSL-0001 (2076 L), DSL-0003 (5089 L), DSL-0004 (5510 L)
- `hsd #### l`: DSL-0006 (7987 L), DSL-0007 (3495 L)
- `torrent power kwh=##### kwh`: ELEC-0007 (41930 kWh), ELEC-0009 (74010 kWh)

ELEC-0015 (a true duplicate of ELEC-0004 with qty 0) is already removed by ADR-004 §11.

## Decision
1. **Grandfathered.** These 3 groups (7 rows) stay in DEV v2 unchanged. Removing or rewording them would break the §11 pre-registered check, which requires per-row outcomes identical to 32aa5dd.
2. **No new DEV duplicate.** PDF-0001 and REF-0001…0012 must not normalise to the same string as each other or as any retained row.
3. **TEST/VAL are unchanged and strict.**
   - Zero exact duplicates within TEST, within VAL, across TEST and VAL, and against **every** DEV v2 row, the grandfathered ones included.
   - So a TEST/VAL line of the form "Diesel <n> L", "HSD <n> L" or "Torrent Power kWh=<n> kWh" is not allowed and must be reworded.
4. **Tests and tools.**
   - The DEV v2 test asserts the exact set of within-DEV duplicate groups equals the 3 groups above, no more and no fewer.
   - `gold_tools overlap` reports within-DEV groups separately from TEST/VAL hits, and never counts them as a TEST/VAL failure.
5. **Disclosure.** DEV v2 scorecards and the paper note that DEV holds 3 quantity-only template groups (7 rows), so DEV accuracy is partly on repeated templates. TEST has none by construction.

## Why
- The §9 exact-duplicate rule exists to stop TEST/VAL from leaking DEV wording and to stop repeated items inflating the scored set.
- Repeats inside DEV can't leak into TEST. They only make DEV (provisional, tuning-only) numbers a little less informative, and that is disclosed.
