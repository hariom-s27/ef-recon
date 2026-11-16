# AGENTS.md: standing rules for coding agents (EF-Recon)

Read this at the start of every session. Each task prompt repeats the safety rules in the same words.
If this file and the prompt's approved decision table disagree, STOP and ask.
This file is not frozen, but it changes only through an approved prompt.

## 1. Scope
- The owner decides, commits and pushes. You implement only what the prompt's approved decision table says.
- Anything else you think is needed: write it as a question in your report. Do not do it.
- Work only inside this repository folder. Reports and scratch files go in `_audit/<YYYY-MM-DD>_P##/` inside the repo (gitignored, never committed).
- Never list, open, create, edit or delete anything outside the repository: no parent-folder listings, no global installs, no edits to home-folder or tool settings.

## 2. Seal and secrets (hard rules)
- Never open, list or read the folders `_sealed` or `_scratch_not_test` (they sit next to this repo), or any `.env` file. If something you need is inside them, STOP and ask.
- Never print keys, tokens or any canary GUID.
- Never write, label, score or print TEST or VAL rows. `data/gold_test*` and `data/gold_val*` must never exist in the repo. The TEST gate (`--final --adr ADR-004`) runs only when a prompt for the final run says so.
- Never put TEST/VAL text, customer data or CarbonTatva data in code, tests, logs, reports or commit messages. Tests use invented fixtures.
- No network calls except package installs from `requirements-lock.txt`, and Ollama on localhost when a prompt allows it. No cloud LLM calls from code.

## 3. Frozen items (change only if the approved table names the change)
- `data/gold_spec_v2.md` and `data/gold_dev_v2.csv` (raw-byte hashes pinned by tests).
- Existing files in `docs/adr/`. A new ADR or amendment file may be added only when the table says so.
- `output/scorecards/*`: never overwrite; a new scorecard gets a new file name.
- Released rows in `data/emission_factors.csv`: changes are new versioned rows, never in-place edits.
- `.gitattributes` (LF line endings).
- Hash-pinning tests: `tests/test_line_endings.py`, `tests/test_gold_dev_v2.py`, `tests/test_scorecard_v2.py`, `tests/test_seal_tripwire.py`.
- Guard files: `AGENTS.md`, `CLAUDE.md`, `.claude/`, `.codex/`, `.githooks/`, `tests/test_agent_guards.py`.

## 4. When something blocks you
- If a guard, hook, test, sandbox, rule or permission blocks you: STOP and report exactly what was blocked.
- Never rephrase, retry another way, or work around it.

## 5. Git
- Never run git commands that change history, the index or branches: no add, commit, push, rebase, reset, clean, merge, stash, checkout or switch. Never delete files. These are human steps.
- At every STOP, give the owner ONE single-line command: `git commit -m "subject" -m "body"`, plus the exact `git add` line before it.
- No AI trailer or AI mention anywhere: no Co-authored-by, Assisted-by or "generated with" lines in commit messages, PR text, code comments or docs. Describing the product's own LLM field extraction is fine.
- Code is committed first, evaluations run after, outputs are committed last. Never evaluate uncommitted code.

## 6. Engineering rules
- Rules decide. An LLM may only extract fields (temperature 0, Pydantic schema, model tag and digest recorded). Embeddings may only suggest.
- Decimal for factor arithmetic, not float. Wilson CIs for proportions. Escalate, never guess. The last cascade row refuses; never fall back to a default factor.
- Every factor row keeps `gas_basis` and `gwp_basis`. Never add CO2-only, AR5 and AR2 values without the disclosure flag.
- Metric names are fixed (for example `determination_accuracy_gold_qty_unit_given__ABC_fixed`). Never call determination accuracy "end-to-end accuracy".
- Every bug fix comes with a test that fails on the old code. Keep all tests green.
- Compare files by git hash or raw-byte sha256, never by size on disk. Take counts and hashes from the current tree, never from memory.
- Edit files in place with your editor tools. Do not rewrite files through shell scripts.

## 7. How to run (Windows, Python 3.12)
- Python: `.venv312\Scripts\python.exe` (installed from `requirements-lock.txt`).
- Tests: `.venv312\Scripts\python.exe -m pytest -q -p no:cacheprovider`
- Lint (the CI rule set): `.venv312\Scripts\python.exe -m flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv*,_audit,data_raw`

## 8. Reports
- Write each task's report to `_audit/<YYYY-MM-DD>_P##/P##_report.md` inside the repo. Never stage or commit anything under `_audit/`.
- Start with a PLAIN SUMMARY (WHAT HAPPENED, WHAT IT MEANS, PROBLEMS including every deviation, DECISION NEEDED, NEXT MESSAGE). End with the 10-item SELF-AUDIT from the prompt.
- Every number names its source file or command. Test counts are copied from the test runner output.
