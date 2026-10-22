# ADR-001 — Block 0 provisional scorecard: protocol and gold-set status

- **Status:** ACCEPTED 22 Oct 2026 (Shyam, in the P03 start note "ADR-001 (scorecard protocol) accepted"), before P03 Part B ran at commit 6ddea50.
- **Context:** P03 truth-up. This is the first scorecard ever committed to the repo.
- **Change rule:** this file is never edited after ACCEPTED. Changes go in `ADR-001-amend-<date>.md`.

## Context
- **The README numbers can't be traced.** They are hand-typed and come from an older code path (~86% judge, ~97% gold, 1/8 → 8/8). The internship headline (100%, n=34) is determination accuracy on clean input (KNOWN_CORRECTIONS #5).
- **Ollama is not installed**, so the judge and LLM extraction can't run.
  - P00/P01 measured a rules-only mode (LOCAL, provisional) at 37/38 decisions correct, P@1 30/31, escalation 7/7, with 7 rows needing the LLM.
- **No dev/test split exists yet.** All 45 gold rows have been read and used for tuning since July (internship, P00, P01).

## Decision
1. **Mode:** rules-only.
   - No LLM extraction and no judge.
   - Gold `canonical_qty`/`canonical_unit` are given (the same input as today's harness).
   - If `canonical_activity(description)` can't resolve a row, the row is recorded as `needs_llm` and **is not scored by the rules**.
2. **Metrics,** each reported as k, n, p and a two-sided 95% Wilson CI (statsmodels `proportion_confint(method="wilson")`):
   - **M1 "Determination accuracy (gold qty/unit given), rule-resolvable rows":** correct / rows the rules decided.
     - A decision is correct when an accept picks gold `correct_factor_id`, when the engine escalates a gold `ESCALATE` row, and when it refuses a gold `NO_FACTOR` (or blank) row.
   - **M2 "Determination accuracy (gold qty/unit given), all rows":** the same numerator, over all 45 rows. `needs_llm` rows count as **not determined**, so this is a lower bound.
   - **Components** (k/n plus CI): P@1 on accepted should-match rows; coverage (accepted / should-match); escalation accuracy; refusal accuracy.
   - **Reported but not a metric:** the `needs_llm` count and their line_ids.
   - **Never reported side by side** with judge numbers or end-to-end numbers.
3. **Headline:** M1 and M2 are always shown together. Neither is shown alone.
4. **Gold-set status:**
   - All 45 current gold rows are declared **DEV (already seen)**. No current row may ever join the sealed TEST set.
   - TEST will be built from **new, unseen rows** before Block 2, with its size from 02_evaluation_methodology.md (n ≥ 84 for a lower bound above 0.90).
5. **Label:** "post-internship (2026-10-22, <commit>) · provisional · DEV-only (pre-split)". This is not a paper or resume number until Block 2.
6. **Reproducibility.** The scorecard JSON records:
   - commit sha (clean tree required);
   - Python version;
   - sha256 of `data/gold_labels.csv`, `data/emission_factors.csv` and `requirements-lock.txt`;
   - mode;
   - a per-row table.

   The run is done **twice**, and the per-row results and metrics must be identical; otherwise it is reported as unstable. The committed file is `output/scorecards/scorecard-<YYYY-MM-DD>-<shortsha>.json`, which is never overwritten.
7. **Expected result** (pre-registered from P00/P01, LOCAL): M1 = 37/38, P@1 = 30/31, escalation 7/7, needs_llm = 7.
   - Any difference → STOP and explain the cause (this check runs before anything is published).
   - **Never tune** anything to match.

## Options considered
- **A. Keep the README numbers as they are.** Rejected: they are untraceable and mix metrics.
- **B. Rules-only scorecard with M1 + M2 (chosen).** Deterministic, runs without Ollama, honest about LLM-dependent rows.
- **C. Wait for the LLM backend (Block 2) before committing any scorecard.** Rejected: the README keeps untraceable numbers for weeks.
- **D. Count `needs_llm` rows as wrong in a single metric.** Folded into M2, which is shown next to M1, so nothing is hidden.

## Worst case and undo
- **Worst case:** someone quotes M1 (37/38) as end-to-end accuracy. Guard: M1 and M2 always appear together, under fixed names, with the label "provisional · DEV-only".
- **Undo:** easy. The scorecard is a new file, and a later scorecard supersedes it. The file itself is never edited.

## Later blocks affected
- **Block 1** changes the results on purpose (tie fixes, aliases), so a new dated scorecard follows.
- **Before Block 2:** about 84+ NEW gold rows are needed for TEST. This is a real time cost.
- **Block 2:** the end-to-end metric gets its own ADR.

## Research gate
None needed. The Wilson CI is a locked decision, and the TEST-size rule is already in 02_evaluation_methodology.md.
