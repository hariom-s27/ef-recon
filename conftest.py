# conftest.py — lets tests import modules from src/
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
