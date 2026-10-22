"""
paths.py — single source of truth for project paths.
Every script in src/ imports DATA_DIR / OUTPUT_DIR from here instead of
recomputing Path(__file__).parent(.parent) itself, so path bugs can't drift.
"""

from pathlib import Path

BASE_DIR = Path(__file__).parent.parent   # the ef-recon project root (one level up from src/)
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"


def ensure_output_dir(path=None):
    """Create the output folder just before a write (never at import). Default: OUTPUT_DIR."""
    path = OUTPUT_DIR if path is None else path
    path.mkdir(parents=True, exist_ok=True)
    return path
