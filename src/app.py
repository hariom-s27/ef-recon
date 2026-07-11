"""
app.py — SP-07: a simple Streamlit dashboard for the EF-Recon engine.
Reuses the existing pipeline (no new logic) and shows results visually.
Run:  streamlit run app.py
"""

import pandas as pd
import streamlit as st

from ingest import ingest_csv, ingest_pdf
from extract import extract_with_rules, extract_with_llm, looks_ambiguous
from normalize import normalize_line
from match import load_factors, exact_match, semantic_match, ACCEPT_SCORE, ESCALATE_SCORE
from compute import compute_emissions
from paths import BASE_DIR, DATA_DIR

st.set_page_config(page_title="EF-Recon", page_icon="🌱", layout="wide")


# cache the factor library so we don't re-embed on every click (fast!)
@st.cache_resource
def get_factors():
    return load_factors()


def process(records, factors):
    """Run the pipeline over records -> list of result dicts for the table."""
    rows = []
    for r in records:
        if r["source_type"] == "csv":
            extracted = extract_with_rules(r)
            line_id = r["raw"].get("line_id", "?")
            source = f"{r['source_file']} row {r['source_row']}"
        else:
            extracted = extract_with_llm(r["raw_text"])
            line_id = f"PDF-p{r['source_page']}"
            source = f"{r['source_file']} page {r['source_page']}"
        norm = normalize_line(extracted)

        row = {"line_id": line_id, "activity": norm.activity, "quantity": norm.quantity,
               "unit": norm.unit, "factor_id": "", "emissions_kgco2e": None,
               "decision": "", "source": source}

        if norm.activity == "unknown" or norm.unit is None:
            row["decision"] = "escalate" if looks_ambiguous(r) else "refuse"
            rows.append(row); continue

        fac = exact_match(norm, factors)
        if fac:
            score, decision = 1.0, "accept"
        else:
            fac, score = semantic_match(norm, factors)
            decision = ("accept" if score >= ACCEPT_SCORE else
                        "escalate" if score >= ESCALATE_SCORE else "refuse")

        if decision == "accept":
            emissions = compute_emissions(norm.quantity, fac["value"])
            row.update(factor_id=fac["factor_id"], emissions_kgco2e=float(emissions),
                       factor_value=fac["value"])
        row["decision"] = decision
        rows.append(row)
    return rows


# ---------------- UI ----------------
st.title("🌱 EF-Recon — Emission-Factor Reconciliation")
st.caption("Upload messy bills → get audit-ready carbon numbers with full traceability.")

factors = get_factors()

# let the user upload, OR use the built-in sample data
uploaded = st.file_uploader("Upload a bill (CSV or PDF)", type=["csv", "pdf"])

records = []
if uploaded:
    tmp = BASE_DIR / uploaded.name
    tmp.write_bytes(uploaded.getbuffer())
    records = ingest_csv(tmp) if uploaded.name.endswith(".csv") else ingest_pdf(tmp)
else:
    st.info("No file uploaded — showing the built-in sample data.")
    records += ingest_csv(DATA_DIR / "electricity_bills.csv")
    records += ingest_csv(DATA_DIR / "diesel_invoices.csv")
    records += ingest_csv(DATA_DIR / "erp_spend_export.csv")
    records += ingest_pdf(DATA_DIR / "electricity_bill_sample.pdf")

rows = process(records, factors)
df = pd.DataFrame(rows)

# --- top metrics ---
total = df["emissions_kgco2e"].dropna().sum()
c1, c2, c3 = st.columns(3)
c1.metric("Total emissions", f"{total:,.0f} kgCO₂e", f"{total/1000:,.2f} tCO₂e")
c2.metric("Lines accepted", int((df["decision"] == "accept").sum()))
c3.metric("Needs review / refused",
          int(df["decision"].isin(["escalate", "refuse"]).sum()))

# --- main results table ---
st.subheader("Results")
st.dataframe(df[["line_id", "activity", "quantity", "unit", "factor_id",
                 "emissions_kgco2e", "decision", "source"]], width="stretch")

# --- explain this number ---
st.subheader("🔍 Explain a number")
accepted = df[df["decision"] == "accept"]
if not accepted.empty:
    pick = st.selectbox("Pick a line", accepted["line_id"])
    row = accepted[accepted["line_id"] == pick].iloc[0]
    st.write(f"**Line:** {row['line_id']}")
    st.write(f"**Formula:** {row['quantity']} {row['unit']} × {row.get('factor_value','?')} "
             f"(factor {row['factor_id']}) = **{row['emissions_kgco2e']:,.3f} kgCO₂e**")
    st.write(f"**Source:** {row['source']}")

# --- review queue ---
st.subheader("⚠️ Review queue (uncertain lines)")
queue = df[df["decision"].isin(["escalate", "refuse"])]
if not queue.empty:
    st.dataframe(queue[["line_id", "activity", "unit", "decision", "source"]],
                 width="stretch")
else:
    st.write("Nothing to review 🎉")