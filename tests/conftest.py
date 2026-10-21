"""Test isolation: no test may touch output/factors_cache.pkl, and no test may reach Ollama."""
import builtins
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import match
from paths import OUTPUT_DIR


@pytest.fixture(autouse=True)
def _no_cache_no_network(monkeypatch):
    """Every test: pickle (as seen by match) and opens under output/ raise; Ollama is offline.
    Returns the list of attempted cache touches (empty = the guard never fired)."""
    touches = []

    def _guard(*args, **kwargs):
        touches.append(args[:1])
        raise AssertionError("test touched the factor cache")

    def _guarded_open(file, *args, **kwargs):
        if isinstance(file, (str, Path)):
            p = Path(file).resolve()
            if p == OUTPUT_DIR.resolve() or OUTPUT_DIR.resolve() in p.parents:
                _guard(file)
        return builtins.open(file, *args, **kwargs)

    def _offline(**kwargs):
        raise ConnectionError("no network in tests")

    monkeypatch.setattr(match, "pickle", SimpleNamespace(load=_guard, dump=_guard))
    monkeypatch.setattr(match, "open", _guarded_open, raising=False)
    monkeypatch.setattr(match.ollama, "embeddings", _offline)
    return touches


@pytest.fixture(scope="session")
def factors():
    return match.read_factor_rows()


@pytest.fixture
def api_client(monkeypatch):
    """Import api with load_factors swapped for the pure reader, so import never hits the cache."""
    from fastapi.testclient import TestClient

    sys.modules.pop("api", None)
    monkeypatch.setattr(match, "load_factors", match.read_factor_rows)
    api = importlib.import_module("api")
    return TestClient(api.app)
