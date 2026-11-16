"""Tripwire and invariant tests for agent rules, tool permissions and hooks."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

import pytest

REPO = Path(__file__).resolve().parents[1]


def test_agents_md_present_small_lf():
    path = REPO / "AGENTS.md"
    assert path.exists()
    raw = path.read_bytes()
    assert len(raw) < 12000
    raw.decode("utf-8")
    assert b"\r\n" not in raw


def test_claude_md_imports_agents_md():
    path = REPO / "CLAUDE.md"
    assert path.exists()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert "@AGENTS.md" in lines


def test_claude_settings_guards():
    path = REPO / ".claude" / "settings.json"
    assert path.exists()
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    perms = data.get("permissions", {})
    assert perms.get("blockReadsOutsideWorkingDirectories") is True
    deny = perms.get("deny", [])
    assert "Bash(git commit *)" in deny
    assert "Bash(git push *)" in deny
    assert "Edit(./data/gold_spec_v2.md)" in deny
    attribution = data.get("attribution", {})
    assert attribution.get("commit") == ""


def test_codex_config_has_no_sandbox_mode():
    path = REPO / ".codex" / "config.toml"
    assert path.exists()
    with path.open("rb") as f:
        data = tomllib.load(f)
    assert data.get("approval_policy") == "on-request"

    def _walk_check_no_sandbox(obj):
        if isinstance(obj, dict):
            assert "sandbox_mode" not in obj
            for val in obj.values():
                _walk_check_no_sandbox(val)
        elif isinstance(obj, list):
            for item in obj:
                _walk_check_no_sandbox(item)

    _walk_check_no_sandbox(data)


def test_codex_rules_forbid_git_writes():
    path = REPO / ".codex" / "rules" / "efrecon.rules"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert 'decision = "forbidden"' in text
    assert '"commit"' in text
    assert '"push"' in text


def test_audit_folder_ignored_and_untracked():
    gitignore = REPO / ".gitignore"
    assert gitignore.exists()
    lines = gitignore.read_text(encoding="utf-8").splitlines()
    assert "_audit/" in lines

    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = "NUL" if sys.platform == "win32" else "/dev/null"
    env["GIT_CONFIG_SYSTEM"] = "NUL" if sys.platform == "win32" else "/dev/null"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    res = subprocess.run(
        ["git", "-c", "safe.directory=*", "ls-files", "_audit"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode == 0
    assert res.stdout.strip() == ""


@pytest.mark.parametrize(
    "msg, expect_zero",
    [
        ("Fix typo\n", True),
        ("Fix\n\nCo-authored-by: X <x@y.z>\n", False),
        ("Fix\n\nAssisted-by: tool\n", False),
        ("Fix\n\nGenerated with some tool\n", False),
        ("Fix\n\nMade-with: tool\n", False),
        ("Fix\n\n# Co-authored-by: ignored comment\n", True),
    ],
)
def test_commit_msg_hook(tmp_path, msg, expect_zero):
    if shutil.which("sh") is None:
        pytest.skip("sh not available")
    msg_file = tmp_path / "COMMIT_EDITMSG"
    msg_file.write_text(msg, encoding="utf-8")
    res = subprocess.run(
        ["sh", ".githooks/commit-msg", str(msg_file)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    if expect_zero:
        assert res.returncode == 0, f"Expected 0 but got {res.returncode}: {res.stderr}"
    else:
        assert res.returncode != 0, f"Expected non-zero but got 0: {res.stdout}"
