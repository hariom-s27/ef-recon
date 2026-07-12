# src/judge.py
"""
LLM-as-judge for EF-Recon.
Grades whether a chosen emission factor is correct for a given bill line,
so we can measure accuracy on REAL data that has no gold answer key.
"""
from typing import Literal
from pydantic import BaseModel, Field
import ollama
from sklearn.metrics import cohen_kappa_score
from statsmodels.stats.proportion import proportion_confint


# ---------- 1. The verdict shape (reason first, verdict last) ----------
class JudgeVerdict(BaseModel):
    reasoning: str = Field(description="explicit step-by-step check of activity, unit, and region")
    activity_match: bool = Field(description="does the factor's activity match the line's activity?")
    unit_compatible: bool = Field(description="can the factor's unit be applied to the line's unit?")
    region_appropriate: bool = Field(description="is the factor usable for the line's country/region?")
    verdict: Literal["correct", "incorrect"] = Field(description="final call, made AFTER the checks above")


# ---------- 2. The rubric prompt (the heart) ----------
def build_prompt(line_text, factor):
    return f"""You are an expert carbon-accounting auditor checking ONE emission-factor match.

BILL LINE (what the company consumed):
{line_text}

CHOSEN EMISSION FACTOR (what our engine picked):
  id: {factor.get('id')} | name: {factor.get('name')} | activity: {factor.get('activity')}
  unit: {factor.get('unit')} | region: {factor.get('region')} | year: {factor.get('year')}

Work through these THREE checks one by one, writing a short sentence for each, THEN decide.

1. activity_match: Does the factor's activity describe the same thing the line consumed?
   (e.g. a diesel line needs a diesel factor; an electricity line needs an electricity factor.)

2. unit_compatible: Can this factor's unit be applied to the line's quantity?
   IMPORTANT: the line's unit is ALREADY NORMALIZED to the factor's base unit before you see it.
   These are all COMPATIBLE and must pass: MWh/GJ/kWh -> kWh; KL/L/litre -> litre; m3/Sm3 -> m3.
   So "line shows KL" with a "litre" factor is CORRECT (KL was converted to litre). Only fail this
   check if the units are genuinely different physical types (e.g. a litre line vs a kWh factor).

3. region_appropriate: Is this factor usable for the line's country (assume India unless stated)?
   IMPORTANT: a factor with region "Global" is ALWAYS region-appropriate — global fuel factors
   (e.g. diesel, petrol) apply everywhere. Only mark region_appropriate = false if the factor is
   for a clearly WRONG specific country (e.g. a UK-only grid factor used for an India electricity line).
   A matching country OR a "Global" factor both count as appropriate.

Final rule: verdict = "correct" ONLY if all three checks pass. Otherwise "incorrect".
Reason about THIS specific line and factor — do not output a generic sentence.
Return JSON only."""


# ---------- 3. Judge one line ----------
def judge_one(line_text, factor, model="llama3.1:8b"):
    resp = ollama.chat(
        model=model,                                   # different family from the extractor (qwen) -> avoids self-preference bias
        messages=[{"role": "user", "content": build_prompt(line_text, factor)}],
        format=JudgeVerdict.model_json_schema(),       # constrains output to our schema
        options={"temperature": 0},                    # repeatable verdicts
    )
    return JudgeVerdict.model_validate_json(resp.message.content)


# ---------- 4. Make planted-wrong pairs (the circularity fix) ----------
def make_negative_pairs(correct_pairs, all_factors):
    """Each line matched to a DIFFERENT-activity factor => a known 'incorrect' pair."""
    negatives = []
    for line_text, correct_factor in correct_pairs:
        wrong = next(f for f in all_factors if f["id"] != correct_factor["id"])
        negatives.append((line_text, wrong, "incorrect"))
    return negatives


# ---------- 5. Validate the judge against known answers ----------
def validate_judge(labeled_pairs, model="llama3.1:8b"):
    """labeled_pairs: list of (line_text, factor, expected) with expected in {'correct','incorrect'}."""
    expected, predicted = [], []
    for line_text, factor, exp in labeled_pairs:
        v = judge_one(line_text, factor, model=model)
        expected.append(exp)
        predicted.append(v.verdict)

    # honest raw agreement: how many rows the judge got right, out of all rows
    n_right = sum(e == p for e, p in zip(expected, predicted))
    agree = n_right / len(expected)
    kappa = cohen_kappa_score(expected, predicted)
    print(f"Judge raw agreement: {agree:.1%}  ({n_right}/{len(expected)} rows)")
    print(f"Judge Cohen's kappa: {kappa:.3f}")
    if len(expected) < 20:
        print("NOTE: n < 20 — kappa is unstable here; trust the per-row results above it.")
    return kappa


# ---------- 6. Score real data using the judge as the answer key ----------
def scorecard(engine_outputs, model="llama3.1:8b"):
    """engine_outputs: list of (line_text, chosen_factor) from your engine on REAL data.
       chosen_factor is None when the engine escalated/refused — skip those."""
    correct = total = 0
    for line_text, factor in engine_outputs:
        if factor is None:
            continue
        total += 1
        if judge_one(line_text, factor, model=model).verdict == "correct":
            correct += 1
    p = correct / total if total else 0.0
    lo, hi = proportion_confint(correct, total, alpha=0.05, method="wilson")
    print(f"Precision@1 (REAL): {p:.1%}  (95% Wilson CI {lo:.1%}-{hi:.1%}, n={total})")
    return p, lo, hi, total


# ---------- 7. Smoke test ----------
if __name__ == "__main__":
    elec = {"id": "EF-IN-ELEC-GRID", "name": "India grid electricity",
            "activity": "electricity", "unit": "kWh", "region": "India", "year": 2024}
    diesel = {"id": "EF-DIESEL-L", "name": "Diesel (HSD) combustion",
              "activity": "diesel", "unit": "litre", "region": "Global", "year": 2024}

    labeled_pairs = [
        ("Electricity purchased from grid: 42,427 kWh", elec,   "correct"),
        ("Diesel for DG set (HSD): 2,076 L",            diesel, "correct"),
        ("Diesel for DG set (HSD): 2,076 L",            elec,   "incorrect"),
        ("Electricity purchased from grid: 42,427 kWh", diesel, "incorrect"),
    ]

    print("Running judge smoke test (first call loads the model — give it a moment)...\n")
    for line, factor, expected in labeled_pairs:
        v = judge_one(line, factor)
        flag = "OK" if v.verdict == expected else "XX  <-- MISMATCH"
        print(f"LINE   : {line}")
        print(f"  factor={factor['id']}  expected={expected}  ->  judge={v.verdict}   [{flag}]")
        print(f"  reason: {v.reasoning[:160]}\n")

    validate_judge(labeled_pairs)