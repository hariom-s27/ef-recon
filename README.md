# EF-Recon — Emission-Factor Reconciliation & Reliability Engine

Turn messy utility and fuel bills into **audit-ready carbon numbers** — with full source-to-factor traceability, honest confidence scoring, and a reliability harness that *measures* how accurate the mapping is.

Built **India-first** (CEA grid factor, DEFRA fuels), aimed at the real bottleneck in carbon accounting: **reconciliation, not reporting.**

---

## 1. The problem

Companies must report emissions (BRSR, CCTS, CBAM), but their data is scattered across utility bills, fuel invoices, and ERP exports — in inconsistent units, headers, and formats. The hardest, most error-prone step is **matching each line to the correct emission factor and proving that number to an auditor.** Most teams still do this manually in spreadsheets. SEBI and NSE themselves flag that companies disclose energy in inconsistent units — the exact problem this engine solves.

## 2. What EF-Recon does

Upload a messy bill → the engine:

1. **Ingests** CSV / Excel / PDF bills, attaching a source pointer to every row.
2. **Extracts** activity, quantity, unit, period (rules first, local LLM for free text).
3. **Normalizes** units (MWh→kWh, KL→litre, GJ→kWh) and activity aliases to a canonical form.
4. **Matches** each line to the correct emission factor under a strict, honest policy.
5. **Computes** emissions with exact math and a full audit trail.
6. **Deduplicates** repeated bills so totals aren't double-counted.
7. **Measures itself** — Precision@1 with a Wilson confidence interval, an LLM-as-judge for unlabeled data, plus escalation/refusal accuracy.
8. **Escalates** uncertain lines to a review queue — never silently guesses.

## 3. Architecture

```
Bills (CSV/Excel/PDF)
→ Ingest → Extract → Normalize → Match (activity-first policy) → Dedup
→ Compute (with lineage) → Reliability harness (judge + Precision@1 + CI)
→ Dashboard (Streamlit) + API (FastAPI)
```

## 4. Key design decisions (and why)

| Decision | Why |
|---|---|
| **Rules first, LLM only for genuine free text** | Deterministic domain rules are more accurate *and* faster than an LLM for known patterns. (See §6 — the core lesson.) |
| **Activity-first matching policy** | Two factors can share a unit (electricity and gas both use kWh). Matching on unit alone force-matches the wrong factor; activity must decide first. |
| **Allow-list of known activities/units** | The engine escalates fuels it has no factor for (furnace oil, pet coke) instead of guessing — honest refusal is the differentiator. |
| **Different-family LLM judge (llama vs qwen extractor)** | A model judging its own family over-rewards itself (self-preference bias); a separate family gives trustworthy grades. |
| **Wilson confidence interval, always reported** | Honest small-sample uncertainty. A wide CI stated is stronger than a fake-precise point estimate. |
| **Special-use factors excluded from auto-match** | The Combined Margin factor is CDM-only; the engine never auto-applies it to corporate Scope 2. |

## 5. Results (hand-labeled adversarial test set, n=45)

| Metric | Result |
|---|---|
| Precision@1 (LLM-judge) | ~86% (95% Wilson CI ~69–95%, n=29) |
| Precision@1 (gold cross-check) | ~97% |
| Escalation accuracy (correctly declined unknown fuels) | improved from 1/8 → ~8/8 after the domain-rule layer |
| Duplicate bills caught | ✅ (incl. a real double-count in a live Tata Motors BRSR filing) |
| Traceability | 100% of numbers trace to factor + source page |

*Numbers are from synthetic + real BRSR data; intervals are wide due to small n, and reported honestly.*

## 6. The core engineering lesson

> **The accuracy problem was never the matcher or the judge — it was trusting the LLM for something a deterministic domain-rule layer does better.**

The scorecard initially showed the engine *force-matching* fuels it had no factor for and *mislabeling* electricity lines (the LLM returned column headers like "Units Consumed" as the activity). The fix was not a bigger model — it was a **standardization/validation layer** built from the BRSR domain: canonical activity aliases, standard unit conversions, an allow-list of known activities, and mandatory-field checks. After this layer, both **accuracy and honesty jumped**, and the LLM became the exception rather than the default.

**Process that found it:** measure → trace the failure to LLM extraction → replace with domain rules → re-measure → confirm improvement. That measurement-driven loop is the project's real backbone.

## 7. Real-filing validation (Tata Motors BRSR FY2024-25)

The engine runs on a real 111-page regulatory PDF with **no hardcoded page** — it locates the Principle 6 energy table by keyword, parses Indian-format numbers, and:
- **Catches a real double-count** — the filing reports three entity blocks where the combined block equals the sum of its parts; counting all three would inflate emissions ~2×.
- **Recomputes Scope 2** from real grid electricity (GJ → kWh → CEA factor) with source-page lineage.
- Honestly notes the location-based vs market-based method difference (~46% of the electricity is renewable).

## 8. Tech stack

Python, pandas, pdfplumber, Pydantic, Ollama (local qwen extractor + llama judge + nomic embeddings), NumPy, statsmodels (Wilson CI), scikit-learn (Cohen's kappa), Neo4j (with in-memory fallback), Streamlit, FastAPI, Docker.

## 9. Data sources

CEA CO₂ Baseline Database v21.0 (India grid), DEFRA GHG conversion factors (fuels), GHG Protocol, IPCC EFDB. All factors are version-stamped; verify before audit use.

## 10. Run it

```
python -m venv .venv
.venv\Scripts\activate            # Windows  (mac/linux: source .venv/bin/activate)
pip install -r requirements.txt
python src/run_scorecard.py       # the accuracy harness (Precision@1 + CI)
python -m streamlit run src/app.py  # the dashboard
```

## 11. Honest limitations

- Tested on synthetic + a real BRSR filing; accuracy intervals are wide due to small n.
- The LLM-judge is validated against a gold set (Cohen's kappa) but is itself imperfect — reported as "accuracy as graded by a validated judge," not ground truth.
- Local LLM path needs Ollama running; Neo4j is optional (in-memory fallback).

## 12. Status & roadmap

Working end-to-end demo with a measured reliability harness and real-filing validation. Roadmap: defense-file / red-team agent, provenance-grounded copilot, learning-from-review loop, and deeper India-first regulatory reasoning (CEA regional grid by site/year, BRSR Core KPIs, CBAM).
