"""
scorecard_view.py — read the committed scorecards (output/scorecards/scorecard-*.json)
for the dashboard. Works for schema 1 and 2 (only `inputs` differs between them).
Kept free of heavy imports: the M1/M2 keys are pinned against run_scorecard by a test.
"""

import json
import re
from pathlib import Path

M1 = "determination_accuracy_gold_qty_unit_given__rule_resolvable"
M2 = "determination_accuracy_gold_qty_unit_given__all_rows"

_DATED = re.compile(r"^scorecard-(\d{4}-\d{2}-\d{2})")


def latest_scorecard(directory):
    """The newest scorecard-*.json: by the date in the filename, then by generated_utc. None if none."""
    best_key, best = None, None
    for path in Path(directory).glob("scorecard-*.json"):
        m = _DATED.match(path.name)
        if not m:
            continue
        try:
            sc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue                      # unreadable file -> skip it, keep the dashboard up
        key = (m.group(1), sc.get("generated_utc", ""))
        if best_key is None or key > best_key:
            best_key, best = key, sc
    return best


def format_metric(m):
    """'37/38 (97.4%, 95% CI 86.5–99.5%)'; n = 0 -> '0/0 (n/a)'."""
    if not m or not m.get("n"):
        return "0/0 (n/a)"
    text = f"{m['k']}/{m['n']} ({m['p'] * 100:.1f}%"
    ci = m.get("ci95_wilson")
    if ci:
        text += f", 95% CI {ci[0] * 100:.1f}–{ci[1] * 100:.1f}%"
    return text + ")"
