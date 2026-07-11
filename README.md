# EF-Recon — Emission-Factor Reconciliation & Reliability Engine

Turn messy utility and fuel bills into **audit-ready carbon numbers** — with full
source-to-factor traceability, confidence scoring, and a reliability harness that
*measures* how accurate the mapping is.

Built India-first (CEA grid factor, DEFRA fuels), inspired by the real bottleneck in
carbon accounting: **reconciliation, not reporting.**

---

## The problem

Companies must report emissions (BRSR, CCTS, CBAM), but their data is scattered across
utility bills, fuel invoices, and ERP exports — in inconsistent units, headers, and
formats. The hardest, most error-prone step is **matching each line to the correct
emission factor** and *proving* that number to an auditor. Most teams still do this
manually in spreadsheets.

## What EF-Recon does

Upload a messy bill → the engine:
1. **Ingests** CSV / Excel / PDF bills.
2. **Extracts** activity, quantity, unit, and period (rules + a local LLM for free text).
3. **Normalizes** units (MWh→kWh, KL→litre) and labels.
4. **Matches** each line to the correct emission factor (exact rules → knowledge-graph
   hard rules → semantic embeddings fallback → escalate if unsure).
5. **Computes** emissions with exact `Decimal` math and a full audit trail.
6. **Deduplicates** repeated bills so totals aren't double-counted.
7. **Measures itself** — Precision@1 with a Wilson confidence interval, plus calibration
   (ECE) and a regression test against a saved baseline.

Uncertain lines are **escalated to a review queue**, never silently guessed.

## Results (on synthetic India-first test data)

| Metric | Result |
|---|---|
| Factor-match accuracy (Precision@1) | **100%** (95% Wilson CI 88–100%, n=29) |
| Noise lines correctly refused | 2 / 2 |
| Ambiguous lines correctly escalated | 1 / 1 |
| Duplicate bills caught | 1 (removed from total) |
| Calibration (ECE) | 0.000 (trivial — most matches are exact; see caveats) |
| Traceability | 100% of numbers trace to factor + source |

## Architecture

```
Bills (CSV/Excel/PDF)
  → Ingest → Extract → Normalize → Dedup → Match (rules + graph + embeddings)
  → Compute (Decimal + lineage) → Reliability harness (Precision@1, ECE, regression)
  → Dashboard (Streamlit)  +  API (FastAPI)
```

## Tech stack

Python, pandas, pdfplumber, Pydantic, Ollama (local LLM + embeddings, `nomic-embed-text`),
NumPy, statsmodels (Wilson CI), Neo4j (with in-memory fallback), Streamlit, FastAPI, Docker.

## Data sources

CEA CO₂ Baseline Database v21.0 (India grid), DEFRA GHG conversion factors (fuels),
GHG Protocol, IPCC EFDB. *(All factors are version-stamped; verify before audit use.)*

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (mac/linux: source .venv/bin/activate)
pip install -r requirements.txt

# 1) run the full pipeline + accuracy report
python src/evaluate.py

# 2) launch the dashboard
python -m streamlit run src/app.py

# 3) launch the API
cd src && python -m uvicorn api:app --reload
# then open http://127.0.0.1:8000/docs
```

## Project structure

```
ef-recon/
├── data/          # bills, gold answer key, emission-factor library
├── output/        # computed results, baseline, reports
├── src/           # pipeline (ingest→...→compute), dedup, graph, evaluate, app, api
└── requirements.txt
```

## Honest limitations

- Tested on **synthetic** India-first data (no real customer data); accuracy intervals
  are wide due to small sample size (n=29).
- Calibration (ECE) is trivially perfect because most lines resolve via exact match;
  it becomes meaningful with more semantic (fuzzy) matches.
- Neo4j is optional (in-memory fallback); the local LLM path needs Ollama running.

## Status

Working end-to-end demo. Roadmap: live ERP/utility ingestion, wider factor coverage,
active-learning from human review, and BRSR/CCTS report generation.
