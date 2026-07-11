"""
paths.py — single source of truth for project paths.
Every script in src/ imports DATA_DIR / OUTPUT_DIR from here instead of
recomputing Path(__file__).parent(.parent) itself, so path bugs can't drift.
"""

from pathlib import Path

BASE_DIR = Path(__file__).parent.parent   # the ef-recon project root (one level up from src/)
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

OUTPUT_DIR.mkdir(exist_ok=True)
