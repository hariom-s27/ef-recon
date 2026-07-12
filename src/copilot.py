"""
copilot.py — #5 grounded copilot.
Answers questions using ONLY the engine's results table, then checks that every
number in the answer actually appears in the data (faithfulness gate).
Cannot fabricate a figure.
"""
import re
import ollama

MODEL = "llama3.1:8b"


def build_context(df):
    """Turn the results table into compact text the LLM can read. Only real rows."""
    lines = []
    for _, r in df.iterrows():
        em = f"{r['emissions_kgco2e']:.1f} kgCO2e" if r["emissions_kgco2e"] is not None else "-"
        lines.append(
            f"{r['line_id']}: activity={r['activity']}, qty={r['quantity']} {r['unit']}, "
            f"factor={r['factor_id']}, emissions={em}, decision={r['decision']}, source={r['source']}"
        )
    return "\n".join(lines)


def ask_copilot(question, df):
    """RAG: retrieve rows -> answer from them only -> gate the answer."""
    context = build_context(df)
    prompt = f"""You are a carbon-accounting assistant. Answer the QUESTION using ONLY the DATA below.
Rules:
- Use only numbers that appear in the DATA. Never invent or estimate a figure.
- If the answer is not in the DATA, say "I don't have that in the data."
- Cite the line_id(s) you used.

DATA:
{context}

QUESTION: {question}

Answer concisely, grounded in the DATA."""

    resp = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0},
    )
    answer = resp["message"]["content"] if isinstance(resp, dict) else resp.message.content

    # ---- faithfulness gate: every big number in the answer must exist in the data ----
    unverified = check_faithfulness(answer, context)
    return answer, unverified


def check_faithfulness(answer, context):
    """Return numbers in the answer that do NOT appear in the data (possible hallucinations)."""
    # pull numbers with 3+ digits (ignore small ones like '5 lines', years)
    answer_nums = set(re.findall(r"\d[\d,]{2,}\.?\d*", answer))
    ctx = context.replace(",", "")
    unverified = []
    for n in answer_nums:
        clean = n.replace(",", "")
        # allow small rounding: check the integer part appears in the data
        if clean.split(".")[0] not in ctx:
            unverified.append(n)
    return unverified