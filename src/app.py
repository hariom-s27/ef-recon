"""
app.py — SP-12: polished EF-Recon dashboard (demo centerpiece).
Same engine underneath — restructured with metrics, charts, tabs, and colour.
Now with a "Real filing" tab: runs the engine on a real Tata Motors BRSR PDF.
Run:  python -m streamlit run src/app.py
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from paths import DATA_DIR
from ingest import ingest_csv, ingest_pdf
from extract import extract_with_rules, extract_with_llm, looks_ambiguous
from normalize import normalize_line
from match import load_factors, match_line
from compute import compute_emissions
from dedup import fingerprint, get_site
from brsr_ingest import ingest_brsr_energy, GJ_TO_KWH, CEA_FACTOR
from defend import defend_number
from copilot import ask_copilot

st.set_page_config(page_title="EF-Recon", page_icon="🌱", layout="wide")

# ---- a little styling ----
st.markdown("""
<style>
.block-container { padding-top: 2rem; }
h1 { color: #166534; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_factors():
    return load_factors()


@st.cache_data
def load_brsr(path):
    """Parse the BRSR PDF once and cache it (the 111-page read is slow)."""
    return ingest_brsr_energy(path)


def process(records, factors):
    """Run the pipeline -> list of result dicts (with dedup + emissions)."""
    rows, seen = [], {}
    for r in records:
        if r["source_type"] == "csv":
            extracted = extract_with_rules(r)
            line_id = r["raw"].get("line_id", "?")
            source = f"{r['source_file']} row {r['source_row']}"
            site = get_site(r)
        else:
            extracted = extract_with_llm(r["raw_text"])
            line_id = f"PDF-p{r['source_page']}"
            source = f"{r['source_file']} page {r['source_page']}"
            site = "pdf"
        norm = normalize_line(extracted)

        row = {"line_id": line_id, "activity": norm.activity, "quantity": norm.quantity,
               "unit": norm.unit, "factor_id": "", "factor_value": None,
               "emissions_kgco2e": None, "decision": "", "source": source, "duplicate": False}

        raw_text = " ".join(str(v) for v in r.get("raw", {}).values()) if r["source_type"] == "csv" \
            else r.get("raw_text", "")
        decision, fac = match_line(norm, factors, raw_text=raw_text)
        if decision == "escalate_or_refuse":
            decision = "escalate" if looks_ambiguous(r) else "refuse"

        if decision == "accept":
            # dedup check
            fp = fingerprint(norm, site)
            if fp in seen:
                row["duplicate"] = True
                row["decision"] = "duplicate"
                row["factor_id"] = fac["factor_id"]
                rows.append(row); continue
            seen[fp] = line_id
            emissions = float(compute_emissions(norm.quantity, fac["value"]))
            row.update(factor_id=fac["factor_id"], factor_value=fac["value"],
                       emissions_kgco2e=emissions)
        row["decision"] = decision if not row["duplicate"] else "duplicate"
        rows.append(row)
    return rows


def colour_decision(val):
    colours = {"accept": "#16a34a", "escalate": "#d97706",
               "refuse": "#dc2626", "duplicate": "#6b7280"}
    return f"color: {colours.get(val, 'black')}; font-weight: 600;"


# ================= UI =================
st.title("🌱 EF-Recon")
st.caption("Turn messy utility & fuel bills into **audit-ready carbon numbers** — with full traceability.")

factors = get_factors()

uploaded = st.file_uploader("Upload a bill (CSV or PDF) — or use the built-in sample", type=["csv", "pdf"])
records = []
if uploaded:
    from pathlib import Path
    tmp = Path(DATA_DIR) / uploaded.name
    tmp.write_bytes(uploaded.getbuffer())
    records = ingest_csv(tmp) if uploaded.name.endswith(".csv") else ingest_pdf(tmp)
else:
    for name in ["electricity_bills.csv", "diesel_invoices.csv", "erp_spend_export.csv"]:
        records += ingest_csv(DATA_DIR / name)
    records += ingest_pdf(DATA_DIR / "electricity_bill_sample.pdf")

df = pd.DataFrame(process(records, factors))

# ---- headline metrics ----
total = df["emissions_kgco2e"].dropna().sum()
n_accept = int((df["decision"] == "accept").sum())
n_review = int(df["decision"].isin(["escalate", "refuse"]).sum())
n_dupes = int((df["decision"] == "duplicate").sum())

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total emissions", f"{total:,.0f} kgCO₂e", f"{total/1000:,.2f} tCO₂e")

# read the measured accuracy from the scorecard run
import json
sc_path = DATA_DIR.parent / "output" / "scorecard.json"
if sc_path.exists():
    sc = json.load(open(sc_path))
    p = sc["precision_judge"] * 100
    n = sc["n"]
    esc_r, esc_t = sc["escalation"]
    ref_r, ref_t = sc["refusal"]
    c2.metric("Factor-match accuracy (measured)", f"{p:.0f}%",
              f"Precision@1 · judge · n={n}")
else:
    c2.metric("Factor-match accuracy", "run scorecard", "python src/run_scorecard.py")

c3.metric("Duplicates caught", n_dupes, "removed from total")
c4.metric("Needs review", n_review, "escalated / refused")

if sc_path.exists():
    st.caption(f"Measured on a hand-labeled adversarial set (n={sc['n']}): "
               f"judge Precision@1 {sc['precision_judge']*100:.0f}%, gold cross-check "
               f"{sc['gold_correct']}/{sc['n']} ({sc['gold_correct']/sc['n']*100:.0f}%), "
               f"escalation {esc_r}/{esc_t}. Small n → wide interval, reported honestly.")

st.divider()

# ---- tabs ----
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(
    ["📊 Overview", "📋 Details", "🔍 Explain", "⚠️ Review queue",
     "🏢 Real filing", "🛡️ Defend", "💬 Ask"])

with tab1:
    left, right = st.columns(2)
    accepted = df[df["decision"] == "accept"]
    if not accepted.empty:
        by_activity = accepted.groupby("activity")["emissions_kgco2e"].sum().reset_index()
        fig1 = px.bar(by_activity, x="activity", y="emissions_kgco2e",
                      title="Emissions by activity (kgCO₂e)", color="activity",
                      color_discrete_sequence=px.colors.sequential.Greens_r)
        fig1.update_layout(showlegend=False)
        left.plotly_chart(fig1, use_container_width=True)

    decision_counts = df["decision"].value_counts().reset_index()
    decision_counts.columns = ["decision", "count"]
    fig2 = px.pie(decision_counts, names="decision", values="count",
                  title="Decision breakdown", hole=0.5,
                  color="decision",
                  color_discrete_map={"accept": "#16a34a", "escalate": "#d97706",
                                      "refuse": "#dc2626", "duplicate": "#6b7280"})
    right.plotly_chart(fig2, use_container_width=True)

with tab2:
    st.subheader("All lines")
    show = df[["line_id", "activity", "quantity", "unit", "factor_id",
               "emissions_kgco2e", "decision", "source"]]
    st.dataframe(show.style.map(colour_decision, subset=["decision"]),
                 use_container_width=True, height=500)

with tab3:
    st.subheader("Trace any number to its source")
    accepted = df[df["decision"] == "accept"]
    if not accepted.empty:
        pick = st.selectbox("Pick a line", accepted["line_id"])
        row = accepted[accepted["line_id"] == pick].iloc[0]
        st.success(f"**{row['quantity']} {row['unit']}** × **{row['factor_value']}** "
                   f"(factor `{row['factor_id']}`)  =  **{row['emissions_kgco2e']:,.3f} kgCO₂e**")
        st.info(f"📄 Source: {row['source']}")
        st.caption("Every number traces back to its factor and source document — audit-ready.")

with tab4:
    st.subheader("Lines that need a human")
    queue = df[df["decision"].isin(["escalate", "refuse", "duplicate"])]
    if queue.empty:
        st.write("Nothing to review 🎉")
    else:
        st.dataframe(queue[["line_id", "activity", "unit", "decision", "source"]]
                     .style.map(colour_decision, subset=["decision"]),
                     use_container_width=True)
        st.caption("Escalated = unclear (needs a human). Refused = noise. Duplicate = already counted.")

with tab5:
    st.subheader("Real BRSR filing — Tata Motors FY2024-25")
    st.caption("The engine on a real 111-page regulatory PDF — no hardcoded page, no LLM. "
               "It finds the Principle 6 energy table itself, catches a real double-count, "
               "and recomputes Scope 2 with source-page lineage.")

    brsr_path = DATA_DIR / "Voluntary-Report-based-on-BRSR-Framework-for-FY-2024-25.pdf"

    if not brsr_path.exists():
        st.warning("Place the Tata Motors BRSR PDF in the data/ folder to run this panel.")
    else:
        recs = load_brsr(str(brsr_path))

        # ---- Step 1: what the engine extracted, and from where ----
        st.markdown("##### 1. Auto-extracted energy table (found by keyword, not page number)")
        brsr_df = pd.DataFrame(recs)[
            ["entity", "source_page", "nonrenew_elec_gj", "nonrenew_fuel_gj", "total_energy_gj"]]
        brsr_df.columns = ["Entity", "Source page", "Grid electricity (GJ)",
                           "Fuel (GJ)", "Total energy (GJ)"]
        st.dataframe(brsr_df, use_container_width=True, hide_index=True)

        # ---- Step 2: the dedup catch ----
        st.markdown("##### 2. Duplication check")
        parts = [r for r in recs if r["entity"] in ("TML", "TMPVL+TPEML")]
        combined = next((r for r in recs if r["entity"] and "combined" in r["entity"]), None)
        if combined and len(parts) >= 2:
            sum_elec = sum((p.get("nonrenew_elec_gj") or 0) for p in parts)
            comb_elec = combined.get("nonrenew_elec_gj") or 0
            cc1, cc2 = st.columns(2)
            cc1.metric("Sum of parts (TML + TMPVL+TPEML)", f"{sum_elec:,.0f} GJ")
            cc2.metric("Combined block reported", f"{comb_elec:,.0f} GJ")
            if comb_elec and abs(sum_elec - comb_elec) / comb_elec < 0.01:
                st.error("⚠️ **Double-count detected** — the filing reports both the parts *and* "
                         "their combined total. Counting all three would inflate emissions ~2×. "
                         "The engine counts it **once**.")

        # ---- Step 3: the recompute with lineage ----
        st.markdown("##### 3. Scope 2 recompute (grid electricity × CEA factor)")
        rows = []
        for r in recs:
            gj = r.get("nonrenew_elec_gj")
            if gj is None:
                continue
            mwh = gj * GJ_TO_KWH / 1000
            rows.append({"Entity": r["entity"], "Source page": r["source_page"],
                         "Grid (GJ)": f"{gj:,.0f}", "→ MWh": f"{mwh:,.0f}",
                         "→ tCO₂e (Scope 2)": f"{mwh * CEA_FACTOR:,.0f}"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption(f"Location-based Scope 2 using CEA v21 grid factor ({CEA_FACTOR} tCO₂/MWh), "
                   "traced to the exact source page. Note: the company's *market-based* figure is "
                   "lower — ~46% of their electricity is renewable (two valid GHG Protocol methods).")

with tab6:
    st.subheader("Defend & red-team any number")
    st.caption("Pick an accepted number → the engine writes its defense (factor, why, source, "
               "rejected alternatives), then a red-team agent attacks it on 5 audit angles.")

    accepted = df[df["decision"] == "accept"]
    if accepted.empty:
        st.write("No accepted numbers to defend.")
    else:
        pick = st.selectbox("Pick a number to defend", accepted["line_id"], key="defend_pick")
        row = accepted[accepted["line_id"] == pick].iloc[0]

        # rebuild the normalized line + chosen factor for this row
        from types import SimpleNamespace
        norm = SimpleNamespace(activity=row["activity"], quantity=row["quantity"], unit=row["unit"])
        chosen = next((f for f in factors if f["factor_id"] == row["factor_id"]), None)

        if chosen is None:
            st.warning("Factor not found for this line.")
        elif st.button("🛡️ Defend this number", key="defend_btn"):
            with st.spinner("Building defense + running red-team (a few seconds)..."):
                defense, report = defend_number(
                    norm, chosen, row["source"], row["emissions_kgco2e"], factors)

            # ---- defense file ----
            st.markdown("##### Defense file")
            st.success(f"**{defense['number']}**  —  {defense['formula']}")
            st.write(f"**Why this factor:** {defense['why_chosen']}")
            st.write(f"**Source:** {defense['source']}")
            if defense["rejected_alternatives"]:
                st.markdown("**Rejected alternatives:**")
                for alt in defense["rejected_alternatives"]:
                    st.write(f"- `{alt['factor_id']}` (score {alt['score']}) — {alt['why_not']}")

            # ---- red-team ----
            st.markdown("##### Red-team attack")
            risk = report.overall_risk
            badge = {"low": "🟢 LOW", "medium": "🟠 MEDIUM", "high": "🔴 HIGH"}[risk]
            st.markdown(f"**Overall risk: {badge}**")
            for name in ["outdated_factor", "wrong_region", "unit_mismatch",
                         "double_count", "special_use_misuse"]:
                a = getattr(report, name)
                icon = "⚠️" if a.weakness_found else "✅"
                label = name.replace("_", " ")
                st.write(f"{icon} **{label}** — {a.finding}")
            with st.expander("Red-team reasoning"):
                st.write(report.reasoning)

with tab7:
    st.subheader("Ask the data (grounded copilot)")
    st.caption("Ask anything about these results. The copilot answers ONLY from the computed "
               "rows — it cannot invent a number. Every answer is checked against the data.")

    q = st.text_input("Your question",
                      placeholder="e.g. Which activity has the highest emissions? Why were any lines refused?")
    if q:
        with st.spinner("Answering from the data..."):
            answer, unverified = ask_copilot(q, df)
        st.markdown("##### Answer")
        st.write(answer)
        if unverified:
            st.warning(f"⚠️ Faithfulness check: these numbers weren't found in the data "
                       f"and may be unverified — {', '.join(unverified)}")
        else:
            st.success("✅ Faithfulness check passed — every figure traces to the data.")