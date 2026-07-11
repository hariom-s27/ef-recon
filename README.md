# EF-Recon — Emission-Factor Reconciliation Engine

Turns messy utility/fuel bills into audit-ready carbon numbers with full traceability.
Pipeline: ingest → extract → normalize → match → compute → dedup, with a reliability
harness (Precision@1 + Wilson CI) and a Streamlit dashboard. India-first (CEA, DEFRA).

## Run
    python -m venv .venv
    .venv\Scripts\activate        # Windows
    pip install -r requirements.txt
    python -m streamlit run src/app.py
