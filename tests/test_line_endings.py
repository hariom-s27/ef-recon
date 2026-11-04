"""P05d tripwires: every checkout must have LF line endings, byte-identical to git."""
import hashlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC_SHA256 = "76297c7ad1ccb20d710db99cf3955ba893372c7915b89c91b0192cc51c09c780"
HINT = "CRLF on disk: this checkout converted line endings; re-checkout with LF (see P05d)"


def test_gitattributes_forces_lf():
    path = REPO / ".gitattributes"
    assert path.is_file(), ".gitattributes missing at repo root (see P05d)"
    lines = {line.strip() for line in path.read_text(encoding="utf-8").splitlines()}
    assert "* text=auto eol=lf" in lines
    assert "*.pdf binary" in lines


def test_frozen_text_files_have_no_crlf():
    adr = sorted((REPO / "docs" / "adr").glob("ADR-004*.md"))
    assert adr, "no docs/adr/ADR-004*.md found"
    frozen = [REPO / "data" / "gold_spec_v2.md", REPO / "data" / "gold_dev_v2.csv", *adr]
    bad = [p.relative_to(REPO).as_posix() for p in frozen if b"\r\n" in p.read_bytes()]
    assert not bad, f"{bad}: {HINT}"


def test_frozen_spec_hash_on_disk():
    digest = hashlib.sha256((REPO / "data" / "gold_spec_v2.md").read_bytes()).hexdigest()
    assert digest == SPEC_SHA256, f"data/gold_spec_v2.md sha256 {digest}: {HINT}"
