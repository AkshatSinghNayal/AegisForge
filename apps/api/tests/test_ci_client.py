"""Execute the checked-in runner with controlled transports, including failures."""

import importlib.util
import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

spec = importlib.util.spec_from_file_location(
    "aegisforge_ci",
    next(
        p / "scripts/aegisforge_ci.py"
        for p in Path(__file__).resolve().parents
        if (p / "scripts/aegisforge_ci.py").exists()
    ),
)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def args(tmp_path):
    return SimpleNamespace(
        api_url="https://api.example.test",
        app_url="https://app.example.test",
        project=str(uuid4()),
        target=str(uuid4()),
        policy=str(uuid4()),
        environment="development",
        commit="a" * 40,
        branch="main",
        repository="owner/repo",
        run_id="123",
        job="scan",
        timeout=10,
        poll_interval=1,
        warn_exit=2,
        fail_exit=1,
        incomplete_exit=3,
        pull_request=1,
        output=str(tmp_path / "summary.json"),
        comment_only=False,
    )


def result(scan, outcome="pass", state="completed"):
    return dict(
        scan_id=scan,
        state=state,
        terminal=state in cli.TERMINAL,
        outcome=outcome,
        counts={s: 2 for s in cli.SEVERITIES},
        path=f"/app/scans/{scan}?organization={uuid4()}",
        evidence="Bearer DO_NOT_PRINT",
        title="::error::injected",
    )


@pytest.mark.parametrize(
    "outcome,state,code",
    [
        ("pass", "completed", 0),
        ("warn", "completed", 2),
        ("fail", "completed", 1),
        ("incomplete", "failed", 3),
        ("pass", "cancelled", 3),
        ("pass", "timed_out", 3),
    ],
)
def test_runner_results_redacted(tmp_path, monkeypatch, capsys, outcome, state, code):
    options = args(tmp_path)
    scan = str(uuid4())
    calls = []

    def call(self, method, path, body=None, key=None, retry=True):
        calls.append((method, path, key))
        if path.endswith("context"):
            return {
                **body,
                "target_version": 1,
                "policy_version": 3,
                "gate_policy_version": 2,
                "gate_policy_id": str(uuid4()),
            }
        if path.endswith("/scans"):
            assert len(key) == 64
            return {"id": scan}
        return result(scan, outcome, state)

    monkeypatch.setattr(cli.Client, "call", call)
    monkeypatch.setenv("AEGISFORGE_API_KEY", "agf_DO_NOT_PRINT")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "job.md"))
    assert cli.run(options) == code
    output = (
        Path(options.output).read_text()
        + (tmp_path / "job.md").read_text()
        + str(capsys.readouterr())
    )
    assert "DO_NOT_PRINT" not in output and "::error::" not in output
    assert "critical" in output and "https://app.example.test/app/scans/" in output
    assert cli.exit_code("warn", 0) == 0


@pytest.mark.parametrize("failure", [TimeoutError, cli.Cancelled])
def test_timeout_cancel_requests_server_stop(tmp_path, monkeypatch, failure):
    options, scan = args(tmp_path), str(uuid4())
    cancelled = []

    def call(self, method, path, body=None, key=None, retry=True):
        if path.endswith("context"):
            return {
                **body,
                "target_version": 1,
                "policy_version": 1,
                "gate_policy_version": 1,
                "gate_policy_id": str(uuid4()),
            }
        if path.endswith("/scans"):
            return {"id": scan}
        if path.endswith("/cancel"):
            cancelled.append(path)
            return {}
        raise failure()

    monkeypatch.setattr(cli.Client, "call", call)
    monkeypatch.setenv("AEGISFORGE_API_KEY", "synthetic")
    assert cli.run(options) == 3
    assert len(cancelled) == 1
    assert json.loads(Path(options.output).read_text())["outcome"] == "incomplete"


def test_retry_network_and_server_errors(monkeypatch):
    from io import BytesIO
    from unittest.mock import Mock

    client = cli.Client(
        "https://api.example.test", "synthetic", cli.time.monotonic() + 30
    )
    client.opener.open = Mock(
        side_effect=[
            urllib.error.URLError("secret"),
            urllib.error.HTTPError("url", 503, "secret", {}, None),
            BytesIO(b'{"ok":true}'),
        ]
    )
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    assert client.call("POST", "/scans", {}, "stable") == {"ok": True}
    assert {
        c.args[0].get_header("Idempotency-key")
        for c in client.opener.open.call_args_list
    } == {"stable"}
    with pytest.raises(cli.Failure):
        cli.NoRedirect().redirect_request(None)


def test_idempotency_changes_only_with_bound_identity():
    config = {"target_id": str(uuid4()), "policy_version": 1}
    key = cli.idempotency("owner/repo", "123", "scan", "a" * 40, config)
    assert key == cli.idempotency("OWNER/REPO", "123", "scan", "a" * 40, config)
    assert key != cli.idempotency(
        "owner/repo", "123", "scan", "a" * 40, {**config, "policy_version": 2}
    )
    assert key != cli.idempotency("owner/repo", "124", "scan", "a" * 40, config)


def test_pr_comment_updates_owned_marker_and_redacts():
    project, target, scan = str(uuid4()), str(uuid4()), str(uuid4())
    clean = cli.summary(result(scan), scan)

    class GitHub:
        def __init__(self):
            self.comments = []
            self.writes = []

        def call(self, method, path, body=None, **kwargs):
            if method == "GET":
                return self.comments
            self.writes.append((method, body))
            self.comments = [
                {
                    "id": 123,
                    "body": body["body"],
                    "user": {"login": "github-actions[bot]", "type": "Bot"},
                }
            ]

    github = GitHub()
    for _ in range(2):
        cli.update_comment(
            github, "owner/repo", 1, project, target, clean, "https://app.example.test"
        )
    assert [w[0] for w in github.writes] == ["POST", "PATCH"]
    assert "<!-- aegisforge:" in github.writes[-1][1]["body"]
    assert "DO_NOT_PRINT" not in str(github.writes)
    github.comments[0]["user"] = {"login": "attacker", "type": "User"}
    cli.update_comment(
        github, "owner/repo", 1, project, target, clean, "https://app.example.test"
    )
    assert github.writes[-1][0] == "POST"


def test_unavailable_never_passes_or_logs_exception(tmp_path, monkeypatch, capsys):
    options = args(tmp_path)
    options.incomplete_exit = 0
    monkeypatch.setenv("AEGISFORGE_API_KEY", "DO_NOT_PRINT")
    assert cli.run(options) == 3
    assert "DO_NOT_PRINT" not in str(capsys.readouterr())
    assert json.loads(Path(options.output).read_text())["counts"] is None


def test_actual_sigterm_keeps_incomplete_artifact(tmp_path):
    import os
    import signal
    import subprocess
    import sys
    import time

    child = tmp_path / "cancel_runner.py"
    marker = tmp_path / "ready"
    stopped = tmp_path / "cancelled"
    options = vars(args(tmp_path))
    child.write_text(
        "import importlib.util, signal, time\n"
        "from pathlib import Path\nfrom types import SimpleNamespace\n"
        "spec=importlib.util.spec_from_file_location('cli', "
        f"{str(Path(cli.__file__))!r})\n"
        "cli=importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)\n"
        "def call(self, method, path, body=None, key=None, retry=True):\n"
        "    if path.endswith('context'):\n"
        "        return {**body, 'target_version':1, 'policy_version':1, "
        f"'gate_policy_version':1, 'gate_policy_id':{str(uuid4())!r}}}\n"
        "    if path.endswith('/scans'):\n"
        f"        return {{'id':{str(uuid4())!r}}}\n"
        "    if path.endswith('/cancel'):\n"
        f"        Path({str(stopped)!r}).touch(); return {{}}\n"
        f"    Path({str(marker)!r}).touch()\n"
        "    time.sleep(30)\n"
        "def cancel(*args): raise cli.Cancelled()\n"
        "cli.Client.call=call\nsignal.signal(signal.SIGTERM,cancel)\n"
        f"raise SystemExit(cli.run(SimpleNamespace(**{options!r})))\n"
    )
    process = subprocess.Popen(
        [sys.executable, str(child)],
        env={**os.environ, "AEGISFORGE_API_KEY": "agf_DO_NOT_PRINT"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists()
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 3 and stopped.exists()
        assert b"DO_NOT_PRINT" not in stdout + stderr
        assert (
            json.loads(Path(options["output"]).read_text())["outcome"] == "incomplete"
        )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_polling_writes_one_final_job_summary(tmp_path, monkeypatch):
    options, scan = args(tmp_path), str(uuid4())
    polls = iter(["queued", "passive_scanning", "completed"])

    def call(self, method, path, body=None, key=None, retry=True):
        if path.endswith("context"):
            return {
                **body,
                "target_version": 1,
                "policy_version": 1,
                "gate_policy_version": 1,
                "gate_policy_id": str(uuid4()),
            }
        if path.endswith("/scans"):
            return {"id": scan}
        state = next(polls)
        return result(scan, "pass" if state == "completed" else "incomplete", state)

    monkeypatch.setattr(cli.Client, "call", call)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    monkeypatch.setenv("AEGISFORGE_API_KEY", "synthetic")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "job.md"))
    assert cli.run(options) == 0
    text = (tmp_path / "job.md").read_text()
    assert text.count("### AegisForge scan") == 1
    assert "**incomplete**" not in text and "**pass**" in text


@pytest.mark.parametrize("phase", ["open", "read"])
def test_total_request_deadline_includes_slow_network(phase):
    import time
    from io import BytesIO

    class SlowBody(BytesIO):
        def read(self, *args):
            if phase == "read":
                time.sleep(0.15)
            return super().read(*args)

    def open_response(*args, **kwargs):
        if phase == "open":
            time.sleep(0.15)
        return SlowBody(b'{"ok":true}')

    client = cli.Client(
        "https://api.example.test", "synthetic", time.monotonic() + 0.04
    )
    client.opener.open = open_response
    with pytest.raises(TimeoutError):
        client.call("GET", "/summary")


def test_passing_summary_requires_counts():
    scan = str(uuid4())
    with pytest.raises(cli.Failure):
        cli.summary({**result(scan), "counts": None}, scan)


def test_trickling_http_body_cannot_extend_deadline():
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    stopping = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            try:
                for _ in range(100):
                    if stopping.wait(0.01):
                        break
                    self.wfile.write(b" ")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = cli.Client(
            "https://api.example.test", "synthetic", time.monotonic() + 0.15
        )
        # Only the controlled test endpoint uses HTTP; production origin validation
        # remains HTTPS-only. Real urllib response reads receive a byte every 10ms.
        client.base = f"http://127.0.0.1:{server.server_port}"
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            client.call("GET", "/summary")
        assert time.monotonic() - started < 0.6
    finally:
        stopping.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
