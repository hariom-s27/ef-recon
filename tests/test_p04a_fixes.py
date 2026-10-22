"""P04a A2: no import-time mkdir in paths.py; the dashboard reads the committed scorecards."""
import ast
import json

import paths
import run_scorecard
from scorecard_view import M1, M2, latest_scorecard, format_metric


# ---------- (a) paths.py ----------
def test_paths_has_no_module_level_call_statements():
    tree = ast.parse((paths.BASE_DIR / "src" / "paths.py").read_text(encoding="utf-8"))
    calls = [ast.unparse(node) for node in tree.body
             if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)]
    assert calls == []


def test_ensure_output_dir_creates_the_given_dir(tmp_path, monkeypatch):
    target = tmp_path / "a" / "out"
    assert paths.ensure_output_dir(target) == target and target.is_dir()

    default = tmp_path / "default_out"
    monkeypatch.setattr(paths, "OUTPUT_DIR", default)
    assert paths.ensure_output_dir() == default and default.is_dir()


# ---------- (b) latest_scorecard ----------
METRIC = {"k": 37, "n": 38, "p": 37 / 38, "ci95_wilson": [0.865, 0.995]}


def _card(schema, generated, label):
    inputs = ({"factors": {"path": "data/emission_factors.csv", "sha256": "a" * 64}}
              if schema == 1 else
              {"factors": {"path": "data/emission_factors.csv", "git_blob": "b" * 40, "sha256": "a" * 64}})
    return {"schema": f"efrecon-scorecard/{schema}", "generated_utc": generated, "label": label,
            "inputs": inputs, "metrics": {M1: METRIC, M2: {**METRIC, "n": 45, "p": 37 / 45}}}


def _write(directory, name, card):
    (directory / name).write_text(json.dumps(card), encoding="utf-8")


def test_latest_scorecard_none_when_empty(tmp_path):
    assert latest_scorecard(tmp_path) is None
    assert latest_scorecard(tmp_path / "missing") is None


def test_latest_scorecard_picks_newest_across_schemas(tmp_path):
    _write(tmp_path, "scorecard-2026-10-22-6ddea50.json", _card(1, "2026-10-22T04:24:50Z", "old"))
    _write(tmp_path, "scorecard-2026-10-22-abc1234.json", _card(2, "2026-10-22T09:00:00Z", "same-day-later"))
    _write(tmp_path, "scorecard-2026-10-21-fffffff.json", _card(2, "2026-10-23T00:00:00Z", "older-date"))
    _write(tmp_path, "notes.json", _card(2, "2099-01-01T00:00:00Z", "ignored"))

    sc = latest_scorecard(tmp_path)
    assert sc["label"] == "same-day-later" and sc["schema"] == "efrecon-scorecard/2"

    (tmp_path / "scorecard-2026-10-22-abc1234.json").unlink()
    sc = latest_scorecard(tmp_path)
    assert sc["label"] == "old" and sc["schema"] == "efrecon-scorecard/1"


def test_format_metric_and_m1_m2_keys():
    assert format_metric(METRIC) == "37/38 (97.4%, 95% CI 86.5–99.5%)"
    assert format_metric({"k": 0, "n": 0, "p": None, "ci95_wilson": None}) == "0/0 (n/a)"
    assert (M1, M2) == (run_scorecard.M1, run_scorecard.M2)
