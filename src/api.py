"""
api.py — SP-11: a web API for the EF-Recon engine (FastAPI).
Other programs send bill data as JSON -> get back emissions + factor + confidence.
Reuses the existing pipeline (no new logic).

Run:  uvicorn api:app --reload   (from inside the src/ folder)
Then open http://127.0.0.1:8000/docs  to test it in your browser.
"""

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

from normalize import normalize_line
from extract import ExtractedLine
from match import load_factors, exact_match, semantic_match, ACCEPT_SCORE, ESCALATE_SCORE
from compute import compute_emissions

app = FastAPI(title="EF-Recon API", description="Turn a bill line into audit-ready carbon numbers.")

# load the factor library ONCE when the server starts (not on every request = fast)
FACTORS = load_factors()


# ---------- what a request looks like ----------
class BillLine(BaseModel):
    activity: str                       # e.g. "electricity"
    quantity: float                     # e.g. 36098
    unit: str                           # e.g. "kWh"
    period: Optional[str] = None


# ---------- what a response looks like ----------
class Result(BaseModel):
    activity: str
    quantity: float
    unit: str
    factor_id: Optional[str] = None
    factor_value: Optional[float] = None
    emissions_kgco2e: Optional[float] = None
    decision: str                        # accept / escalate / refuse
    match_type: str                      # exact / semantic / none


# ---------- endpoint 0: friendly root ----------
@app.get("/")
def home():
    return {"message": "EF-Recon API is running. Go to /docs to try it."}


# ---------- endpoint 1: health check ----------
@app.get("/health")
def health():
    """Simple 'are you alive?' check."""
    return {"status": "ok", "factors_loaded": len(FACTORS)}


# ---------- endpoint 2: compute emissions for one bill line ----------
@app.post("/compute", response_model=Result)
def compute(line: BillLine):
    # turn the request into the same shape our pipeline uses
    extracted = ExtractedLine(activity=line.activity, quantity=line.quantity,
                              unit=line.unit, period=line.period)
    norm = normalize_line(extracted)

    # noise / no unit -> refuse
    if norm.activity == "unknown" or norm.unit is None:
        return Result(activity=norm.activity, quantity=line.quantity, unit=line.unit,
                      decision="refuse", match_type="none")

    # match: exact first, else semantic
    fac = exact_match(norm, FACTORS)
    if fac:
        confidence, match_type = 1.0, "exact"
    else:
        fac, confidence = semantic_match(norm, FACTORS)
        match_type = "semantic"

    decision = ("accept" if confidence >= ACCEPT_SCORE else
                "escalate" if confidence >= ESCALATE_SCORE else "refuse")

    if decision == "accept":
        emissions = float(compute_emissions(norm.quantity, fac["value"]))
        return Result(activity=norm.activity, quantity=norm.quantity, unit=norm.unit,
                      factor_id=fac["factor_id"], factor_value=fac["value"],
                      emissions_kgco2e=emissions, decision=decision, match_type=match_type)
    else:
        return Result(activity=norm.activity, quantity=norm.quantity, unit=norm.unit,
                      factor_id=fac["factor_id"] if fac else None,
                      decision=decision, match_type=match_type)