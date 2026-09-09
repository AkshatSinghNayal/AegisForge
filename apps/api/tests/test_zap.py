"""Provider/security contracts. Fake transport never makes a network connection."""

import hashlib
import json
import socket
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr, ValidationError

from aegis_api.configuration_schemas import PolicyInput
from aegis_api.db.enums import ScanMode, ScanState
from aegis_api.scanner import MockScannerProvider, ScannerProvider, StageRequest
from aegis_api.settings import WorkerSettings
from aegis_api.zap.artifacts import LocalArtifactStore, redact
from aegis_api.zap.contracts import Credential, Execution
from aegis_api.zap.gateway import Budget, Scope
from aegis_api.zap.provider import Interrupted, ZapScannerProvider, context_pattern
from aegis_api.zap.runtime import DockerRuntime, RuntimeFailure


@pytest.fixture
def execution():
    return Execution(
        organization_id=uuid4(),
        scan_id=uuid4(),
        job_id=uuid4(),
        fence=1,
        target_version=1,
        policy_version=1,
        target_url="http://172.30.88.10:8000/",
        kind="web_url",
        policy=PolicyInput(
            name="Local authorized training",
            mode="passive",
            allow_private=True,
            internal_test_declaration="Isolated local training fixture owned by us",
        ),
        includes=["/*"],
        excludes=["/excluded*"],
        methods=["GET", "HEAD"],
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        authorized_until=datetime.now(UTC) + timedelta(hours=1),
        authorization_digest="a" * 64,
    )


@pytest.fixture
def config(tmp_path):
    return WorkerSettings(
        redis_url="redis://unused:6379",
        profile="test",
        scanner_provider="zap",
        zap_allowlist=["http://172.30.88.10:8000"],
        zap_artifact_root=str(tmp_path),
        zap_artifact_key=Fernet.generate_key().decode(),
        zap_secret_key=Fernet.generate_key().decode(),
    )


class FakeRuntime:
    def __init__(self, fail=None):
        self.calls = []
        self.started = False
        self.closed = False
        self.fail = fail
        self.scope = None
        self.upload = None

    def resolve(self, host, port, allow_private):
        return ["172.30.88.10"]

    def start(self, scope, api_key):
        self.started = True
        self.scope = scope
        if self.fail == "start":
            raise RuntimeFailure("crash")

    def call(self, component, kind, operation, **params):
        self.calls.append((component, kind, operation, params))
        if operation == self.fail:
            raise RuntimeFailure("crash")
        if operation == "numberOfResults":
            return {"numberOfResults": "2"}
        if operation == "scanners":
            return {"scanners": [{"id": "40012"}]}
        if operation == "importFile":
            return {"importFile": []}
        if operation == "version":
            return {"version": "2.17.0"}
        if operation == "newContext":
            return {"contextId": "1"}
        if operation == "scan" and component != "ajaxSpider":
            return {"scan": "0"}
        if operation == "status":
            return {"status": "stopped" if component == "ajaxSpider" else "100"}
        if operation == "recordsToScan":
            return {"recordsToScan": "0"}
        if operation == "alerts":
            return {
                "alerts": [
                    {
                        "pluginId": "10020",
                        "alert": "Missing header",
                        "risk": "Medium",
                        "confidence": "High",
                        "url": "http://172.30.88.10:8000/?token=private",
                        "method": "GET",
                        "messageId": "1",
                        "param": "token",
                        "attack": "payload",
                        "evidence": "session=private",
                        "cweid": "16",
                        "wascid": "15",
                        "reference": "https://example.invalid/reference",
                    }
                ]
            }
        if operation == "message":
            return {
                "message": {
                    "requestHeader": "Authorization: Bearer private",
                    "requestBody": "password=private",
                    "responseHeader": "Set-Cookie: session=private",
                    "responseBody": "sensitive body",
                }
            }
        return {"Result": "OK"}

    def stats(self):
        return {"count": 3, "denied": 1, "exhausted": False, "failed": False}

    def configure_proxy(self):
        pass

    def file(self, path, content):
        self.upload = (path, json.loads(content))

    def close(self):
        self.closed = True


def request(e):
    return StageRequest(
        scan_id=e.scan_id,
        job_id=e.job_id,
        fence=e.fence,
        stage=ScanState.VALIDATING_TARGET,
        demo=False,
    )


def provider(monkeypatch, config, execution, runtime, **kw):
    # Any accidental network call is a hard failure in these contracts.
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *a, **k: pytest.fail("Unexpected network contact"),
    )
    return ZapScannerProvider(
        config,
        execution,
        runtime,
        kw.get("alive", lambda: True),
        kw.get("emit", lambda stage: None),
        kw.get("sleeper", lambda n: None),
    )


def test_provider_contract_and_raw_provenance(monkeypatch, config, execution, tmp_path):
    runtime = FakeRuntime()
    stages = []
    p: ScannerProvider = provider(
        monkeypatch, config, execution, runtime, emit=stages.append
    )
    result = p.execute(request(execution))
    assert result.status == "ok" and result.fixture_version == "zap-v1"
    assert runtime.closed and runtime.scope.address == "172.30.88.10"
    assert not any(c[0] == "ascan" for c in runtime.calls)
    assert stages[-1] == ScanState.COLLECTING_RESULTS
    receipt = result.artifact
    raw = Fernet(config.zap_artifact_key.get_secret_value()).decrypt(
        (tmp_path / receipt.restricted_object_key).read_bytes()
    )
    assert hashlib.sha256(raw).hexdigest() == receipt.content_hash
    doc = json.loads(raw)
    assert doc["alerts"][0]["attack"] == "payload"
    assert doc["alerts"][0]["cweid"] == "16"
    assert doc["messages"]["1"]["responseBody"] == "sensitive body"
    clean = (tmp_path / receipt.redacted_object_key).read_text()
    assert "private" not in clean and "sensitive body" not in clean
    assert "10020" in clean


def test_mock_contract(execution):
    p: ScannerProvider = MockScannerProvider(
        WorkerSettings(
            redis_url="redis://unused",
            profile="test",
            scanner_provider="mock",
            mock_stage_seconds=0,
        )
    )
    assert (
        p.execute(request(execution).model_copy(update={"demo": True})).status == "ok"
    )
    assert p.execute(request(execution)).status == "scanner_unavailable"


@pytest.mark.parametrize(
    "failure", ["start", "scan", "recordsToScan", "alerts", "message"]
)
def test_crash_always_cleans(monkeypatch, config, execution, failure):
    runtime = FakeRuntime(failure)
    with pytest.raises(RuntimeFailure):
        provider(monkeypatch, config, execution, runtime).execute(request(execution))
    assert runtime.closed


@pytest.mark.parametrize(
    "bad", [None, [], {"alerts": "bad"}, {"alerts": [{"pluginId": "bogus"}]}]
)
def test_malformed_alert_response(monkeypatch, config, execution, bad):
    runtime = FakeRuntime()
    original = runtime.call
    runtime.call = lambda c, k, op, **p: (
        bad if op == "alerts" else original(c, k, op, **p)
    )
    with pytest.raises((ValidationError, RuntimeFailure)):
        provider(monkeypatch, config, execution, runtime).execute(request(execution))
    assert runtime.closed


@pytest.mark.parametrize("field", ["exhausted", "failed"])
def test_incomplete_cannot_export(monkeypatch, config, execution, tmp_path, field):
    runtime = FakeRuntime()
    runtime.stats = lambda: {
        "count": 1,
        "denied": 0,
        "exhausted": False,
        "failed": False,
        field: True,
    }
    with pytest.raises(RuntimeFailure):
        provider(monkeypatch, config, execution, runtime).execute(request(execution))
    assert runtime.closed and not list(tmp_path.iterdir())


def test_cancel_during_poll_cleans(monkeypatch, config, execution):
    runtime = FakeRuntime()
    alive = True
    original = runtime.call

    def call(c, k, op, **p):
        if op == "status":
            return {"status": "50"}
        return original(c, k, op, **p)

    def sleep(seconds):
        nonlocal alive
        assert seconds >= 1
        alive = False

    runtime.call = call
    with pytest.raises(Interrupted):
        provider(
            monkeypatch, config, execution, runtime, alive=lambda: alive, sleeper=sleep
        ).execute(request(execution))
    assert runtime.closed


def test_deadline_during_poll_cleans(monkeypatch, config, execution):
    runtime = FakeRuntime()
    original = runtime.call
    runtime.call = lambda c, k, op, **p: (
        {"status": "1"} if op == "status" else original(c, k, op, **p)
    )
    p = provider(monkeypatch, config, execution, runtime)
    p.sleep = lambda n: setattr(p, "wall_deadline", 0)
    with pytest.raises(TimeoutError):
        p.execute(request(execution))
    assert runtime.closed


@pytest.mark.parametrize(
    "change",
    ["allowlist", "expired", "wrong_job", "active_grant", "dns", "internet_active"],
)
def test_preflight_denies_before_runtime(monkeypatch, config, execution, change):
    runtime = FakeRuntime()
    p = provider(monkeypatch, config, execution, runtime)
    req = request(execution)
    if change == "allowlist":
        config.zap_allowlist = []
    elif change == "expired":
        p.until = datetime.now(UTC) - timedelta(seconds=1)
    elif change == "wrong_job":
        req.job_id = uuid4()
    elif change == "dns":

        def rejected(*args):
            raise ValueError("blocked")

        monkeypatch.setattr(runtime, "resolve", rejected)
    else:
        execution.policy.mode = ScanMode.ACTIVE
        execution.policy.active_warning_acknowledged = True
        execution.policy.active_rule_allowlist = ["40012"]
        if change == "internet_active":
            execution.active_confirmation_digest = "b" * 64
            monkeypatch.setattr(runtime, "resolve", lambda *args: ["8.8.8.8"])
    with pytest.raises((RuntimeFailure, TimeoutError, ValueError)):
        p.execute(req)
    assert not runtime.started


def test_authorized_active_only_allowlisted_rules(monkeypatch, config, execution):
    execution.policy.mode = ScanMode.ACTIVE
    execution.policy.active_warning_acknowledged = True
    execution.policy.active_rule_allowlist = ["40012"]
    execution.active_confirmation_digest = "b" * 64
    runtime = FakeRuntime()
    provider(monkeypatch, config, execution, runtime).execute(request(execution))
    active = [c for c in runtime.calls if c[0] == "ascan"]
    assert [c[2] for c in active] == [
        "scanners",
        "disableAllScanners",
        "enableScanners",
        "scan",
        "status",
    ]
    assert active[2][3] == {"ids": "40012"}


def test_openapi_import_sanitized_local_file(monkeypatch, config, execution):
    execution.kind = "openapi_upload"
    execution.spec = {
        "openapi": "3.0.3",
        "info": {"title": "Fixture", "version": "1"},
        "servers": [{"url": "https://unauthorized.invalid"}],
        "paths": {"/": {"get": {"responses": {"200": {"description": "OK"}}}}},
    }
    runtime = FakeRuntime()
    provider(monkeypatch, config, execution, runtime).execute(request(execution))
    assert "servers" not in runtime.upload[1]
    assert not any(c[0] == "spider" for c in runtime.calls)
    assert (
        next(c for c in runtime.calls if c[0] == "openapi")[3]["target"]
        == execution.target_url
    )


def test_ajax_opt_in_always_follows_traditional(monkeypatch, config, execution):
    execution.policy.spider = "ajax"
    runtime = FakeRuntime()
    provider(monkeypatch, config, execution, runtime).execute(request(execution))
    scans = [c[0] for c in runtime.calls if c[2] == "scan"]
    assert scans == ["spider", "ajaxSpider"]


def test_secrets_worker_scope_and_redaction(monkeypatch, config, execution):
    id = uuid4()
    secret = "Bearer private-credential"
    ciphertext = (
        Fernet(config.zap_secret_key.get_secret_value())
        .encrypt(f"{execution.organization_id}:{id}:{secret}".encode())
        .decode()
    )
    execution.credentials = [
        Credential(id=id, header_name="Authorization", ciphertext=SecretStr(ciphertext))
    ]
    runtime = FakeRuntime()
    provider(monkeypatch, config, execution, runtime).execute(request(execution))
    rule = next(c for c in runtime.calls if c[0] == "replacer")
    assert rule[3]["replacement"] == secret
    assert secret not in repr(execution)
    execution.organization_id = uuid4()
    runtime = FakeRuntime()
    with pytest.raises(RuntimeFailure):
        provider(monkeypatch, config, execution, runtime).execute(request(execution))
    assert not runtime.started


@pytest.fixture
def scope():
    return Scope(
        target_url="http://fixture.test:8000/",
        address="172.30.88.10",
        includes=["/allowed*"],
        excludes=["/allowed/private*"],
        methods=["GET"],
        max_requests=1,
        rate=100,
        seconds=10,
    )


@pytest.mark.parametrize(
    "url,method",
    [
        ("http://evil.test:8000/allowed", "GET"),
        ("http://fixture.test:8001/allowed", "GET"),
        ("https://fixture.test:8000/allowed", "GET"),
        ("http://fixture.test:8000/allowed", "POST"),
        ("http://fixture.test:8000/allowed/private", "GET"),
        ("http://fixture.test:8000/no", "GET"),
        ("http://fixture.test:8000/allowed/../private", "GET"),
        ("http://fixture.test:8000/allowed/%252e%252e/private", "GET"),
        ("http://fixture.test:8000/allowed\\private", "GET"),
        ("http://user@fixture.test:8000/allowed", "GET"),
    ],
)
def test_egress_denials(scope, url, method):
    assert not scope.permits(url, method)


def test_budget_enforces_at_execution(scope):
    budget = Budget(scope)
    assert budget.admit("http://fixture.test:8000/allowed", "GET")
    assert not budget.admit("http://fixture.test:8000/allowed", "GET")
    assert budget.exhausted


def test_context_patterns_are_escaped():
    import re

    pattern = context_pattern("https://fixture.test", "/foo(.*)/*")
    assert not re.fullmatch(pattern, "https://fixtureXtest/foobar/foo")
    assert re.fullmatch(pattern, "https://fixture.test/foo(.*)/foo")


def test_artifact_immutability_and_patterns(tmp_path):
    store = LocalArtifactStore(tmp_path, Fernet.generate_key().decode())
    store.write("o/s/id", b"original")
    with pytest.raises(FileExistsError):
        store.write("o/s/id", b"replacement")
    assert redact(
        {"alert": "custom PI-123 secretvalue", "requestBody": "private"},
        ["secretvalue"],
        [r"PI-\d+"],
    ) == {"alert": "custom [REDACTED] [REDACTED]"}


def test_runtime_resources_and_management_api(config, scope):
    runtime = DockerRuntime(config, uuid4(), lambda: None)
    calls = []

    def command(args, data=None, timeout=15):
        calls.append((args, data))
        return "172.31.0.2" if args[0] == "inspect" else "ok"

    runtime.command = command
    runtime.start(scope, "private-api-key")
    runtime.close()
    arguments = json.dumps([a for a, _ in calls])
    assert "private-api-key" not in arguments
    launches = [a for a, _ in calls if a[0] == "run"]
    assert all(
        "--cpus" in a and "--memory" in a and "--pids-limit" in a for a in launches
    )
    for launch in launches:
        expected = "512" if runtime.zap in launch else "256"
        assert launch[launch.index("--pids-limit") + 1] == expected
    assert all("--publish" not in a and "-p" not in a for a in launches)
    assert any("--internal" in a for a, _ in calls)
    assert "-host 127.0.0.1" in arguments and "@sha256:" in arguments
    assert "XDG_CACHE_HOME=/tmp/browser-cache" in arguments
    assert (
        "/home/zap/.ZAP/webdriver:rw,exec,nosuid,nodev,uid=1000,gid=1000,size=128m"
        in arguments
    )
    assert "/home/zap/.mozilla:rw,nosuid,nodev,uid=1000,gid=1000,size=64m" in arguments
    assert [a[:2] for a, _ in calls[-3:]] == [
        ["container", "rm"],
        ["container", "rm"],
        ["network", "rm"],
    ]


@pytest.mark.parametrize("tls_tunnel", [False, True])
def test_gateway_real_http_denies_foreign_destination(
    tmp_path, monkeypatch, tls_tunnel
):
    import http.client
    import ssl
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from aegis_api.zap.gateway import certificate, handler

    contacted = []

    class Target(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            contacted.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"fixture")

    target = ThreadingHTTPServer(("127.0.0.1", 0), Target)
    target_port = target.server_port
    tls = certificate("fixture.test", tmp_path)
    scheme = "https" if tls_tunnel else "http"
    if tls_tunnel:
        target.socket = tls.wrap_socket(target.socket, server_side=True)
    scope = Scope(
        target_url=f"{scheme}://fixture.test:{target_port}/",
        address="127.0.0.1",
        includes=["/allowed*"],
        excludes=["/allowed/private*"],
        methods=["GET"],
        max_requests=10,
        rate=100,
        seconds=20,
    )
    budget = Budget(scope)
    gateway = ThreadingHTTPServer(("127.0.0.1", 0), handler(scope, budget, tls))
    threads = [
        threading.Thread(target=s.serve_forever, daemon=True) for s in (target, gateway)
    ]
    # Trust only this generated fixture certificate for the upstream TLS test.
    default_context = ssl.create_default_context
    monkeypatch.setattr(
        "aegis_api.zap.gateway.ssl.create_default_context",
        lambda: default_context(cafile=str(tmp_path / "tls-cert.pem")),
    )
    connect = socket.create_connection
    destinations = []

    def pinned(address, *args, **kwargs):
        destinations.append(address)
        assert address in {
            ("127.0.0.1", gateway.server_port),
            ("127.0.0.1", target_port),
        }
        return connect(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", pinned)
    for thread in threads:
        thread.start()
    try:
        if tls_tunnel:
            # An HTTP CONNECT is terminated, then each inner request is checked.
            connection = http.client.HTTPSConnection(
                "127.0.0.1",
                gateway.server_port,
                context=ssl._create_unverified_context(),
                timeout=5,
            )
            connection.set_tunnel("fixture.test", target_port)
            connection.request("GET", "/allowed")
        else:
            connection = http.client.HTTPConnection(
                "127.0.0.1", gateway.server_port, timeout=5
            )
            connection.request("GET", f"http://fixture.test:{target_port}/allowed")
        response = connection.getresponse()
        assert response.status == 200 and response.read() == b"fixture"
        connection.close()
        for url in [
            f"{scheme}://evil.test:{target_port}/allowed",
            f"{scheme}://fixture.test:{target_port}/excluded",
            f"{scheme}://fixture.test:{target_port}/allowed//private",
            f"{scheme}://fixture.test:{target_port}/allowed/%2fprivate",
            f"{scheme}://fixture.test:{target_port}/allowed/..;/private",
        ]:
            connection = http.client.HTTPConnection(
                "127.0.0.1", gateway.server_port, timeout=5
            )
            connection.request("GET", url)
            assert connection.getresponse().status == 403
            connection.close()
        assert contacted == ["/allowed"]
        assert destinations.count(("127.0.0.1", target_port)) == 1
    finally:
        for server in (gateway, target):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)


@pytest.mark.parametrize(
    "addresses",
    [["127.0.0.1"], ["169.254.169.254"], ["8.8.8.8", "10.0.0.1"], [], "malformed"],
)
def test_dns_helper_rejects_unsafe_responses(config, addresses):
    runtime = DockerRuntime(config, uuid4(), lambda: None)
    calls = []

    def command(args, data=None, timeout=15):
        calls.append(args)
        return json.dumps(addresses)

    runtime.command = command
    with pytest.raises(RuntimeFailure):
        runtime.resolve("fixture.test", 443, False)
    assert calls[0][0] == "run" and "--pull" in calls[0]
    assert "--memory" in calls[0] and "--cpus" in calls[0]
    assert calls[-1][:2] == ["rm", "-f"]


def test_openapi_warning_is_incomplete():
    from aegis_api.zap.contracts import OpenApiImport

    with pytest.raises(ValidationError):
        OpenApiImport.model_validate({"importFile": [{"warning": "partial"}]})


@pytest.mark.parametrize("restriction", ["none", "zero_depth"])
def test_url_policy_cannot_expand_crawl(monkeypatch, config, execution, restriction):
    if restriction == "none":
        execution.policy.spider = "none"
    else:
        execution.policy.max_depth = 0
    runtime = FakeRuntime()
    with pytest.raises(RuntimeFailure):
        provider(monkeypatch, config, execution, runtime).execute(request(execution))
    assert not runtime.started


def test_ajax_applies_policy_depth(monkeypatch, config, execution):
    execution.policy.spider = "ajax"
    execution.policy.max_depth = 2
    runtime = FakeRuntime()
    provider(monkeypatch, config, execution, runtime).execute(request(execution))
    assert (
        "ajaxSpider",
        "action",
        "setOptionMaxCrawlDepth",
        {"Integer": "2"},
    ) in runtime.calls


def test_missing_active_rule_cannot_succeed(monkeypatch, config, execution):
    execution.policy.mode = ScanMode.ACTIVE
    execution.policy.active_warning_acknowledged = True
    execution.policy.active_rule_allowlist = ["99999999"]
    execution.active_confirmation_digest = "b" * 64
    runtime = FakeRuntime()
    original = runtime.call
    runtime.call = lambda c, k, op, **p: (
        {"scanners": []} if op == "scanners" else original(c, k, op, **p)
    )
    with pytest.raises(RuntimeFailure):
        provider(monkeypatch, config, execution, runtime).execute(request(execution))
    assert runtime.closed
    assert not any(c[0] == "ascan" and c[2] == "scan" for c in runtime.calls)


def test_stopped_ajax_without_observations_fails(
    monkeypatch, config, execution, tmp_path
):
    execution.policy.spider = "ajax"
    runtime = FakeRuntime()
    original = runtime.call
    runtime.call = lambda c, k, op, **p: (
        {"numberOfResults": "0"} if op == "numberOfResults" else original(c, k, op, **p)
    )
    with pytest.raises(RuntimeFailure):
        provider(monkeypatch, config, execution, runtime).execute(request(execution))
    assert runtime.closed and not list(tmp_path.iterdir())
