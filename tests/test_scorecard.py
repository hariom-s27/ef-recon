"""P03: rules-only scorecard (ADR-001) — no LLM, no judge, never overwrites, import touches no file.
Every output goes to tmp_path; extract_with_llm and judge_one are tripwired to raise."""
import builtins
import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from statsmodels.stats.proportion import proportion_confint

import run_scorecard as rs
from paths import OUTPUT_DIR

REQUIRED_FIELDS = {"schema", "protocol", "label", "commit", "generated_utc", "python", "mode",
                   "inputs", "metrics", "needs_llm_ids", "per_row"}
METRIC_NAMES = {"determination_accuracy_gold_qty_unit_given__rule_resolvable",
                "determination_accuracy_gold_qty_unit_given__all_rows",
                "precision_at_1_accepted", "coverage_should_match",
                "escalation_accuracy", "refusal_accuracy"}
FAKE_SHA = "0123456789abcdef0123456789abcdef01234567"


def _boom(*args, **kwargs):
    raise AssertionError("LLM / judge reached in rules-only mode")


@pytest.fixture(autouse=True)
def _no_llm_no_judge(monkeypatch):
    monkeypatch.setattr(rs, "extract_with_llm", _boom)
    monkeypatch.setattr(rs, "judge_one", _boom)
    monkeypatch.setattr(rs, "load_factors", _boom)


def _gold(line_id, desc, gold, qty="", unit=""):
    return {"line_id": line_id, "raw_description": desc, "correct_factor_id": gold,
            "canonical_qty": qty, "canonical_unit": unit}


def _meta():
    return {"label": "test", "generated_utc": "2026-10-22T00:00:00Z", "python": "3.12.10",
            "inputs": {"gold": {"path": "g", "git_blob": "0" * 40, "sha256": "0" * 64}}}


# ---------- run_engine(allow_llm=False) ----------
@pytest.mark.parametrize("desc, qty, unit, expected", [
    pytest.param("Grid electricity 33000 kWh Unit-2", 33000, "kWh", ("accept", "EF-IN-ELEC-GRID"),
                 id="electricity-accept"),
    pytest.param("Furnace oil 4200 L for boiler", None, "litre", ("escalate", None), id="furnace-escalate"),
    pytest.param("Printer cartridges & stationery", None, "lot", ("needs_llm", None), id="no-alias-needs-llm"),
])
def test_run_engine_rules_only(factors, desc, qty, unit, expected):
    decision, fac = rs.run_engine(desc, factors, qty, unit, allow_llm=False)
    assert (decision, fac["factor_id"] if fac else None) == expected


# ---------- score_rows ----------
SYNTH = [
    _gold("S1", "accept-right", "EF-A"),
    _gold("S2", "accept-wrong", "EF-A"),
    _gold("S3", "escalate", "ESCALATE"),
    _gold("S4", "refuse", "NO_FACTOR"),
    _gold("S5", "needs-llm", "EF-A"),
]
ENGINE = {"accept-right": ("accept", {"factor_id": "EF-A"}),
          "accept-wrong": ("accept", {"factor_id": "EF-B"}),
          "escalate": ("escalate", None),
          "refuse": ("refuse", None),
          "needs-llm": ("needs_llm", None)}


def test_score_rows_synthetic(monkeypatch):
    monkeypatch.setattr(rs, "run_engine", lambda desc, *a, **kw: ENGINE[desc])

    result = rs.score_rows(SYNTH, factors=[], allow_llm=False)
    m = result["metrics"]

    expected_kn = {
        "determination_accuracy_gold_qty_unit_given__rule_resolvable": (3, 4),
        "determination_accuracy_gold_qty_unit_given__all_rows": (3, 5),
        "precision_at_1_accepted": (1, 2),
        "coverage_should_match": (2, 2),
        "escalation_accuracy": (1, 1),
        "refusal_accuracy": (1, 1),
    }
    assert set(m) == METRIC_NAMES
    for name, (k, n) in expected_kn.items():
        assert (m[name]["k"], m[name]["n"]) == (k, n), name
        assert m[name]["p"] == k / n
        assert m[name]["ci95_wilson"] == list(proportion_confint(k, n, method="wilson")), name
    assert result["needs_llm_ids"] == ["S5"]
    assert [r["outcome"] for r in result["per_row"]] == ["correct", "wrong", "correct", "correct", "needs_llm"]


def test_metric_n_zero_is_null():
    assert rs.metric(0, 0) == {"k": 0, "n": 0, "p": None, "ci95_wilson": None}


# ---------- write_scorecard ----------
def _result():
    return {"metrics": {name: rs.metric(1, 2) for name in rs.METRIC_NAMES},
            "needs_llm_ids": [], "per_row": []}


def test_write_scorecard_fields(tmp_path):
    path = rs.write_scorecard(_result(), tmp_path, FAKE_SHA, _meta())

    assert path.name == "scorecard-2026-10-22-0123456.json"
    raw = path.read_bytes()
    assert b"\r\n" not in raw and raw.endswith(b"\n")
    doc = json.loads(raw.decode("utf-8"))
    assert set(doc) == REQUIRED_FIELDS
    assert set(doc["metrics"]) == METRIC_NAMES
    assert doc["schema"] == "efrecon-scorecard/2"
    assert doc["protocol"] == "ADR-001"
    assert doc["mode"] == "rules-only (no LLM, no judge)"
    assert doc["commit"] == FAKE_SHA


def test_write_scorecard_refuses_existing(tmp_path):
    existing = tmp_path / "scorecard-2026-10-22-0123456.json"
    existing.write_bytes(b"keep")

    with pytest.raises(FileExistsError):
        rs.write_scorecard(_result(), tmp_path, FAKE_SHA, _meta())

    assert existing.read_bytes() == b"keep"
    assert [p.name for p in tmp_path.iterdir()] == [existing.name]


# ---------- import has no side effects ----------
def test_import_touches_no_file(monkeypatch):
    calls = []
    real_open, real_mkdir = builtins.open, Path.mkdir

    def _open(file, *args, **kwargs):
        calls.append(("open", file))
        return real_open(file, *args, **kwargs)

    def _mkdir(self, *args, **kwargs):
        calls.append(("mkdir", self))
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "run_scorecard", raising=False)
    monkeypatch.setattr(builtins, "open", _open)
    monkeypatch.setattr(Path, "mkdir", _mkdir)

    importlib.import_module("run_scorecard")

    assert calls == []


# ---------- main --no-llm ----------
def _protected_bytes():
    return {p: p.read_bytes() for p in (OUTPUT_DIR / "scorecard.json", OUTPUT_DIR / "judge_cache.json")
            if p.exists()}


def test_main_no_llm_writes_one_new_file(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "_git_state", lambda: (FAKE_SHA, True))
    before = _protected_bytes()

    path = rs.main(["--no-llm", "--out-dir", str(tmp_path)])

    assert [p.name for p in tmp_path.iterdir()] == [path.name]
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert set(doc) == REQUIRED_FIELDS
    assert len(doc["per_row"]) == 45
    assert _protected_bytes() == before


def test_main_no_llm_refuses_dirty_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "_git_state", lambda: (FAKE_SHA, False))

    with pytest.raises(SystemExit):
        rs.main(["--no-llm", "--out-dir", str(tmp_path / "out")])

    assert not (tmp_path / "out").exists()


# ---------- schema 2: inputs hashed from the committed blob (ADR-001 amendment) ----------
def test_inputs_use_committed_blob(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "_git_state", lambda: (FAKE_SHA, True))
    monkeypatch.setattr(rs, "_git_object", lambda rel_path, repo=None: ("b" * 40, b"fixed\n"))

    path = rs.main(["--no-llm", "--out-dir", str(tmp_path)])

    doc = json.loads(path.read_text(encoding="utf-8"))
    sha = hashlib.sha256(b"fixed\n").hexdigest()
    assert doc["schema"] == "efrecon-scorecard/2"
    assert doc["inputs"] == {
        "gold": {"path": "data/gold_labels.csv", "git_blob": "b" * 40, "sha256": sha},
        "factors": {"path": "data/emission_factors.csv", "git_blob": "b" * 40, "sha256": sha},
        "requirements_lock": {"path": "requirements-lock.txt", "git_blob": "b" * 40, "sha256": sha},
    }


def test_input_hash_ignores_working_tree_eol(tmp_path, monkeypatch):
    """Same committed content, LF or CRLF on disk -> identical inputs entry (throwaway repo in tmp_path)."""
    empty_cfg = tmp_path / "empty.gitconfig"
    empty_cfg.write_bytes(b"")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_cfg))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        return subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "user.name=t",
                               "-c", "user.email=t@example.invalid", *args],
                              cwd=repo, capture_output=True, check=True).stdout

    lf = b"line_id,value\nA,1\nB,2\n"
    (repo / "a.csv").write_bytes(lf)
    git("init", "-q")
    git("add", "a.csv")
    git("commit", "-q", "-m", "lf")

    entry_lf = rs._input_entry("a.csv", repo=repo)
    (repo / "a.csv").write_bytes(lf.replace(b"\n", b"\r\n"))
    entry_crlf = rs._input_entry("a.csv", repo=repo)

    assert (repo / "a.csv").read_bytes() != lf                 # disk bytes really differ
    assert entry_lf == entry_crlf
    assert entry_lf == {"path": "a.csv",
                        "git_blob": git("rev-parse", "HEAD:a.csv").decode("ascii").strip(),
                        "sha256": hashlib.sha256(lf).hexdigest()}
