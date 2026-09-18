"""Phase 13 privacy, authorization, immutable artifacts and delivery boundaries."""

import hashlib
import hmac
import io
import json
import socket
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from factories import scan, tenant
from pydantic import SecretStr, ValidationError
from pypdf import PdfReader
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request
from test_auth import client as auth_client
from test_auth import login, register

from aegis_api import api_keys, notifications, report_jobs, reporting
from aegis_api.auth import now
from aegis_api.conventions import APIError
from aegis_api.db.enums import Completeness, NotificationState, ReportState, ScanState
from aegis_api.db.models import (
    APIKey,
    NotificationDelivery,
    NotificationDestination,
    Report,
)
from aegis_api.settings import Settings

client = auth_client


def config(tmp_path):
    return Settings(
        profile="test",
        database_url=SecretStr("postgresql+asyncpg://test@localhost/test"),
        redis_url=SecretStr("redis://localhost/0"),
        report_root=str(tmp_path),
        report_signing_key=SecretStr("s" * 32),
        notification_encryption_key=SecretStr(Fernet.generate_key().decode()),
    )


def request(cfg):
    return Request(
        {"type": "http", "app": SimpleNamespace(state=SimpleNamespace(config=cfg))}
    )


def snapshot():
    return reporting.Snapshot(
        organization_id=uuid4(),
        scan_id=uuid4(),
        project_id=uuid4(),
        target_id=uuid4(),
        policy_id=uuid4(),
        policy_version=1,
        evaluation_id=None,
        scanner_versions=["2.16.1"],
        scan_state="failed",
        completeness="partial",
        created_at=now(),
        started_at=now(),
        finished_at=now(),
        captured_at=now(),
        severity_summary={"high": 1},
        evidence=[
            reporting.Evidence(
                finding_id=uuid4(),
                occurrence_id=uuid4(),
                artifact_id=uuid4(),
                severity="high",
                ai_analysis_ids=[],
            )
        ],
        policy_result="incomplete",
        limitations=["Partial scan; no passing gate."],
    )


def test_pdf_and_json_content(tmp_path):
    value = snapshot()
    encoded = reporting.render(value, "json")
    assert reporting.Snapshot.model_validate_json(encoded) == value
    from jsonschema import validate

    validate(json.loads(encoded), reporting.Snapshot.model_json_schema())
    pdf = reporting.render(value, "pdf")
    text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)
    for expected in [
        "AegisForge",
        "failed",
        "partial",
        "incomplete",
        "2.16.1",
        "Advisory AI",
        str(value.evidence[0].artifact_id),
        "Redacted",
    ]:
        assert expected in text
    (tmp_path / "report.pdf").write_bytes(pdf)
    with pytest.raises(ValidationError):
        reporting.Snapshot.model_validate(
            {**value.model_dump(), "response_body": "SECRET_FIXTURE"}
        )


def test_local_storage_write_once_traversal_and_signatures(tmp_path):
    cfg = config(tmp_path)
    store = reporting.ReportStore(cfg)
    store.write("org/report.json", b"{}", "application/json")
    assert store.path("org/report.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        store.write("org/report.json", b"changed", "application/json")
    with pytest.raises(ValueError):
        store.path("../../escape")
    org, report = uuid4(), uuid4()
    a = reporting.signature(cfg, org, report, 100)
    assert a != reporting.signature(cfg, uuid4(), report, 100)
    assert a != reporting.signature(cfg, org, report, 101)
    with pytest.raises(APIError):
        reporting.signature(
            cfg.model_copy(update={"report_signing_key": SecretStr("")}),
            org,
            report,
            100,
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://127.0.0.1/",
        "https://168.63.129.16/",
        "https://[64:ff9b::7f00:1]/",
        "https://[2002:7f00:1::]/",
        "https://169.254.169.254/",
        "https://[::1]/",
        "https://[::ffff:127.0.0.1]/",
        "https://localhost/",
        "https://example.com:8443/",
        "https://user:password@example.com/",
        "https://example.com/#fragment",
    ],
)
def test_ssrf_urls(url):
    with pytest.raises(ValueError):
        notifications.validate_url(url)


async def test_dns_mixed_public_private_and_rebinding(monkeypatch):
    loop = __import__("asyncio").get_running_loop()
    fake = AsyncMock(
        return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 443)),
        ]
    )
    monkeypatch.setattr(loop, "getaddrinfo", fake)
    with pytest.raises(ValueError):
        await notifications.PublicResolver().resolve("example.com", 443)
    fake.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
    assert (await notifications.PublicResolver().resolve("example.com", 443))[0][
        "host"
    ] == "8.8.8.8"
    fake.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
    ]
    with pytest.raises(ValueError):
        await notifications.PublicResolver().resolve("example.com", 443)


def test_webhook_signature_and_cipher_scope(tmp_path):
    payload = b'{"event":"scan.failed"}'
    signed = notifications.signed_headers("secret", 1234, payload)
    expected = hmac.new(b"secret", b"1234." + payload, hashlib.sha256).hexdigest()
    assert signed == {
        "X-Aegis-Timestamp": "1234",
        "X-Aegis-Signature": "sha256=" + expected,
    }
    cfg = config(tmp_path)
    org, identity = uuid4(), uuid4()
    body = notifications.DestinationInput(
        name="Test",
        kind="webhook",
        address=SecretStr("https://example.com/hook/SECRET_FIXTURE"),
        secret=SecretStr("HMAC_FIXTURE" * 4),
        subscriptions=["scan.failed"],
    )
    cipher = notifications.seal(cfg, org, identity, body)
    assert "SECRET_FIXTURE" not in cipher and "HMAC_FIXTURE" not in cipher
    row = NotificationDestination(
        id=identity, organization_id=org, configuration_ciphertext=cipher
    )
    assert notifications.unseal(cfg, row)[0].endswith("SECRET_FIXTURE")
    row.organization_id = uuid4()
    with pytest.raises(ValueError):
        notifications.unseal(cfg, row)


def test_key_entropy_hash_one_time_schema():
    a, prefix, hashed = api_keys.issue_secret()
    b, _, _ = api_keys.issue_secret()
    assert len(a) == 47 and a != b and prefix == a[:16]
    assert hashed == hashlib.sha256(a.encode()).hexdigest() and a not in hashed
    assert "secret" not in api_keys.KeyView.model_fields
    assert "key_hash" not in api_keys.IssuedKey.model_fields


@pytest.mark.integration
async def test_snapshot_privacy_regeneration_download_and_tenant_denial(db, tmp_path):
    ctx = await tenant(db)
    foreign = await tenant(db)
    row = scan(*ctx)
    row.state = ScanState.FAILED
    row.completeness = Completeness.PARTIAL
    row.config_snapshot = {
        "policy_version": 1,
        "Authorization": "Bearer SECRET_FIXTURE",
        "Cookie": "COOKIE_FIXTURE",
        "response_body": "BODY_FIXTURE",
    }
    db.add(row)
    await db.flush()
    cfg = config(tmp_path)
    created = await reporting.create(
        reporting.ReportInput(scan_id=row.id, format="json"), ctx[1], db, request(cfg)
    )
    assert created.state == ReportState.PENDING
    retained = await db.get(Report, created.id)
    assert all(
        secret not in json.dumps(retained.snapshot)
        for secret in ["SECRET_FIXTURE", "COOKIE_FIXTURE", "BODY_FIXTURE"]
    )
    assert retained.snapshot["policy_result"] == "incomplete"
    assert await report_jobs.generate_one(db, cfg)
    await db.commit()
    second = await reporting.create(
        reporting.ReportInput(scan_id=row.id, format="pdf"), ctx[1], db, request(cfg)
    )
    assert second.id != created.id and second.version == 2
    assert await report_jobs.generate_one(db, cfg)
    await db.commit()
    pdf_row = await db.get(Report, second.id)
    pdf_bytes = reporting.ReportStore(cfg).path(pdf_row.object_key).read_bytes()
    pdf_text = "\n".join(
        p.extract_text() for p in PdfReader(io.BytesIO(pdf_bytes)).pages
    )
    assert all(
        secret not in pdf_text
        for secret in ["SECRET_FIXTURE", "COOKIE_FIXTURE", "BODY_FIXTURE"]
    )
    with pytest.raises(APIError) as denied:
        await reporting.download(created.id, foreign[1], db, request(cfg))
    assert denied.value.status == 404
    url = await reporting.download(created.id, ctx[1], db, request(cfg))
    from urllib.parse import parse_qs, urlsplit

    query = parse_qs(urlsplit(url.url).query)
    params = dict(
        report_id=created.id,
        organization_id=ctx[0].id,
        expires=int(query["expires"][0]),
        signature=query["signature"][0],
        request=request(cfg),
        db=db,
    )
    response = await reporting.content(**params)
    assert hashlib.sha256(response.body).hexdigest() == retained.content_hash
    with pytest.raises(APIError):
        await reporting.content(**{**params, "expires": int(now().timestamp()) - 1})
    with pytest.raises(APIError):
        await reporting.content(**{**params, "organization_id": foreign[0].id})
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(
                text("UPDATE reports SET snapshot = '{}' WHERE id = :id"),
                {"id": created.id},
            )

    for assignment in [
        "state = 'pending'",
        "content_hash = 'replacement'",
        "redaction_version = 'replacement'",
    ]:
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await db.execute(
                    text(f"UPDATE reports SET {assignment} WHERE id = :id"),
                    {"id": created.id},
                )
    await db.execute(
        text("UPDATE reports SET state = 'expired' WHERE id = :id"), {"id": created.id}
    )
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(
                text("UPDATE reports SET content_hash = 'replacement' WHERE id = :id"),
                {"id": created.id},
            )


@pytest.mark.integration
async def test_retry_backoff_dead_letter_and_manual_retry(db, tmp_path, monkeypatch):
    ctx = await tenant(db)
    cfg = config(tmp_path)
    dest = NotificationDestination(
        organization_id=ctx[0].id,
        name="retry",
        kind="email",
        address_reference="encrypted",
        enabled=True,
        subscriptions=["scan.failed"],
    )
    db.add(dest)
    await db.flush()
    await report_jobs.enqueue(
        db, cfg, dest, "scan.failed", uuid4(), ctx[2].project_id, now()
    )
    await db.flush()
    failed = AsyncMock(side_effect=ValueError("SECRET_PROVIDER_ERROR"))
    monkeypatch.setattr(report_jobs, "send", failed)
    for attempt in range(1, 6):
        assert await report_jobs.deliver_one(db, cfg)
        delivery = await db.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.destination_id == dest.id
            )
        )
        assert delivery.attempts == attempt
        assert delivery.failure_code == "delivery_failed"
        assert "SECRET_PROVIDER_ERROR" not in json.dumps(delivery.payload)
        if attempt < 5:
            assert delivery.next_attempt_at > now()
            delivery.next_attempt_at = now() - timedelta(seconds=1)
        await db.flush()
    assert delivery.state == NotificationState.DEAD_LETTER
    await notifications.retry(delivery.id, ctx[1], db)
    success = AsyncMock()
    monkeypatch.setattr(report_jobs, "send", success)
    assert await report_jobs.deliver_one(db, cfg)
    assert delivery.state == NotificationState.SENT and delivery.attempts == 6


@pytest.mark.integration
async def test_api_key_http_scope_expiry_revoke_and_rate_limit(client, db):
    await register(client)
    await login(client)
    org = (await client.get("/api/v1/auth/me")).json()["organizations"][0]["id"]
    created = await client.post(
        f"/api/v1/api-keys?organization_id={org}",
        json={
            "name": "CI",
            "scopes": ["scans:read"],
            "expires_at": (now() + timedelta(days=1)).isoformat(),
        },
    )
    assert created.status_code == 201, created.text
    value = created.json()
    listed = await client.get(f"/api/v1/api-keys?organization_id={org}")
    assert value["secret"] not in listed.text and "key_hash" not in listed.text
    row = await db.get(APIKey, value["id"])
    assert row.key_hash == hashlib.sha256(value["secret"].encode()).hexdigest()
    session_headers = dict(client.headers)
    client.headers["Authorization"] = "Bearer " + value["secret"]
    assert (await client.get("/api/public/v1/projects")).status_code == 200
    assert (await client.get("/api/public/v1/findings")).status_code == 403
    client.app.state.config.api_key_rate_limit = 2
    assert (await client.get("/api/public/v1/projects")).status_code == 429
    assert row.last_used_at is not None
    client.app.state.config.api_key_rate_limit = 100
    row.expires_at = now() - timedelta(seconds=1)
    await db.flush()
    assert (await client.get("/api/public/v1/projects")).status_code == 401
    row.expires_at = now() + timedelta(days=1)
    client.headers.clear()
    client.headers.update(session_headers)
    assert (
        await client.delete(f"/api/v1/api-keys/{value['id']}?organization_id={org}")
    ).status_code == 200
    client.headers["Authorization"] = "Bearer " + value["secret"]
    assert (await client.get("/api/public/v1/projects")).status_code == 401


def test_s3_private_encryption_and_presign(tmp_path, monkeypatch):
    from unittest.mock import Mock

    cfg = config(tmp_path).model_copy(
        update={
            "report_storage": "s3",
            "report_bucket": "private-reports",
            "report_kms_key_id": "alias/reports",
        }
    )
    client = Mock()
    monkeypatch.setattr(reporting.ReportStore, "s3", lambda _: client)
    store = reporting.ReportStore(cfg)
    store.write("tenant/report.json", b"{}", "application/json")
    args = client.put_object.call_args.kwargs
    assert args["IfNoneMatch"] == "*" and args["ServerSideEncryption"] == "aws:kms"
    assert args["SSEKMSKeyId"] == "alias/reports" and "ACL" not in args
    store.delete("tenant/report.json")
    client.delete_object.assert_called_once()


async def test_webhook_adapter_exact_bytes_no_redirect_or_proxy(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    body = notifications.DestinationInput(
        name="Signed",
        kind="webhook",
        address=SecretStr("https://example.com/hook"),
        secret=SecretStr("secret" * 8),
        subscriptions=["scan.failed"],
    )
    org, identity = uuid4(), uuid4()
    row = NotificationDestination(
        id=identity,
        organization_id=org,
        kind="webhook",
        configuration_ciphertext=notifications.seal(cfg, org, identity, body),
    )
    captured = {}

    class Response:
        status = 302

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            await captured["connector"].close()

        def post(self, address, **kwargs):
            captured.update(kwargs)
            return Response()

    monkeypatch.setattr(notifications.aiohttp, "ClientSession", Client)
    payload = notifications.NotificationPayload(
        event="scan.failed",
        organization_id=org,
        resource_id=uuid4(),
        link="https://aegis.example/app/scans",
    )
    with pytest.raises(ValueError):
        await notifications.send(cfg, row, payload, uuid4())
    assert captured["trust_env"] is False and captured["allow_redirects"] is False
    data = captured["data"]
    headers = captured["headers"]
    assert data == payload.model_dump_json().encode()
    assert (
        headers["X-Aegis-Signature"]
        == notifications.signed_headers(
            "secret" * 8, int(headers["X-Aegis-Timestamp"]), data
        )["X-Aegis-Signature"]
    )


@pytest.mark.integration
async def test_fanout_dedup_and_project_filter(db, tmp_path):
    ctx = await tenant(db)
    cfg = config(tmp_path)
    dest = NotificationDestination(
        organization_id=ctx[0].id,
        name="Subscribed",
        kind="email",
        address_reference="encrypted",
        enabled=True,
        subscriptions=[
            "scan.completed",
            "scan.failed",
            "report.ready",
            "finding.high",
            "policy.failed",
        ],
    )
    wrong = NotificationDestination(
        organization_id=ctx[0].id,
        name="Wrong project",
        project_id=(await tenant(db))[2].project_id,
        kind="email",
        address_reference="encrypted",
        enabled=True,
        subscriptions=["scan.failed"],
    )
    # Database independently denies cross-tenant destinations.
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(wrong)
            await db.flush()
    db.add(dest)
    await db.flush()
    item = scan(*ctx)
    item.state = ScanState.FAILED
    item.completeness = Completeness.PARTIAL
    item.finished_at = now() + timedelta(seconds=1)
    db.add(item)
    await db.flush()
    await report_jobs.fanout(db, cfg)
    await report_jobs.fanout(db, cfg)
    rows = (
        await db.scalars(
            select(NotificationDelivery).where(
                NotificationDelivery.destination_id == dest.id
            )
        )
    ).all()
    assert len(rows) == 1 and rows[0].payload["event"] == "scan.failed"
    assert rows[0].payload["resource_id"] == str(item.id)
    assert "organization=" in rows[0].payload["link"]


@pytest.mark.integration
async def test_api_key_cannot_read_foreign_scan_or_use_session_routes(client, db):
    await register(client)
    await login(client)
    org = (await client.get("/api/v1/auth/me")).json()["organizations"][0]["id"]
    created = await client.post(
        f"/api/v1/api-keys?organization_id={org}",
        json={
            "name": "Reader",
            "scopes": ["scans:read", "reports:read"],
            "expires_at": (now() + timedelta(days=1)).isoformat(),
        },
    )
    foreign = await tenant(db)
    item = scan(*foreign)
    db.add(item)
    await db.flush()
    client.headers["Authorization"] = "Bearer " + created.json()["secret"]
    for path in [
        f"/api/public/v1/scans/{item.id}",
        f"/api/public/v1/scans/{item.id}/events",
        f"/api/public/v1/reports?scan_id={item.id}",
    ]:
        assert (await client.get(path)).status_code == 404
    assert (
        await client.get(f"/api/v1/api-keys?organization_id={org}")
    ).status_code == 401
    assert (await client.post("/api/public/v1/scans", json={})).status_code == 403


@pytest.mark.integration
async def test_exception_expiring_only_active_version(db, tmp_path):
    from aegis_api.db.models import GateActivation, GatePolicy

    ctx = await tenant(db)
    cfg = config(tmp_path)
    dest = NotificationDestination(
        organization_id=ctx[0].id,
        name="Exceptions",
        kind="email",
        address_reference="encrypted",
        enabled=True,
        subscriptions=["exception.expiring"],
    )
    db.add(dest)
    await db.flush()
    policy = GatePolicy(
        organization_id=ctx[0].id,
        project_id=ctx[2].project_id,
        version=1,
        published_by=ctx[1].id,
        snapshot={
            "allow_exceptions": True,
            "exceptions": [
                {
                    "finding_id": str(uuid4()),
                    "owner_id": str(ctx[1].id),
                    "reason": "SECRET_REASON_FIXTURE",
                    "approved_by": str(ctx[1].id),
                    "created_at": now().isoformat(),
                    "expires_at": (now() + timedelta(days=2)).isoformat(),
                }
            ],
        },
    )
    db.add(policy)
    await db.flush()
    db.add(
        GateActivation(
            organization_id=ctx[0].id,
            project_id=ctx[2].project_id,
            gate_policy_id=policy.id,
            actor_id=ctx[1].id,
            sequence=1,
        )
    )
    await db.flush()
    await report_jobs.fanout(db, cfg)
    await report_jobs.fanout(db, cfg)
    rows = (
        await db.scalars(
            select(NotificationDelivery).where(
                NotificationDelivery.destination_id == dest.id
            )
        )
    ).all()
    assert len(rows) == 1 and rows[0].payload["event"] == "exception.expiring"
    assert "SECRET_REASON_FIXTURE" not in json.dumps(rows[0].payload)


@pytest.mark.integration
async def test_report_never_promotes_legacy_evaluation_to_passing_gate(db):
    from aegis_api.db.models import PolicyEvaluation

    ctx = await tenant(db)
    item = scan(*ctx)
    item.state = ScanState.COMPLETED
    item.completeness = Completeness.COMPLETE
    item.is_demo = False
    db.add(item)
    await db.flush()
    db.add(
        PolicyEvaluation(
            organization_id=ctx[0].id,
            scan_id=item.id,
            policy_id=ctx[3].id,
            input_digest="0" * 64,
            evaluation_version="legacy-v1",
            outcome="pass",
            reason_codes=[],
            completeness="complete",
            enrichment_status="disabled",
            scan_state="completed",
        )
    )
    await db.flush()
    value = await reporting.capture(db, item)
    assert value.evaluation_id is None and value.policy_result == "incomplete"


@pytest.mark.integration
async def test_expired_report_updates_latest_scan_status(db, tmp_path, monkeypatch):
    ctx = await tenant(db)
    item = scan(*ctx)
    db.add(item)
    await db.flush()
    cfg = config(tmp_path)
    created = await reporting.create(
        reporting.ReportInput(scan_id=item.id, format="json"), ctx[1], db, request(cfg)
    )
    assert await report_jobs.generate_one(db, cfg)
    await db.flush()
    assert item.report_status == ReportState.COMPLETE
    monkeypatch.setattr(report_jobs, "now", lambda: now() + timedelta(days=365))
    await report_jobs.expire_one(db, cfg)
    assert item.report_status == ReportState.EXPIRED
    retained = await db.get(Report, created.id)
    assert not reporting.ReportStore(cfg).path(retained.object_key).exists()


@pytest.mark.integration
async def test_key_revocation_during_usage_commit_is_rechecked(
    db, tmp_path, monkeypatch
):
    from fastapi.security import HTTPAuthorizationCredentials

    ctx = await tenant(db)
    issued = await api_keys.create(
        api_keys.KeyInput(
            name="race", scopes=["scans:read"], expires_at=now() + timedelta(days=1)
        ),
        ctx[1],
        db,
    )
    req = request(config(tmp_path))
    req.app.state.redis = SimpleNamespace(eval=AsyncMock(return_value=1))
    original = db.commit

    async def commit_then_revoke():
        await original()
        await db.execute(
            text("UPDATE api_keys SET revoked_at = now() WHERE id = :id"),
            {"id": issued.id},
        )

    monkeypatch.setattr(db, "commit", commit_then_revoke)
    with pytest.raises(APIError) as denied:
        await api_keys.access("scans:read")(
            req,
            db,
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=issued.secret),
        )
    assert denied.value.status == 401


@pytest.mark.integration
async def test_report_storage_failure_is_not_ready(db, tmp_path, monkeypatch):
    ctx = await tenant(db)
    item = scan(*ctx)
    db.add(item)
    await db.flush()
    cfg = config(tmp_path)
    created = await reporting.create(
        reporting.ReportInput(scan_id=item.id, format="pdf"), ctx[1], db, request(cfg)
    )

    def unavailable(*args):
        raise OSError("SECRET_STORAGE_FIXTURE")

    monkeypatch.setattr(reporting.ReportStore, "write", unavailable)
    assert await report_jobs.generate_one(db, cfg)
    retained = await db.get(Report, created.id)
    assert retained.state == ReportState.FAILED
    assert item.report_status == ReportState.FAILED
    assert retained.failure_code == "generation_failed"
    assert retained.object_key is None and retained.content_hash is None
    with pytest.raises(APIError):
        await reporting.download(created.id, ctx[1], db, request(cfg))


@pytest.mark.parametrize(
    "kind,status", [("slack", 200), ("slack", 429), ("github", 201), ("github", 403)]
)
async def test_adapter_success_and_rejection(kind, status, tmp_path, monkeypatch):
    cfg = config(tmp_path)
    org, identity = uuid4(), uuid4()
    address = (
        "https://hooks.slack.com/services/FIXTURE"
        if kind == "slack"
        else "https://api.github.com/repos/owner/repo/issues/1/comments"
    )
    body = notifications.DestinationInput(
        name="test",
        kind=kind,
        address=SecretStr(address),
        secret=SecretStr("PROVIDER_SECRET_FIXTURE" * 3),
        subscriptions=["scan.failed"],
    )
    row = NotificationDestination(
        id=identity,
        organization_id=org,
        kind=kind,
        configuration_ciphertext=notifications.seal(cfg, org, identity, body),
    )
    captured = {}

    class Response:
        def __init__(self, status):
            self.status = status
            self.content = SimpleNamespace(
                read=AsyncMock(
                    side_effect=[
                        b'{"pull_request":',
                        b'{"url":"https://api.github.com/repos/owner/repo/pulls/1"}}',
                        b"",
                    ]
                )
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Client:
        def __init__(self, **kwargs):
            self.connector = kwargs["connector"]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            await self.connector.close()

        def get(self, address, **kwargs):
            assert kwargs["allow_redirects"] is False
            return Response(200)

        def post(self, address, **kwargs):
            captured.update(kwargs)
            return Response(status)

    monkeypatch.setattr(notifications.aiohttp, "ClientSession", Client)
    payload = notifications.NotificationPayload(
        event="scan.failed",
        organization_id=org,
        resource_id=uuid4(),
        link="https://aegis.example/app/scans",
    )
    if status >= 400:
        with pytest.raises(ValueError):
            await notifications.send(cfg, row, payload, uuid4())
    else:
        await notifications.send(cfg, row, payload, uuid4())
    assert b"PROVIDER_SECRET_FIXTURE" not in captured["data"]
    assert b"scan.failed" in captured["data"]
    assert captured["allow_redirects"] is False
