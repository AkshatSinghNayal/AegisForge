"""Opt-in real ZAP tests. Exclusively disposable, internal fixture networks."""

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from test_zap import request

from aegis_api.configuration_schemas import PolicyInput
from aegis_api.db.enums import ScanState
from aegis_api.settings import WorkerSettings
from aegis_api.zap.contracts import Execution
from aegis_api.zap.provider import Interrupted, ZapScannerProvider
from aegis_api.zap.runtime import DockerRuntime, RuntimeFailure

pytestmark = [
    pytest.mark.zap_live,
    pytest.mark.skipif(
        os.environ.get("AEGIS_RUN_ZAP_LIVE") != "1",
        reason="opt-in real isolated ZAP tests",
    ),
]


def docker(*args):
    return subprocess.run(
        ["docker", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture(scope="module")
def fixture_network():
    name = "aegis-phase8-test-" + uuid4().hex[:12]
    fixture = Path(__file__).resolve().parents[3] / "infra/scanner/fixture.py"
    docker("network", "create", "--internal", "--subnet", "172.30.89.0/24", name)
    containers = []
    try:
        for suffix, ip in [("target", "172.30.89.10"), ("canary", "172.30.89.11")]:
            container = f"{name}-{suffix}"
            containers.append(container)
            docker(
                "run",
                "-d",
                "--name",
                container,
                "--network",
                name,
                "--ip",
                ip,
                "--read-only",
                "--tmpfs",
                "/tmp:size=16m",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                "64m",
                "--cpus",
                "0.25",
                "--user",
                "10001:10001",
                "-v",
                f"{fixture}:/fixture.py:ro",
                "-e",
                "OUT_OF_SCOPE_ORIGIN=http://172.30.89.11:8000",
                "python:3.12.14-slim",
                "python",
                "/fixture.py",
            )
        yield name, containers
    finally:
        for container in containers:
            subprocess.run(["docker", "rm", "-f", container], capture_output=True)
        subprocess.run(["docker", "network", "rm", name], capture_output=True)


@pytest.mark.parametrize(
    "mode", ["passive", "active", "openapi", "ajax", "cancel", "timeout", "crash"]
)
def test_live_isolated_scan(fixture_network, tmp_path, mode):
    network, containers = fixture_network
    config = WorkerSettings(
        redis_url="redis://unused",
        profile="test",
        scanner_provider="zap",
        zap_allowlist=["http://172.30.89.10:8000"],
        zap_egress_network=network,
        zap_artifact_root=str(tmp_path),
        zap_artifact_key=Fernet.generate_key().decode(),
    )
    policy = PolicyInput(
        name="Explicit isolated training test",
        mode="active" if mode == "active" else "passive",
        allow_private=True,
        internal_test_declaration="Owned disposable isolated training fixture",
        active_rule_allowlist=["40012"] if mode == "active" else [],
        active_warning_acknowledged=mode == "active",
        spider="ajax" if mode == "ajax" else "traditional",
        max_requests=500,
        rate_limit=20,
    )
    e = Execution(
        organization_id=uuid4(),
        scan_id=uuid4(),
        job_id=uuid4(),
        fence=1,
        target_version=1,
        policy_version=1,
        target_url="http://172.30.89.10:8000/",
        kind="openapi_upload" if mode == "openapi" else "web_url",
        policy=policy,
        includes=["/*"],
        excludes=["/excluded*"],
        methods=["GET", "HEAD"],
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        authorized_until=datetime.now(UTC) + timedelta(minutes=6),
        authorization_digest="a" * 64,
        active_confirmation_digest="b" * 64 if mode == "active" else None,
        spec={
            "openapi": "3.0.3",
            "info": {"title": "Fixture", "version": "1"},
            "paths": {"/": {"get": {"responses": {"200": {"description": "OK"}}}}},
        }
        if mode == "openapi"
        else None,
    )
    runtime = DockerRuntime(config, e.job_id, lambda: None)
    if mode == "ajax":
        original_stats = runtime.stats

        def ajax_stats():
            observed = runtime.call("ajaxSpider", "view", "numberOfResults")
            assert int(observed["numberOfResults"]) > 0, (
                "AJAX browser made no observations"
            )
            return original_stats()

        runtime.stats = ajax_stats
    alive = True
    stages = []

    def emit(stage):
        nonlocal alive
        stages.append(stage)
        if stage == ScanState.SPIDERING:
            if mode == "cancel":
                alive = False
            if mode == "timeout":
                p.wall_deadline = 0
            if mode == "crash":
                docker("kill", runtime.zap)

    p = ZapScannerProvider(config, e, runtime, lambda: alive, emit)
    runtime.check = p.check
    if mode in {"cancel", "timeout", "crash"}:
        with pytest.raises((Interrupted, TimeoutError, RuntimeFailure)):
            p.execute(request(e))
    else:
        result = p.execute(request(e))
        assert result.status == "ok"
        data = Fernet(config.zap_artifact_key.get_secret_value()).decrypt(
            (tmp_path / result.artifact.restricted_object_key).read_bytes()
        )
        raw = json.loads(data)
        assert raw["alerts"]  # Fixture intentionally lacks security headers.
        assert (
            "synthetic-fixture-secret"
            not in (tmp_path / result.artifact.redacted_object_key).read_text()
        )
        if mode == "active":
            assert ScanState.ACTIVE_SCANNING in stages
    assert not docker("ps", "-aq", "--filter", f"name={runtime.prefix}")
    assert not docker("network", "ls", "-q", "--filter", f"name={runtime.prefix}")
    # The canary shares the target network but is never an authorized destination.
    count = docker(
        "exec",
        containers[1],
        "python",
        "-c",
        "from pathlib import Path; print(Path('/tmp/requests').exists())",
    )
    assert count == "False", "An unauthorized target received traffic"


def test_live_network_routes_and_lost_worker_lease(fixture_network):
    import time

    from aegis_api.zap.gateway import Scope

    network, containers = fixture_network
    config = WorkerSettings(redis_url="redis://unused", zap_egress_network=network)
    runtime = DockerRuntime(config, uuid4(), lambda: None)
    scope = Scope(
        target_url="http://172.30.89.10:8000/",
        address="172.30.89.10",
        includes=["/*"],
        excludes=[],
        methods=["GET"],
        max_requests=10,
        rate=10,
        seconds=60,
        require_lease=True,
    )
    try:
        runtime.start(scope, "synthetic-management-key")
        # Direct target/canary access must have no route from the ZAP namespace.
        code = """
import socket
for host in ('172.30.89.10', '172.30.89.11'):
    try:
        connection = socket.create_connection((host, 8000), timeout=1)
    except OSError:
        continue
    connection.close()
    raise SystemExit(1)
print('direct routes blocked')
"""
        assert (
            runtime.command(["exec", runtime.zap, "python3", "-c", code])
            == "direct routes blocked"
        )
        code = """
import http.client,sys
connection=http.client.HTTPConnection(sys.argv[1],8888,timeout=3)
connection.request('GET','http://172.30.89.11:8000/forbidden')
assert connection.getresponse().status==403
print('foreign proxy target blocked')
"""
        assert (
            runtime.command(
                ["exec", runtime.zap, "python3", "-c", code, runtime.gateway_ip]
            )
            == "foreign proxy target blocked"
        )
        runtime.stop.set()  # Models abrupt worker heartbeat loss independently of ZAP.
        time.sleep(12)
        code = """
import socket,sys
try:
    socket.create_connection((sys.argv[1],8888),timeout=2)
except OSError:
    print('egress revoked')
else:
    raise SystemExit(1)
"""
        assert (
            runtime.command(
                ["exec", runtime.zap, "python3", "-c", code, runtime.gateway_ip]
            )
            == "egress revoked"
        )
        assert (
            docker(
                "exec",
                containers[1],
                "python",
                "-c",
                "from pathlib import Path; print(Path('/tmp/requests').exists())",
            )
            == "False"
        )
    finally:
        runtime.close()
