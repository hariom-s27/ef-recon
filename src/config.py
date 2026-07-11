"""
config.py — single source of truth for all EF-Recon settings.
Change a value here and it applies everywhere. No hunting through files.
"""
from paths import OUTPUT_DIR

# ---- matching thresholds (0..1) ----
ACCEPT_SCORE   = 0.60      # >= this -> auto-accept the match
ESCALATE_SCORE = 0.45      # between escalate & accept -> human review; below -> refuse

# ---- models (local Ollama) ----
LLM_MODEL   = "qwen3:1.7b"        # for text extraction
EMBED_MODEL = "nomic-embed-text"  # for semantic matching

# ---- calibration ----
CALIBRATION_BINS = 5

# ---- logging ----
LOG_LEVEL = "INFO"                       # DEBUG shows everything; INFO = normal
LOG_FILE  = OUTPUT_DIR / "efrecon.log"   # permanent log record lives here