import hmac
import json
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select
from test_auth import client as auth_client
from test_scans import prepared

from aegis_api import github
from aegis_api.db.models import GitHubDelivery, GitHubMapping, Scan, Target

client = auth_client


def test_signature_vector_and_untrusted_url():
    secret = "It's a Secret to Everybody"
    expected = "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17"
    assert github.valid_signature(b"Hello, World!", secret, expected)
    assert not github.valid_signature(b"Hello, world!", secret, expected)
    mapping = GitHubMapping(
        repository="owner/repo", branch="main", events=["push", "pull_request"]
    )
    body = {
        "repository": {"full_name": "owner/repo"},
        "ref": "refs/heads/main",
        "after": "a" * 40,
        "target_url": "http://169.254.169.254/",
    }
    assert github.trigger(json.dumps(body).encode(), "push", mapping).commit == "a" * 40
    body["repository"]["full_name"] = "attacker/repo"
    with pytest.raises(ValueError):
        github.trigger(json.dumps(body).encode(), "push", mapping)


async def setup(client, db, monkeypatch):
    org, scan_body = await prepared(client, monkeypatch)
    target = await db.get(Target, UUID(scan_body["target_id"]))
    path = f"/api/v1/organizations/{org}/projects/{target.project_id}/gate-policies"
    published = await client.post(path, json={"policy": {"rules": []}})
    assert published.status_code == 200, published.text
    response = await client.post(
        path + "/activation", json={"policy_id": published.json()["id"]}
    )
    assert response.status_code == 200, response.text
    client.app.state.config.notification_encryption_key = SecretStr(
        Fernet.generate_key().decode()
    )
    body = dict(
        project_id=str(target.project_id),
        target_id=str(target.id),
        policy_id=scan_body["policy_id"],
        environment=target.environment,
        repository="owner/repo",
        branch="main",
        events=["push", "pull_request"],
    )
    response = await client.post(
        f"/api/v1/github/mappings?organization_id={org}", json=body
    )
    assert response.status_code == 200, response.text
    return org, body, response.json()


@pytest.mark.integration
async def test_signed_delivery_atomic_replay_invalid_scope_and_secret(
    client, db, monkeypatch
):
    org, body, mapping = await setup(client, db, monkeypatch)
    path = mapping["webhook_path"]
    raw = json.dumps(
        {
            "repository": {"full_name": body["repository"]},
            "ref": "refs/heads/main",
            "after": "a" * 40,
            "url": "http://169.254.169.254",
        }
    ).encode()
    headers = {
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": str(uuid4()),
        "X-Hub-Signature-256": "sha256="
        + hmac.digest(mapping["secret"].encode(), raw, "sha256").hex(),
    }
    invalid = await client.post(path, content=raw + b" ", headers=headers)
    assert invalid.status_code == 401
    invalid = await client.post(
        path, content=raw, headers={**headers, "X-GitHub-Event": "issues"}
    )
    assert invalid.status_code == 422
    first = await client.post(path, content=raw, headers=headers)
    assert first.status_code == 200 and first.json()["state"] == "accepted", first.text
    again = await client.post(path, content=raw, headers=headers)
    assert again.json() == first.json()
    replay = await client.post(
        path, content=raw, headers={**headers, "X-GitHub-Delivery": str(uuid4())}
    )
    assert replay.json() == first.json()  # payload replay with a changed header
    rows = (
        await db.scalars(
            select(GitHubDelivery).where(GitHubDelivery.organization_id == UUID(org))
        )
    ).all()
    assert len(rows) == 1
    scan = await db.get(Scan, UUID(first.json()["scan_id"]))
    assert (
        str(scan.target_id) == body["target_id"]
        and scan.trigger_metadata["commit"] == "a" * 40
    )
    listed = await client.get(f"/api/v1/github/mappings?organization_id={org}")
    assert mapping["secret"] not in listed.text and "secret" not in listed.text
    saved = await db.get(GitHubMapping, UUID(mapping["id"]))
    assert mapping["secret"] not in saved.secret_ciphertext
    bad = raw.replace(b"owner/repo", b"attacker/repo")
    denied = await client.post(
        path,
        content=bad,
        headers={
            **headers,
            "X-GitHub-Delivery": str(uuid4()),
            "X-Hub-Signature-256": "sha256="
            + hmac.digest(mapping["secret"].encode(), bad, "sha256").hex(),
        },
    )
    assert denied.status_code == 422
    receipts = await client.get(f"/api/v1/github/deliveries?organization_id={org}")
    assert {r["state"] for r in receipts.json()} == {"accepted", "rejected"}
    check = await client.post(
        f"/api/v1/github/mappings/{mapping['id']}/test?organization_id={org}"
    )
    assert check.status_code == 200
    foreign = await client.post(
        f"/api/v1/github/mappings/{mapping['id']}/test?organization_id={uuid4()}"
    )
    assert foreign.status_code == 404


@pytest.mark.parametrize("change", ["fork", "base", "closed"])
def test_pull_request_mapping_rejects_untrusted_changes(change):
    mapping = GitHubMapping(
        repository="owner/repo", branch="main", events=["pull_request"]
    )
    ref = {"ref": "main", "sha": "a" * 40, "repo": {"full_name": "owner/repo"}}
    payload = {
        "repository": {"full_name": "owner/repo"},
        "action": "opened",
        "pull_request": {"number": 1, "base": ref, "head": {**ref, "ref": "feature"}},
    }
    assert (
        github.trigger(
            json.dumps(payload).encode(), "pull_request", mapping
        ).pull_request
        == 1
    )
    if change == "fork":
        payload["pull_request"]["head"]["repo"] = {"full_name": "attacker/repo"}
    elif change == "base":
        payload["pull_request"]["base"]["ref"] = "other"
    else:
        payload["action"] = "closed"
    with pytest.raises(ValueError):
        github.trigger(json.dumps(payload).encode(), "pull_request", mapping)


@pytest.mark.integration
async def test_ci_api_key_idempotency_cancellation_and_version_binding(
    client, db, monkeypatch
):
    from datetime import timedelta

    from aegis_api.auth import now

    org, body, mapping = await setup(client, db, monkeypatch)
    issued = await client.post(
        f"/api/v1/api-keys?organization_id={org}",
        json={
            "name": "CI",
            "scopes": ["scans:create", "scans:read"],
            "expires_at": (now() + timedelta(days=1)).isoformat(),
        },
    )
    assert issued.status_code == 201
    headers = {"Authorization": "Bearer " + issued.json()["secret"]}
    selection = {
        k: body[k] for k in ["project_id", "target_id", "policy_id", "environment"]
    }
    context = await client.post(
        "/api/public/v1/ci/context", json=selection, headers=headers
    )
    assert context.status_code == 200, context.text
    config = context.json()
    request = {
        **config,
        "trigger": {
            "source": "ci",
            "repository": "owner/repo",
            "commit": "a" * 40,
            "branch": "main",
            "pull_request": 12,
        },
    }
    headers["Idempotency-Key"] = "ci-test-stable"
    first = await client.post("/api/public/v1/ci/scans", json=request, headers=headers)
    assert first.status_code == 202, first.text
    replay = await client.post("/api/public/v1/ci/scans", json=request, headers=headers)
    assert replay.json()["id"] == first.json()["id"]
    assert (
        await client.post(
            "/api/public/v1/ci/scans",
            json={**request, "policy_version": 999},
            headers=headers,
        )
    ).status_code == 409
    path = f"/api/public/v1/ci/scans/{first.json()['id']}"
    state = await client.get(path + "/summary", headers=headers)
    assert state.status_code == 200, state.text
    assert state.json()["outcome"] == "incomplete" and state.json()["counts"] is None
    for _ in range(2):
        assert (await client.post(path + "/cancel", headers=headers)).status_code == 200
    state = await client.get(path + "/summary", headers=headers)
    assert state.json()["terminal"] and state.json()["outcome"] != "pass"
    assert (
        await client.get(
            "/api/public/v1/ci/scans/" + str(uuid4()) + "/summary", headers=headers
        )
    ).status_code == 404
    assert (
        await client.post(
            "/api/public/v1/ci/context",
            json={**selection, "project_id": str(uuid4())},
            headers=headers,
        )
    ).status_code == 409


@pytest.mark.integration
async def test_summary_uses_retained_deterministic_evaluation(db):
    from test_policies import setup as policy_setup

    from aegis_api.ci import summary
    from aegis_api.db.models import GatePolicy
    from aegis_api.policy_engine import Match, Policy, Rule
    from aegis_api.policy_service import persist_evaluation

    for outcome in ["pass", "warn", "fail"]:
        policy = Policy(
            rules=[]
            if outcome == "pass"
            else [Rule(id="all", match=Match(), outcome=outcome)]
        )
        context, scan, published = await policy_setup(db, policy)
        scan.config_snapshot = {
            **scan.config_snapshot,
            "gate_policy_id": str(published.id),
        }
        gate = await db.get(GatePolicy, published.id)
        await persist_evaluation(db, scan, gate)
        view = await summary(scan.id, context[1], db)
        assert view.outcome == outcome
        assert sum(view.counts.values()) == 1
        assert "fixture" not in view.model_dump_json()


@pytest.mark.integration
async def test_mapping_csrf_deactivation_and_changed_configuration(
    client, db, monkeypatch
):
    org, body, mapping = await setup(client, db, monkeypatch)
    token = client.headers.pop("X-CSRF-Token")
    assert (
        await client.post(f"/api/v1/github/mappings?organization_id={org}", json=body)
    ).status_code == 403
    client.headers["X-CSRF-Token"] = token
    target = await db.get(Target, UUID(body["target_id"]))
    target.version += 1
    await db.flush()
    assert (
        await client.post(
            f"/api/v1/github/mappings/{mapping['id']}/test?organization_id={org}"
        )
    ).status_code == 409
    raw = json.dumps(
        {
            "repository": {"full_name": "owner/repo"},
            "ref": "refs/heads/main",
            "after": "b" * 40,
        }
    ).encode()
    headers = {
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": str(uuid4()),
        "X-Hub-Signature-256": "sha256="
        + hmac.digest(mapping["secret"].encode(), raw, "sha256").hex(),
    }
    response = await client.post(mapping["webhook_path"], content=raw, headers=headers)
    assert response.json()["state"] == "blocked"
    assert not (
        await db.scalars(select(Scan).where(Scan.organization_id == UUID(org)))
    ).all()
    await client.delete(
        f"/api/v1/workspace/integrations/{mapping['integration_id']}?organization_id={org}"
    )
    assert (
        await client.post(mapping["webhook_path"], content=raw, headers=headers)
    ).status_code == 403


@pytest.mark.integration
async def test_mapping_foreign_keys_deny_cross_tenant_links(client, db, monkeypatch):
    from factories import tenant
    from sqlalchemy.exc import IntegrityError

    org, body, mapping = await setup(client, db, monkeypatch)
    foreign, _, target, _ = await tenant(db)
    original = await db.get(GitHubMapping, UUID(mapping["id"]))
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                GitHubMapping(
                    organization_id=foreign.id,
                    integration_id=original.integration_id,
                    creator_id=original.creator_id,
                    project_id=original.project_id,
                    target_id=original.target_id,
                    policy_id=original.policy_id,
                    gate_policy_id=original.gate_policy_id,
                    target_version=1,
                    policy_version=1,
                    repository="foreign/repo",
                    branch="main",
                    environment="development",
                    events=["push"],
                    secret_ciphertext="synthetic",
                )
            )
            await db.flush()
    denied = await client.post(
        f"/api/v1/github/mappings?organization_id={org}",
        json={**body, "target_id": str(target.id)},
    )
    assert denied.status_code == 404


@pytest.mark.integration
async def test_ci_reused_key_cannot_replay_another_gate_version(
    client, db, monkeypatch
):
    from datetime import timedelta

    from aegis_api.auth import now

    org, body, _ = await setup(client, db, monkeypatch)
    key = await client.post(
        f"/api/v1/api-keys?organization_id={org}",
        json={
            "name": "Review",
            "scopes": ["scans:create", "scans:read"],
            "expires_at": (now() + timedelta(days=1)).isoformat(),
        },
    )
    headers = {
        "Authorization": "Bearer " + key.json()["secret"],
        "Idempotency-Key": "unchanged-client-key",
    }
    selection = {
        k: body[k] for k in ["project_id", "target_id", "policy_id", "environment"]
    }
    context = (
        await client.post("/api/public/v1/ci/context", json=selection, headers=headers)
    ).json()
    first = await client.post(
        "/api/public/v1/ci/scans",
        json={**context, "trigger": {"source": "ci"}},
        headers=headers,
    )
    assert first.status_code == 202
    path = f"/api/v1/organizations/{org}/projects/{body['project_id']}/gate-policies"
    gate = (
        await client.post(path, json={"policy": {"incomplete_outcome": "fail"}})
    ).json()
    assert (
        await client.post(path + "/activation", json={"policy_id": gate["id"]})
    ).status_code == 200
    changed = (
        await client.post("/api/public/v1/ci/context", json=selection, headers=headers)
    ).json()
    assert changed["gate_policy_id"] != context["gate_policy_id"]
    replay = await client.post(
        "/api/public/v1/ci/scans",
        json={**changed, "trigger": {"source": "ci"}},
        headers=headers,
    )
    assert replay.status_code == 409, replay.text


@pytest.mark.integration
async def test_delivery_id_conflict_wins_over_matching_payload(client, db, monkeypatch):
    _, _, mapping = await setup(client, db, monkeypatch)
    first_id, second_id = str(uuid4()), str(uuid4())
    first = json.dumps({"repository": {"full_name": "unsupported/repo"}}).encode()
    second = json.dumps({"repository": {"full_name": "owner/repo"}}).encode()

    async def send(raw, delivery_id):
        return await client.post(
            mapping["webhook_path"],
            content=raw,
            headers={
                "X-GitHub-Event": "ping",
                "X-GitHub-Delivery": delivery_id,
                "X-Hub-Signature-256": "sha256="
                + hmac.digest(mapping["secret"].encode(), raw, "sha256").hex(),
            },
        )

    assert (await send(first, first_id)).status_code == 422
    assert (await send(second, second_id)).status_code == 200
    # The OR query must not depend on which legal PostgreSQL plan finds a row first.
    from sqlalchemy import text

    await db.execute(text("SET LOCAL enable_indexscan = off"))
    await db.execute(text("SET LOCAL enable_bitmapscan = off"))
    conflict = await send(first, second_id)
    assert conflict.status_code == 409, conflict.text


@pytest.mark.integration
@pytest.mark.parametrize(
    "failure,status",
    [
        ("missing_signature", 401),
        ("wrong_signature", 401),
        ("missing_delivery", 400),
        ("invalid_delivery", 400),
        ("unsupported_event", 422),
        ("expired_target", 200),
        ("demoted_creator", 403),
        ("inactive_organization", 403),
    ],
)
async def test_webhook_failures_never_enqueue_or_log_secrets(
    client, db, monkeypatch, caplog, failure, status
):
    from datetime import timedelta

    from aegis_api.auth import now
    from aegis_api.db.enums import RecordState, Role
    from aegis_api.db.models import Organization, OrganizationMember

    org, body, mapping = await setup(client, db, monkeypatch)
    raw = json.dumps(
        {
            "repository": {"full_name": "owner/repo"},
            "ref": "refs/heads/main",
            "after": "a" * 40,
            "body": "synthetic-review-secret-canary",
        }
    ).encode()
    headers = {
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": str(uuid4()),
        "X-Hub-Signature-256": "sha256="
        + hmac.digest(mapping["secret"].encode(), raw, "sha256").hex(),
    }
    if failure == "missing_signature":
        headers.pop("X-Hub-Signature-256")
    elif failure == "wrong_signature":
        headers["X-Hub-Signature-256"] = "sha256=" + "0" * 64
    elif failure == "missing_delivery":
        headers.pop("X-GitHub-Delivery")
    elif failure == "invalid_delivery":
        headers["X-GitHub-Delivery"] = "invalid"
    elif failure == "unsupported_event":
        headers["X-GitHub-Event"] = "workflow_run"
    elif failure == "expired_target":
        target = await db.get(Target, UUID(body["target_id"]))
        target.authorized_until = now() - timedelta(seconds=1)
    elif failure == "demoted_creator":
        row = await db.get(GitHubMapping, UUID(mapping["id"]))
        member = await db.get(OrganizationMember, row.creator_id)
        member.role = Role.VIEWER
    else:
        row = await db.get(Organization, UUID(org))
        row.status = RecordState.DEACTIVATED
    await db.flush()
    response = await client.post(mapping["webhook_path"], content=raw, headers=headers)
    assert response.status_code == status
    if status == 200:
        assert response.json() == {"state": "blocked", "scan_id": None}
    assert not (
        await db.scalars(select(Scan).where(Scan.organization_id == UUID(org)))
    ).all()
    assert "synthetic-review-secret-canary" not in response.text + caplog.text
    assert mapping["secret"] not in response.text + caplog.text
