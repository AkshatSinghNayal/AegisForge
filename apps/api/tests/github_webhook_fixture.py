"""Test-only GitHub deliveries; never represents an actual repository or Actions run."""

import hashlib
import hmac
import json
from uuid import uuid4


def delivery(event: str, secret: bytes) -> tuple[bytes, dict[str, str]]:
    repository = {"id": 101, "name": "synthetic", "full_name": "fixture/synthetic"}
    if event == "pull_request":
        payload = {
            "action": "opened",
            "number": 7,
            "repository": repository,
            "pull_request": {
                "number": 7,
                "title": "Synthetic review – café",
                "head": {"sha": "a" * 40},
                "base": {"ref": "main"},
            },
        }
    elif event == "workflow_run":
        payload = {
            "action": "completed",
            "repository": repository,
            "workflow_run": {
                "id": 202,
                "name": "Synthetic CI",
                "head_sha": "a" * 40,
                "status": "completed",
                "conclusion": "failure",
                "event": "pull_request",
            },
        }
    else:
        raise ValueError("Unsupported synthetic event")
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    # GitHub signs only the raw body, without AegisForge's timestamp prefix.
    return body, {
        "Content-Type": "application/json",
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": str(uuid4()),
        "X-Hub-Signature-256": "sha256=" + hmac.digest(secret, body, "sha256").hex(),
    }


def valid_signature(body: bytes, secret: bytes, header: str | None) -> bool:
    if header is None:
        return False
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), header.encode())
