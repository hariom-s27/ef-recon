"""
defend.py — #2 Defense-File + Red-Team agent.
For any accepted emission number, it (a) writes the DEFENSE (why this factor,
source, rejected alternatives) and (b) RED-TEAMS it against a fixed audit checklist.
Reuses your factor library + the local llama judge model. No new installs.
"""
from typing import Literal, Optional
from pydantic import BaseModel, Field
import numpy as np
import ollama
from config import EMBED_MODEL
from match import load_factors        # only need the loader

# self-contained so defend.py works regardless of match.py version
SPECIAL_USE = {"EF-IN-ELEC-GRID-CM"}   # Combined Margin: never valid for corporate Scope 2

def embed(text):
    return np.array(ollama.embeddings(model=EMBED_MODEL, prompt=text)["embedding"])

def cosine(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

JUDGE_MODEL = "llama3.1:8b"     # different family from extractor — same as your judge


# ---------- 1. the red-team output shape ----------
class Attack(BaseModel):
    check: str = Field(description="the risk being tested")
    passed: bool = Field(description="true = number survives this attack, false = weakness found")
    finding: str = Field(description="one-sentence explanation grounded in the factor's real fields")

class RedTeamReport(BaseModel):
    reasoning: str = Field(description="step-by-step review before the per-check verdicts")
    outdated_factor: Attack
    wrong_region: Attack
    unit_mismatch: Attack
    double_count: Attack
    special_use_misuse: Attack
    overall_risk: Literal["low", "medium", "high"] = Field(description="final risk after all checks")


# ---------- 2. DEFENSE FILE (deterministic — no LLM needed) ----------
def ranked_candidates(norm, factors, top_k=3):
    """Return the top-K closest factors by embedding — the 'considered' set."""
    line_vec = embed(f"{norm.activity} {norm.unit}")
    scored = [(cosine(line_vec, f["vector"]), f) for f in factors
              if f["factor_id"] not in SPECIAL_USE]
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top_k]

def build_defense(norm, chosen, source, emissions, factors):
    """Assemble the defense file for one accepted number. Pure data, no AI."""
    considered = ranked_candidates(norm, factors, top_k=3)
    rejected = []
    for score, fac in considered:
        if fac["factor_id"] == chosen["factor_id"]:
            continue
        reason = _why_not(norm, fac)
        rejected.append({"factor_id": fac["factor_id"], "score": round(score, 3), "why_not": reason})

    return {
        "number": f"{emissions:,.3f} kgCO2e",
        "formula": f"{norm.quantity} {norm.unit} × {chosen['value']} (factor {chosen['factor_id']})",
        "chosen_factor": chosen["factor_id"],
        "why_chosen": f"activity '{norm.activity}' and unit '{norm.unit}' both match "
                      f"factor {chosen['factor_id']} ({chosen.get('region', 'GLOBAL')}).",
        "source": source,
        "rejected_alternatives": rejected,
    }

def _why_not(norm, fac):
    """One-line reason this candidate was NOT picked — grounded in real fields."""
    if fac["activity_type"] != (norm.activity or "").lower():
        return f"different activity ('{fac['activity_type']}' vs line '{norm.activity}')"
    if fac["unit_in"] != (norm.unit or "").lower():
        return f"unit mismatch (factor is '{fac['unit_in']}', line is '{norm.unit}')"
    if fac["factor_id"] in SPECIAL_USE:
        return "special-use factor (e.g. Combined Margin) — not valid for corporate Scope 2"
    return "lower semantic match than the chosen factor"


# ---------- 3. RED-TEAM (llama attacks the number) ----------
AGGREGATE_HINTS = ["total", "summary", "rollup", "roll-up", "combined", "all sites", "all locations"]

def red_team(defense, chosen, norm, reporting_year="FY2024-25"):
    is_special = chosen["factor_id"] in SPECIAL_USE
    source_year = chosen.get("source_year") or "not stated in the factor library"
    line_unit = norm.unit or "not stated"
    source_text = defense["source"] or ""
    looks_like_aggregate = any(h in source_text.lower() for h in AGGREGATE_HINTS)

    prompt = f"""You are a Big-4 carbon auditor trying to REJECT this emission number.
Attack it on each checklist item. A check 'passed' = the number survives that attack.
Ground every finding in the real facts given below — do NOT invent problems, and do NOT
mark a check as a weakness just because a fact wasn't explicitly re-stated if it is
already given here.

NUMBER: {defense['number']}
FORMULA: {defense['formula']}
CHOSEN FACTOR: {chosen['factor_id']} | activity: {chosen['activity_type']} | region: {chosen.get('region', 'N/A')}
FACTOR SOURCE: {chosen.get('source', 'N/A')} | FACTOR VINTAGE: {source_year}
REPORTING PERIOD: {reporting_year}
LINE UNIT (already normalized): {line_unit}   FACTOR UNIT: {chosen['unit_in']}
IS THIS A SPECIAL-USE FACTOR (e.g. Combined Margin, CDM-only)? {"YES" if is_special else "NO — this is a standard factor, valid for corporate Scope 2"}
SOURCE DOC: {defense['source']}

Checklist. IMPORTANT: "passed": true is the DEFAULT and CORRECT answer for every check below
unless the specific fail condition is clearly met. Do not set "passed": false out of general
caution — only when the stated fail condition is true.

- outdated_factor:
    FAIL condition: FACTOR VINTAGE is chronologically EARLIER than REPORTING PERIOD.
    PASS condition (default): FACTOR VINTAGE is the same as or later than REPORTING PERIOD.
    Here FACTOR VINTAGE={source_year} and REPORTING PERIOD={reporting_year} — compare them
    literally as periods, and if they are equal, that is a PASS, not a fail.
- wrong_region:
    FAIL condition: the factor's region is a specific country/grid different from the line's country.
    PASS condition (default): region matches, or factor region is Global.
- unit_mismatch:
    FAIL condition: LINE UNIT and FACTOR UNIT are different physical quantity types (e.g. volume vs energy).
    PASS condition (default): LINE UNIT equals FACTOR UNIT (given above, already normalized) — this is a PASS.
- double_count:
    AGGREGATE_LANGUAGE_DETECTED (computed by string search, not your judgment): {looks_like_aggregate}
    FAIL condition: AGGREGATE_LANGUAGE_DETECTED is True.
    PASS condition (default): AGGREGATE_LANGUAGE_DETECTED is False. A plain filename (e.g.
    "electricity_bills.csv", "diesel_invoices.csv") plus a row/page number is NOT aggregate
    language — the mere fact that a source is named at all is not evidence of double-counting.
- special_use_misuse:
    FAIL condition: IS THIS A SPECIAL-USE FACTOR above says YES.
    PASS condition (default): it says NO.

Reason first, then give a verdict per check, then an overall_risk. Return JSON only."""

    resp = ollama.chat(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        format=RedTeamReport.model_json_schema(),
        options={"temperature": 0},
    )
    return RedTeamReport.model_validate_json(resp.message.content)


# ---------- 4. one-call convenience ----------
def defend_number(norm, chosen, source, emissions, factors):
    defense = build_defense(norm, chosen, source, emissions, factors)
    report = red_team(defense, chosen, norm)
    return defense, report


# ---------- 5. smoke test ----------
if __name__ == "__main__":
    from types import SimpleNamespace
    print("Loading factors...")
    factors = load_factors()

    # fake an accepted electricity line
    norm = SimpleNamespace(activity="electricity", quantity=42427, unit="kWh")
    chosen = next(f for f in factors if f["factor_id"] == "EF-IN-ELEC-GRID")
    emissions = norm.quantity * chosen["value"]

    defense, report = defend_number(norm, chosen, "electricity_bills.csv row 6", emissions, factors)

    print("\n===== DEFENSE FILE =====")
    for k, v in defense.items():
        print(f"{k}: {v}")

    print("\n===== RED-TEAM =====")
    print("reasoning:", report.reasoning[:200])
    for name in ["outdated_factor", "wrong_region", "unit_mismatch", "double_count", "special_use_misuse"]:
        a = getattr(report, name)
        print(f"  {name:20} {'PASS' if a.passed else 'WEAKNESS'} — {a.finding[:90]}")
    print(f"  OVERALL RISK: {report.overall_risk.upper()}")