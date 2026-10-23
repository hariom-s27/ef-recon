"""ADR-004 Part D seal tripwire tests.

Detects unauthorized presence of private names, tokens, and files in tracked paths and source.
The 6 forbidden private tokens appear exclusively in this file.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]

# The forbidden private tokens appear only in this file.
PRIVATE_TOKENS = (
    "_sealed",
    "gold_test_v2",
    "gold_val_v2",
    "val_second_labels",
    "drift_relabel",
    "adjudication_log",
)


def scan_tree_for_violations(root: Path, exempt_file: Path | None = None) -> list[str]:
    """Scans src/ and tests/ under root for forbidden tokens, and checks for private data files."""
    violations: list[str] = []
    exempt_resolved = exempt_file.resolve() if exempt_file is not None else None

    for folder_name in ("src", "tests"):
        folder = root / folder_name
        if not folder.exists():
            continue
        for p in folder.rglob("*"):
            if not p.is_file():
                continue
            if exempt_resolved and p.resolve() == exempt_resolved:
                continue
            if "__pycache__" in p.parts or p.name.endswith(".pyc"):
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for token in PRIVATE_TOKENS:
                if token in content:
                    violations.append(f"PRIVATE_TOKEN:{token}:{p.relative_to(root)}")

    # Check git tracked files if git repository
    git_dir = root / ".git"
    if git_dir.exists():
        try:
            env = dict(os.environ)
            env["GIT_CONFIG_GLOBAL"] = "NUL" if sys.platform == "win32" else "/dev/null"
            env["GIT_CONFIG_SYSTEM"] = "NUL" if sys.platform == "win32" else "/dev/null"
            env["GIT_CONFIG_NOSYSTEM"] = "1"
            res = subprocess.run(
                ["git", "-c", "safe.directory=*", "ls-files", "data/gold_test*", "data/gold_val*"],
                cwd=str(root),
                capture_output=True,
                text=True,
                env=env,
            )
            if res.returncode == 0 and res.stdout.strip():
                for line in res.stdout.strip().splitlines():
                    if line.strip():
                        violations.append(f"TRACKED_PRIVATE_PATH:{line.strip()}")
        except Exception:
            pass

    return violations


def test_no_private_names_in_source_or_tracked_paths():
    """Asserts that no private tokens exist in src/ or tests/ and no private paths are tracked."""
    violations = scan_tree_for_violations(REPO, exempt_file=Path(__file__))
    assert violations == [], f"Found forbidden private tokens or files: {violations}"


def test_tripwire_detects_synthetic_violations(tmp_path):
    """Proves that each violation is detected in a synthetic tree and the one-file exemption works."""
    synthetic_root = tmp_path / "mock_repo"
    src_dir = synthetic_root / "src"
    tests_dir = synthetic_root / "tests"
    src_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)

    # 1. Clean synthetic tree passes
    exempt_test_file = tests_dir / "test_seal_tripwire.py"
    # Exempt file contains all tokens
    exempt_test_file.write_text(" ".join(PRIVATE_TOKENS), encoding="utf-8")
    violations_clean = scan_tree_for_violations(synthetic_root, exempt_file=exempt_test_file)
    assert violations_clean == []

    # 2. Plant each token in synthetic src and prove detection
    for token in PRIVATE_TOKENS:
        planted_file = src_dir / f"planted_{token}.py"
        planted_file.write_text(f"# planted comment with {token}\n", encoding="utf-8")
        violations = scan_tree_for_violations(synthetic_root, exempt_file=exempt_test_file)
        assert any(f"PRIVATE_TOKEN:{token}:" in v for v in violations), f"Failed to detect {token}"
        planted_file.unlink()

    # 3. Non-exempt file in tests/ with token is caught
    other_test = tests_dir / "test_other.py"
    other_test.write_text(f"TOKEN = '{PRIVATE_TOKENS[0]}'\n", encoding="utf-8")
    violations_test = scan_tree_for_violations(synthetic_root, exempt_file=exempt_test_file)
    assert any(f"PRIVATE_TOKEN:{PRIVATE_TOKENS[0]}:" in v for v in violations_test)
    other_test.unlink()

