"""Execution-boundary regressions confirmed during strict Phase 8 review."""

import json
import stat

import pytest
from cryptography.fernet import Fernet

from aegis_api.zap.artifacts import LocalArtifactStore
from aegis_api.zap.gateway import Budget, Scope


def scope():
    return Scope(
        target_url="http://fixture.test/",
        address="172.30.88.10",
        includes=["/*"],
        excludes=["/private*"],
        methods=["GET"],
        max_requests=10,
        rate=1,
        seconds=30,
    )


@pytest.mark.parametrize("path", ["//private", "/%2fprivate", "/public/..;/private"])
def test_ambiguous_server_normalized_paths_are_denied(path):
    assert not scope().permits("http://fixture.test" + path, "GET")


@pytest.mark.parametrize("expiration", ["lease", "deadline"])
def test_queued_request_rechecks_authorization(monkeypatch, expiration):
    budget = Budget(scope())
    alive = True
    monkeypatch.setattr(budget, "lease_current", lambda: alive)

    def expire(_):
        nonlocal alive
        if expiration == "lease":
            alive = False
        else:
            budget.until = 0

    monkeypatch.setattr("aegis_api.zap.gateway.time.sleep", expire)
    assert not budget.admit("http://fixture.test/", "GET")
    assert budget.exhausted


def test_every_artifact_directory_is_private(tmp_path):
    store = LocalArtifactStore(tmp_path / "objects", Fernet.generate_key().decode())
    store.write("organization/scan/artifact", b"encrypted")
    for suffix in ["", "organization", "organization/scan"]:
        assert stat.S_IMODE((store.root / suffix).stat().st_mode) == 0o700


def test_gateway_rejected_framing_persists_failure(tmp_path, monkeypatch):
    import http.client
    import threading
    from http.server import ThreadingHTTPServer

    from aegis_api.zap.gateway import certificate, handler

    monkeypatch.chdir(tmp_path)
    stats = tmp_path / "stats.json"
    monkeypatch.setattr("aegis_api.zap.gateway.STATS_PATH", stats)
    budget = Budget(scope())
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        handler(scope(), budget, certificate("fixture.test", tmp_path)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
        connection.request(
            "GET", "http://fixture.test/", headers={"Upgrade": "websocket"}
        )
        assert connection.getresponse().status == 400
        connection.close()
        server.shutdown()
        assert json.loads(stats.read_text())["failed"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.mark.parametrize(
    "credential,leaked",
    [
        ("Bearer opaque-value-123", "opaque-value-123"),
        ("Basic dXNlcjpwYXNzLXZhbHVl", "pass-value"),
    ],
)
def test_redaction_removes_credential_components(credential, leaked):
    from aegis_api.zap.artifacts import redact

    assert leaked not in json.dumps(
        redact({"alert": "Observation " + leaked}, [credential], [])
    )


@pytest.mark.parametrize("expiration", ["lease", "deadline"])
def test_slow_body_cannot_send_after_revocation(tmp_path, monkeypatch, expiration):
    import socket
    import threading
    import time
    from http.server import ThreadingHTTPServer

    from aegis_api.zap.gateway import certificate, handler

    budget = Budget(scope())
    alive = True
    monkeypatch.setattr(budget, "lease_current", lambda: alive)
    monkeypatch.setattr("aegis_api.zap.gateway.STATS_PATH", tmp_path / "stats.json")
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        handler(scope(), budget, certificate("fixture.test", tmp_path)),
    )
    connect = socket.create_connection

    def only_gateway(address, *args, **kwargs):
        assert address == ("127.0.0.1", server.server_port), (
            "Unauthorized upstream contact"
        )
        return connect(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", only_gateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.create_connection(
            ("127.0.0.1", server.server_port), timeout=3
        ) as client:
            client.sendall(
                b"GET http://fixture.test/ HTTP/1.0\r\nContent-Length: 1\r\n\r\n"
            )
            until = time.monotonic() + 2
            while budget.count == 0 and time.monotonic() < until:
                time.sleep(0.01)
            assert budget.count == 1
            if expiration == "lease":
                alive = False
            else:
                budget.until = 0
            client.sendall(b"x")
            assert b"403" in client.recv(1024)
        assert budget.exhausted
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
