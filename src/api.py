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
from match import read_factor_rows, match_line, resolve_decision
from compute import compute_emissions
from totals import factor_bases, sum_by_basis

app = FastAPI(
    title="EF-Recon API",
    description="Turn messy bill lines into audit-ready carbon numbers, "
                "with the matched factor, computed emissions, a decision "
                "(accept / escalate / refuse), and full traceability.",
    version="1.0.0",
)

FACTORS = read_factor_rows()   # loaded once at startup (no cache, no embeddings needed)
BASES = factor_bases()         # factor_id -> (gas_basis, gwp_basis), for basis-aware totals (ADR-002)


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
    value_status: Optional[str] = None
    factor_row_id: Optional[str] = None
    emissions_kgco2e: Optional[float] = None
    decision: str                              # accept / escalate / refuse
    match_type: str                            # exact / none
    confidence: Optional[float] = None         # 1.0 when accepted, else None
    trace: Optional[str] = None                # the audit trail (formula + factor)


# ---------- the shared engine logic ----------
def _process_line(line: BillLine) -> Result:
    # validation -> clean error instead of a crash
    if line.quantity <= 0:
        raise HTTPException(status_code=422, detail="quantity must be greater than 0")

    extracted = ExtractedLine(activity=line.activity, quantity=line.quantity,
                              unit=line.unit, period=line.period)
    norm = normalize_line(extracted)

    # the ONE decision path (same as the dashboard and scorecard)
    decision, fac = match_line(norm, FACTORS, raw_text=f"{line.activity} {line.unit}")
    decision = resolve_decision(decision, {"raw": {"activity": line.activity, "unit": line.unit}})

    if decision == "accept":
        emissions = float(compute_emissions(norm.quantity, fac["value"]))
        trace = (f"{norm.quantity} {norm.unit} × {fac['value']} "
                 f"(factor {fac['factor_id']}) = {emissions} kgCO2e")
        validity = (f"{fac['valid_from']}..{fac['valid_to']}"
                    if fac["valid_from"] else "always valid")
        trace += (f" [value_status={fac['value_status']}; row={fac['row_id']}; "
                  f"REPORTING_FY={fac['reporting_fy']}; validity={validity}]")
        return Result(activity=norm.activity, quantity=norm.quantity, unit=norm.unit,
                      factor_id=fac["factor_id"], factor_value=fac["value"],
                      value_status=fac["value_status"], factor_row_id=fac["row_id"],
                      emissions_kgco2e=emissions, decision=decision,
                      match_type="exact", confidence=1.0, trace=trace)

    # escalate / refuse: no factor, no confidence score
    return Result(activity=norm.activity, quantity=norm.quantity, unit=norm.unit or line.unit,
                  decision=decision, match_type="none")


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
          description="Takes a single activity line and returns the decision, and for accepted "
                      "lines the matched factor, computed emissions and a traceability string. "
                      "Only an exact activity + unit match is accepted.")
def compute(line: BillLine):
    return _process_line(line)


@app.post("/batch",
          summary="Compute emissions for MANY bill lines at once",
          description="Takes a list of activity lines. Returns each result plus the "
                      "total accepted emissions and a small summary. total_kgco2e is a plain "
                      "sum; when basis_mixed is true, totals_by_basis holds the reportable "
                      "figures (ADR-002).")
def batch(lines: List[BillLine]):
    if not lines:
        raise HTTPException(status_code=422, detail="send at least one line")

    results, counted = [], []
    for line in lines:
        r = _process_line(line)
        results.append(r)
        if r.decision == "accept" and r.emissions_kgco2e:
            gas, gwp = BASES.get(r.factor_id, ("", ""))
            counted.append({"emissions_kg": r.emissions_kgco2e, "gas_basis": gas, "gwp_basis": gwp})

    totals = sum_by_basis(counted)     # Decimal, split per gas/GWP basis
    total = float(totals["total_kg"])
    return {
        "total_kgco2e": round(total, 3),
        "total_tco2e": round(total / 1000, 3),
        "basis_mixed": totals["basis_mixed"],
        "totals_by_basis": {k: str(v) for k, v in totals["by_basis"].items()},
        "total_label": totals["label"],
        "lines_received": len(lines),
        "lines_accepted": len(counted),
        "results": results,
    }
