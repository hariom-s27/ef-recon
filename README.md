# EF-Recon — Emission-Factor Reconciliation & Reliability Engine

Turn messy utility and fuel bills into **audit-ready carbon numbers** — with full source-to-factor traceability, typed escalate/refuse decisions instead of guesses, and a reliability harness that *measures* how accurate the mapping is.

Built for Indian reporting (BRSR / CCTS): CEA grid factor for Scope 2, DESNZ/DEFRA factors for fuels. Aimed at the real bottleneck in carbon accounting: **reconciliation, not reporting.**

---

## 1. The problem

Companies must report emissions (BRSR, CCTS, CBAM), but their data is scattered across utility bills, fuel invoices, and ERP exports — in inconsistent units, headers, and formats. The hardest, most error-prone step is **matching each line to the correct emission factor and proving that number to an auditor.**

## 2. What EF-Recon does

Upload a messy bill → the engine:

1. **Ingests** CSV / PDF bills, attaching a source pointer to every row.
2. **Extracts** activity, quantity, unit, period (rules first, local LLM for free text).
3. **Normalizes** units (MWh→kWh, KL→litre, GJ→kWh) and activity aliases to a canonical form.
4. **Matches** each line to the correct emission factor under a strict, honest policy.
5. **Computes** emissions with exact math and a full audit trail.
6. **Deduplicates** repeated bills so totals aren't double-counted.
7. **Measures itself** — determination accuracy with Wilson confidence intervals, escalation/refusal accuracy. An LLM-as-judge exists for unlabeled data but is not yet validated against human labels.
8. **Escalates** uncertain lines to a review queue — never silently guesses.

## 3. Architecture

```
Bills (CSV/PDF)
→ Ingest → Extract → Normalize → Match (activity-first policy) → Dedup
→ Compute (with lineage) → Reliability harness (rules-only scorecard + Wilson CI)
→ Dashboard (Streamlit) + API (FastAPI)
```

## 4. Key design decisions (and why)

| Decision | Why |
|---|---|
| **Rules first, LLM only for genuine free text** | Deterministic domain rules are more accurate *and* faster than an LLM for known patterns. (See §6 — the core lesson.) |
| **Activity-first matching policy** | Two factors can share a unit (electricity and gas both use kWh). Matching on unit alone force-matches the wrong factor; activity must decide first. |
| **Allow-list of known activities/units** | The engine escalates fuels it has no factor for (furnace oil, pet coke) instead of guessing. In the EF-matching works we surveyed, none reports typed refusals, confidence intervals, or a miss rate on declined items; EF-Recon aims to measure all three (nearest precedents: EFMatch-LLM, GLAD). |
| **Different-family LLM judge (llama vs qwen extractor)** | A model judging its own family over-rewards itself (self-preference bias); a separate family reduces that bias (agreement with human labels not yet measured). |
| **Wilson confidence interval, always reported** | Honest small-sample uncertainty. A wide CI stated is stronger than a fake-precise point estimate. |
| **Special-use factors excluded from auto-match** | The Combined Margin factor is CDM-only; the engine never auto-applies it to corporate Scope 2. |

## 5. Results (provisional)

**post-internship (2026-10-22, 6ddea50) · provisional · DEV-only (pre-split)** — source: [`output/scorecards/scorecard-2026-10-22-6ddea50.json`](output/scorecards/scorecard-2026-10-22-6ddea50.json) (rules-only, no LLM, no judge; protocol ADR-001).

Protocol: [docs/adr/ADR-001](docs/adr/ADR-001-block0-provisional-scorecard.md) (+ [amendment](docs/adr/ADR-001-amend-2026-10-22.md)).

| Metric | k/n | p | 95% Wilson CI |
|---|---|---|---|
| `determination_accuracy_gold_qty_unit_given__rule_resolvable` | 37/38 | 97.4% | 86.5%–99.5% |
| `determination_accuracy_gold_qty_unit_given__all_rows` | 37/45 | 82.2% | 68.7%–90.7% |
| `precision_at_1_accepted` | 30/31 | 96.8% | 83.8%–99.4% |
| `coverage_should_match` | 31/31 | 100.0% | 89.0%–100.0% |
| `escalation_accuracy` | 7/7 | 100.0% | 64.6%–100.0% |
| `refusal_accuracy` | 0/0 — not measured (both NO_FACTOR rows need LLM extraction) | — | — |

Determination accuracy (gold qty/unit given): the engine receives the gold quantity and unit and decides the factor, or escalates or refuses. It is NOT end-to-end accuracy (extraction from raw bills is not measured yet).

7 of 45 rows need LLM extraction and are not scored in rules-only mode (incl. both NO_FACTOR rows). Component metrics are computed over the rule-resolved rows; only `…__all_rows` counts all 45.

*History:* Internship (Jul 2026): 100% (n=34) was determination accuracy on clean input; not reproducible from this commit, superseded by the scorecard above.

## 6. The core engineering lesson

> **The accuracy problem was never the matcher or the judge — it was trusting the LLM for something a deterministic domain-rule layer does better.**

The scorecard initially showed the engine *force-matching* fuels it had no factor for and *mislabeling* electricity lines (the LLM returned column headers like "Units Consumed" as the activity). The fix was not a bigger model — it was a **standardization/validation layer** built from the BRSR domain: canonical activity aliases, standard unit conversions, an allow-list of known activities, and mandatory-field checks. After this layer, both **accuracy and honesty jumped**, and the LLM became the exception rather than the default.

**Process that found it:** measure → trace the failure to LLM extraction → replace with domain rules → re-measure → confirm improvement. That measurement-driven loop is the project's real backbone.

## 7. Real-filing check (Tata Motors Limited, BRSR FY2024-25)

The BRSR ingester (`src/brsr_ingest.py`, deterministic, no LLM) runs on a real 117-page regulatory PDF with **no hardcoded page** — it locates the Principle 6 energy table by keyword, parses Indian-format numbers, and:
- **Catches a real double-count** — the filing reports three entity blocks (TML p. 78, TMPVL+TPEML p. 79, combined p. 80) where the combined block equals the sum of its parts (grid electricity 1,061,127 GJ vs 1,061,128 GJ); counting all three would inflate grid electricity 2.0×.
- **Recomputes Scope 2** from grid electricity with source-page lineage: combined block (p. 80) 1,061,128 GJ → 294,758 MWh → 209,779 tCO₂ (CO₂-only, location-based), using the CEA v21.0 value as used in `src/brsr_ingest.py` (0.7117 tCO₂/MWh); v22.0 update pending.
- Notes the location-based vs market-based method difference: 45.8% of the combined block's electricity is renewable (896,271 of 1,957,399 GJ).

Internship (Jul 2026) stated ~2× / ~46%; this re-check computes 2.0× / 45.8%.

*Figures re-checked post-internship (2026-10-22, 6ddea50) by calling `brsr_ingest.ingest_brsr_energy` on `data/Voluntary-Report-based-on-BRSR-Framework-for-FY-2024-25.pdf`.*

## 8. Tech stack

Python 3.12, pandas, pdfplumber, Pydantic, Ollama (local qwen extractor + llama judge + nomic embeddings (suggestions only; no decision)), NumPy, statsmodels (Wilson CI), scikit-learn (Cohen's kappa, for future judge validation), Neo4j (with in-memory fallback), Streamlit, FastAPI.

## 9. Data sources

Currently loaded: CEA CO₂ Baseline Database v21.0 (FY2024-25). Update to v22.0 pending. CEA publishes a single national grid factor; no regional CEA factor exists.

DEFRA GHG conversion factors (fuels), GHG Protocol, IPCC EFDB. All factors are version-stamped; verify before audit use.

## 10. Run it

Python 3.12 (CI uses 3.12; the committed scorecard was produced on 3.12.10).

```
python -m venv .venv
.venv\Scripts\activate                # Windows  (mac/linux: source .venv/bin/activate)
pip install -r requirements.txt       # or requirements-lock.txt for the exact measured environment
python -m pytest -q tests             # no LLM, no network
python src/run_scorecard.py --no-llm  # rules-only scorecard (see §5)
python -m streamlit run src/app.py    # the dashboard
```

- `run_scorecard.py --no-llm` needs a clean git tree; it writes a new dated file to `output/scorecards/` (or `--out-dir DIR`) and never overwrites.
- `run_scorecard.py` without `--no-llm` is the LLM + judge mode: it needs Ollama running, and rewrites `output/scorecard.json`.
- `python src/generate_synthetic_bills.py --out <new folder>` — never `data/`; existing files are never overwritten.
- `python src/calibrate.py` only compares against `output/baseline.json`; `--update-baseline` saves a new baseline.
- Note: `output/baseline.json` predates P01's single decision path and must be regenerated deliberately.

## 11. API contract

Run: `cd src && python -m uvicorn api:app` (docs at `/docs`; `GET /health` reports the loaded factor count).

- `POST /compute` — one line `{activity, quantity, unit, period?}` → one result.
- `POST /batch` — a list of lines → `{total_kgco2e, total_tco2e, basis_mixed, totals_by_basis, total_label, lines_received, lines_accepted, results}`.
- `total_kgco2e` / `total_tco2e` are a plain sum of all accepted lines. Factor bases differ (CEA grid electricity is CO₂-only, DESNZ/DEFRA fuels are CO₂e AR5), so when `basis_mixed` is true, `totals_by_basis` (exact Decimal strings keyed `gas/gwp`, e.g. `CO2/CO2`, `CO2e/AR5`) holds the reportable figures and `total_label` says MIXED. See [ADR-002](docs/adr/ADR-002-mixed-basis-totals.md).
- `quantity ≤ 0`, or an empty `/batch` list → HTTP 422.

| Field | Values |
|---|---|
| `decision` | `accept` \| `escalate` \| `refuse` |
| `match_type` | `exact` (on accept) \| `none` |
| `confidence` | `1.0` on accept, `null` otherwise (no similarity score) |
| `factor_id`, `factor_value`, `emissions_kgco2e`, `trace` | set on accept only |

One decision function (`match.match_line` + `match.resolve_decision`) is shared by the API, dashboard and scorecard:
- **accept** only on an exact activity + unit match in the factor library;
- **escalate** for unknown or unsupported fuels (e.g. furnace oil, pet coke) and for a known activity in a unit with no factor (LPG in kg, CNG in m³);
- **refuse** only when there is no activity or unit and no energy/fuel hint (fuel, energy, consumption, utility).

## 12. Honest limitations

- Tested on synthetic + a real BRSR filing; accuracy intervals are wide due to small n.
- The LLM judge has not been validated against human labels (only a small smoke test); judge numbers are not reported.
- The 45-row gold set has been used during development (DEV only); a sealed held-out test set is planned.
- Local LLM path needs Ollama running; Neo4j is optional (in-memory fallback).

## 13. Status & roadmap

Working end-to-end demo with a rules-only scorecard (§5) and a real-filing check (§7). Roadmap: rule cascade with typed refusals · versioned factor library (CEA v22, DESNZ, BEE with GWP basis) · end-to-end measurement on a sealed test set · miss-rate estimation on declined items.
