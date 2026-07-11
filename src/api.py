"""
api.py — SP-12: upgraded EF-Recon API (FastAPI).
Improvements: self-documenting endpoints, example values, proper error handling,
a /batch endpoint for many lines, and traceability in the response.

Run:  cd src && python -m uvicorn api:app --reload
Docs: http://127.0.0.1:8000/docs
"""

from typing import Optional, List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from normalize import normalize_line
from extract import ExtractedLine
from config import ACCEPT_SCORE, ESCALATE_SCORE
from match import load_factors, exact_match, semantic_match
from compute import compute_emissions

app = FastAPI(
    title="EF-Recon API",
    description="Turn messy bill lines into audit-ready carbon numbers, "
                "with the matched factor, computed emissions, confidence, and full traceability.",
    version="1.0.0",
)

FACTORS = load_factors()   # loaded once at startup (fast)


# ---------- request model (with examples + descriptions) ----------
class BillLine(BaseModel):
    activity: str = Field(..., description="Activity type, e.g. electricity, diesel, petrol",
                          examples=["electricity"])
    quantity: float = Field(..., description="Numeric amount used (must be > 0)",
                            examples=[36098])
    unit: str = Field(..., description="Unit, e.g. kWh, MWh, litre, KL, m3",
                      examples=["kWh"])
    period: Optional[str] = Field(None, description="Billing period or date",
                                  examples=["01-Jun-2025"])


# ---------- response model (now includes traceability) ----------
class Result(BaseModel):
    activity: str
    quantity: float
    unit: str
    factor_id: Optional[str] = None
    factor_value: Optional[float] = None
    emissions_kgco2e: Optional[float] = None
    decision: str                              # accept / escalate / refuse
    match_type: str                            # exact / semantic / none
    confidence: float
    trace: Optional[str] = None                # the audit trail (formula + factor)


# ---------- the shared engine logic ----------
def _process_line(line: BillLine) -> Result:
    # validation -> clean error instead of a crash
    if line.quantity <= 0:
        raise HTTPException(status_code=422, detail="quantity must be greater than 0")

    extracted = ExtractedLine(activity=line.activity, quantity=line.quantity,
                              unit=line.unit, period=line.period)
    norm = normalize_line(extracted)

    if norm.activity == "unknown" or norm.unit is None:
        return Result(activity=norm.activity, quantity=line.quantity, unit=line.unit,
                      decision="refuse", match_type="none", confidence=0.0)

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
        trace = (f"{norm.quantity} {norm.unit} × {fac['value']} "
                 f"(factor {fac['factor_id']}) = {emissions} kgCO2e")
        return Result(activity=norm.activity, quantity=norm.quantity, unit=norm.unit,
                      factor_id=fac["factor_id"], factor_value=fac["value"],
                      emissions_kgco2e=emissions, decision=decision,
                      match_type=match_type, confidence=round(confidence, 3), trace=trace)

    return Result(activity=norm.activity, quantity=norm.quantity, unit=norm.unit,
                  factor_id=fac["factor_id"] if fac else None,
                  decision=decision, match_type=match_type, confidence=round(confidence, 3))


# ---------- endpoints ----------
@app.get("/", summary="Welcome")
def home():
    return {"message": "EF-Recon API is running. Open /docs to try it."}


@app.get("/health", summary="Health check",
         description="Returns 'ok' and how many emission factors are loaded.")
def health():
    return {"status": "ok", "factors_loaded": len(FACTORS)}


@app.post("/compute", response_model=Result,
          summary="Compute emissions for ONE bill line",
          description="Takes a single activity line and returns the matched factor, "
                      "computed emissions, confidence, decision, and a traceability string.")
def compute(line: BillLine):
    return _process_line(line)


@app.post("/batch",
          summary="Compute emissions for MANY bill lines at once",
          description="Takes a list of activity lines. Returns each result plus the "
                      "total accepted emissions and a small summary.")
def batch(lines: List[BillLine]):
    if not lines:
        raise HTTPException(status_code=422, detail="send at least one line")

    results, total, accepted = [], 0.0, 0
    for line in lines:
        r = _process_line(line)
        results.append(r)
        if r.decision == "accept" and r.emissions_kgco2e:
            total += r.emissions_kgco2e
            accepted += 1

    return {
        "total_kgco2e": round(total, 3),
        "total_tco2e": round(total / 1000, 3),
        "lines_received": len(lines),
        "lines_accepted": accepted,
        "results": results,
    }