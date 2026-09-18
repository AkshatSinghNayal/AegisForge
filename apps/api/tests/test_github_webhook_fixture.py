"""Local simulated GitHub HTTP deliveries, not the production AegisForge API."""

import hashlib
import hmac
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import pytest
from github_webhook_fixture import delivery, valid_signature


def test_github_published_signature_vector():
    # Public test vector from GitHub Docs, not a credential:
    # https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
    expected = "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17"
    assert valid_signature(b"Hello, World!", b"It's a Secret to Everybody", expected)
    assert not valid_signature(
        b"Hello, world!", b"It's a Secret to Everybody", expected
    )


@pytest.fixture
def receiver():
    secret = secrets.token_bytes(32)
    accepted = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            valid = valid_signature(
                body, secret, self.headers.get("X-Hub-Signature-256")
            )
            if valid:
                accepted.append((self.headers["X-GitHub-Event"], json.loads(body)))
            self.send_response(204 if valid else 403)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/github", secret, accepted
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("event", ["pull_request", "workflow_run"])
def test_simulated_github_delivery_over_http(receiver, event):
    url, secret, accepted = receiver
    body, headers = delivery(event, secret)
    with httpx.Client(trust_env=False, timeout=5) as client:
        assert client.post(url, content=body, headers=headers).status_code == 204
    assert accepted == [(event, json.loads(body))]
    if event == "workflow_run":
        assert accepted[0][1]["workflow_run"]["conclusion"] == "failure"
    else:
        assert "café" in accepted[0][1]["pull_request"]["title"]


@pytest.mark.parametrize(
    "failure", ["tampered", "wrong_secret", "missing", "sha1", "aegis_scheme"]
)
def test_simulated_github_signature_rejections(receiver, failure):
    url, secret, accepted = receiver
    body, headers = delivery("workflow_run", secret)
    if failure == "tampered":
        body = body.replace(b'"failure"', b'"success"')
    elif failure == "wrong_secret":
        _, headers = delivery("workflow_run", secrets.token_bytes(32))
    elif failure == "missing":
        del headers["X-Hub-Signature-256"]
    elif failure == "sha1":
        headers["X-Hub-Signature-256"] = (
            "sha1=" + hmac.new(secret, body, hashlib.sha1).hexdigest()
        )
    else:
        headers["X-Hub-Signature-256"] = (
            "sha256=" + hmac.digest(secret, b"1234." + body, "sha256").hex()
        )
    with httpx.Client(trust_env=False, timeout=5) as client:
        assert client.post(url, content=body, headers=headers).status_code == 403
    assert accepted == []
