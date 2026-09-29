"""The local entry point cannot enable arbitrary cleartext origins."""

import importlib.util
from pathlib import Path

import pytest

SCRIPTS = next(
    p / "scripts"
    for p in Path(__file__).resolve().parents
    if (p / "scripts/aegisforge_ci_local_test.py").exists()
)


@pytest.fixture
def local(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "local_ci_test", SCRIPTS / "aegisforge_ci_local_test.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("port", [8000, 5173])
def test_exact_loopback_only(local, port):
    value = f"http://127.0.0.1:{port}"
    assert local.local_origin(value) == value
    with pytest.raises(local.ci.Failure):
        local.ci.origin(value)


@pytest.mark.parametrize(
    "value",
    [
        "http://example.com",
        "http://localhost:8000",
        "http://127.0.0.1:9000",
        "http://127.0.0.1:8000@evil.test",
        "http://127.0.0.1:8000/path",
        "http://127.0.0.1:8000?secret=value",
        "http://127.0.0.1:8000#fragment",
        "http://127.0.0.1:8000/",
    ],
)
def test_reject_other_http_origins(local, value):
    with pytest.raises(local.ci.Failure):
        local.local_origin(value)


def test_entrypoint_restores_production_validation(local, monkeypatch):
    def run():
        assert local.ci.origin("http://127.0.0.1:8000")
        assert local.ci.origin("https://api.github.com") == "https://api.github.com"
        return 3

    monkeypatch.setattr(local.ci, "main", run)
    assert local.main() == 3
    with pytest.raises(local.ci.Failure):
        local.ci.origin("http://127.0.0.1:8000")
