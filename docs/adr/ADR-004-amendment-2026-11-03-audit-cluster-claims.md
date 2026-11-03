# ADR-004 amendment 3 Nov 2026: post-run label audit, cluster sensitivity CI, claim scope

- **Amends:** ADR-004 §10 (metrics and stopping rules) and the paper-claim wording. ADR-004 and the spec are not edited, and `spec_sha256` is unchanged.
- **Accepted:** Shyam, 3 Nov 2026 (R06 evaluation picks DECIDE-1 (b), DECIDE-2 (c), DECIDE-3 (b)).
- **Evidence:** `efrecon/research/R06_gold_set_annotation_methods.md` and `R06_evaluation_2026-10-25.md`:
  - Northcutt et al. 2021 (test-label errors);
  - Miller 2024 (clustered standard errors);
  - Cameron, Gelbach & Miller 2008 (few-cluster inference is unreliable);
  - Recht et al. 2019; Geva et al. 2019.
- **Timing:** written before any TEST/VAL hash is frozen, so it counts as pre-registration.

## 1. Cluster sensitivity CI (secondary, never the headline)
- The headline CI for `determination_accuracy_gold_qty_unit_given__ABC_fixed` stays **Wilson 95%**.
- **Additional output:** `determination_accuracy_gold_qty_unit_given__ABC_fixed_cluster_ci95`. It is a percentile cluster bootstrap that resamples whole clusters with replacement, with B = 10000 and seed 20261103.
- **Clusters** = author × sub-type, over A+B+C rows only:
  - A rows: `expected_factor_id`;
  - B rows: `rule_id`;
  - C rows: `near_miss` (0/1).
- The output records the number of clusters and states: "sensitivity check; few clusters (CGM 2008) — not the headline".
- If the cluster CI and the Wilson CI differ materially (the cluster interval is more than 1.5× wider), the paper reports both and says so. Nothing else changes.

## 2. Symmetric post-run TEST label audit
Carried out **once, after the single final TEST run**:
1. **Disagreement set D:** every A+B+C row whose outcome is not `correct` (`needs_llm` included).
2. **Agreement sample S:** a seeded random sample of `correct` A+B+C rows, of size max(|D|, 20). If fewer correct rows exist, take all of them. Seed 20261103.
3. **Audit list:** D ∪ S, shuffled with the same seed. The auditor never learns which rows are in D and which are in S.
4. **Auditor:** each row is re-labelled blind by the **other** writer (A1 rows by A2, A2 rows by A1). The auditor sees only:
   - the frozen spec and factor list;
   - `raw_description`;
   - `canonical_qty`/`canonical_unit`.
   The auditor does not see the gold label or the engine output. They record `expected_decision` (and `expected_factor_id` for accepts) plus the spec rule.
5. **Correction rule:** a gold label is corrected only if the auditor's label differs from gold **and** the original writer agrees that gold was wrong. The original writer is shown the spec rule and both labels, without engine output.
6. **Reporting:**
   - **"As-labelled"** score: the headline, unchanged;
   - **"Audited"** score: secondary, Wilson;
   - the number of corrections in D and in S;
   - the full list of corrected line_ids with the spec rule cited.
   Corrections in S (labels that "helped" the engine) and in D are both applied.
7. Hashed TEST files are never edited. Corrections live in a separate `audit_corrections.csv` in the sealed folder, and its sha256 goes in a dated amendment written after the audit.

## 3. Claim scope (pre-registered wording)
- "The headline TEST result measures determination accuracy (gold qty/unit given) on **spec-written synthetic rows** written by two humans under a frozen spec; it makes no claim about real customer traffic."
- "The A2 slice (A+B+C rows written by the mentor, who did not build the rules) is the **writer-disjoint estimate**, reported with its n and Wilson CI."

## 4. Tools
- `gold_tools audit-sample <final_scorecard_json> --seed 20261103 --min 20`: prints counts and a shuffled line_id list only.
- `gold_tools audit-apply <final_scorecard_json> <corrections_csv>`: prints the as-labelled and audited k/n with Wilson CIs, plus correction counts in D and in S, and ids only.
- Both obey the no-row-text rule.
