"""P03 A2: uploads never land in data/; dead thresholds are documented, not changed;
requirements.txt header is truthful and its pins match the lock."""
import hashlib

import pytest

import config
import match
from paths import BASE_DIR, DATA_DIR
from upload import save_upload


def _data_hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(DATA_DIR.iterdir()) if p.is_file()}


# ---------- (a) save_upload ----------
def test_save_upload_never_writes_data(tmp_path):
    before = _data_hashes()

    path = save_upload("gold_labels.csv", b"evil", tmp_path)
    assert path == (tmp_path / "gold_labels.csv").resolve()
    assert path.read_bytes() == b"evil"

    with pytest.raises(ValueError):
        save_upload("gold_labels.csv", b"evil", DATA_DIR)
    with pytest.raises(ValueError):
        save_upload("x.csv", b"evil", DATA_DIR / "sub")

    assert _data_hashes() == before
    assert not (DATA_DIR / "sub").exists()


@pytest.mark.parametrize("name", ["../x", "a/../x", "..\\x", "/etc/x", "C:\\x", "C:x", "", "sub/"])
def test_save_upload_refuses_bad_names(tmp_path, name):
    with pytest.raises(ValueError):
        save_upload(name, b"x", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_save_upload_uses_basename_only(tmp_path):
    path = save_upload("sub/x.csv", b"ok", tmp_path)
    assert path.name == "x.csv" and path.parent == tmp_path.resolve()


def test_save_upload_refuses_overwrite(tmp_path):
    (tmp_path / "x.csv").write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        save_upload("x.csv", b"new", tmp_path)
    assert (tmp_path / "x.csv").read_bytes() == b"keep"


# ---------- (b) thresholds documented, unchanged ----------
def test_thresholds_unchanged_and_docstring_truthful():
    assert (config.ACCEPT_SCORE, config.ESCALATE_SCORE) == (0.60, 0.45)
    assert ("5. activity unknown -> ESCALATE via match_line; semantic_match may only SUGGEST "
            "candidates (no threshold decides)") in match.__doc__


# ---------- (c) requirements.txt header ----------
HEADER = ('# Direct dependencies, pinned on Python 3.12.10 (2026-10-22). '
          'Exact environment: requirements-lock.txt. Regenerate: see README "Run it".')


def test_requirements_header_and_pins():
    raw = (BASE_DIR / "requirements.txt").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    lines = raw.decode("utf-8").splitlines()
    assert lines[0] == HEADER
    assert "passed" not in raw.decode("utf-8")

    pins = [ln for ln in lines if "==" in ln and not ln.startswith("#")]
    lock = (BASE_DIR / "requirements-lock.txt").read_text(encoding="utf-8").splitlines()
    assert len(pins) == 15
    assert all(p in lock for p in pins)
