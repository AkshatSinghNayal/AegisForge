"""Phase 15 safety, tenant authorization, redaction and retention coverage."""

from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from test_auth import client as auth_client
from test_scans import create, prepared

from aegis_api.admin_controls import Controls, check_enabled
from aegis_api.audit import safe_fields
from aegis_api.auth import now
from aegis_api.conventions import APIError
from aegis_api.db.enums import Role, ScanMode
from aegis_api.db.models import AuditLog, OrganizationMember
from aegis_api.maintenance import remove_artifact
from aegis_api.network_policy import network_allowed
from aegis_api.settings import Settings

client = auth_client


def test_network_deny_precedence_and_closed_controls():
    assert network_allowed("10.1.1.1", ["10.0.0.0/8"], [])
    assert not network_allowed("10.1.1.1", ["10.0.0.0/8"], ["10.1.0.0/16"])
    assert not network_allowed("8.8.8.8", ["10.0.0.0/8"], [])
    assert network_allowed("2001:4860::1", ["2001:4860::/32"], [])
    for body in (
        {"concurrency": 0},
        {"allow_networks": ["https://example.com"]},
        {"deny_networks": ["10.1.1.1/8"]},
        {"token": "secret"},
    ):
        with pytest.raises(ValidationError):
            Controls.model_validate(body)


@pytest.mark.parametrize("mode", list(ScanMode))
def test_operator_and_tenant_stop(mode):
    cfg = Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        redis_url="redis://localhost",
    )
    for controls, config in (
        (Controls(scans_enabled=False), cfg),
        (Controls(), cfg.model_copy(update={"emergency_stop": True})),
    ):
        with pytest.raises(APIError):
            check_enabled(controls, config, mode)
    with pytest.raises(APIError):
        check_enabled(Controls(active_scans_enabled=False), cfg, ScanMode.ACTIVE)
    check_enabled(Controls(active_scans_enabled=False), cfg, ScanMode.PASSIVE)


def test_value_free_audit_summary():
    assert safe_fields(
        ["role", "password", "Authorization", "token=SECRET", "cookie", "role"]
    ) == ["role"]


def test_retention_path_scope(tmp_path):
    path = tmp_path / "org" / "scan" / "artifact.fernet"
    path.parent.mkdir(parents=True)
    path.write_text("encrypted synthetic bytes")
    for key in ("../outside", "other/scan/artifact", "org/scan/../../../outside"):
        with pytest.raises(ValueError):
            remove_artifact(tmp_path, "org", "scan", key)
    assert path.exists()
    remove_artifact(tmp_path, "org", "scan", "org/scan/artifact.fernet")
    remove_artifact(tmp_path, "org", "scan", "org/scan/artifact.fernet")
    assert not path.exists()
    path.symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError):
        remove_artifact(tmp_path, "org", "scan", "org/scan/artifact.fernet")


@pytest.mark.integration
async def test_controls_quota_stop_and_audit(client, db, monkeypatch):
    org, body = await prepared(client, monkeypatch)
    endpoint = f"/api/v1/admin/controls?organization_id={org}"
    limits = (await client.get(endpoint)).json()
    limits.update(target_concurrency=1, daily_quota=1)
    result = await client.put(endpoint, json=limits)
    assert result.status_code == 200, result.text
    assert (await create(client, org, body)).status_code == 202
    assert (await create(client, org, body)).status_code == 429
    limits["scans_enabled"] = False
    assert (await client.put(endpoint, json=limits)).status_code == 200
    assert (await create(client, org, body)).status_code == 409
    logs = await client.get(
        f"/api/v1/admin/audit?organization_id={org}&action=administration.updated"
    )
    assert logs.status_code == 200
    assert len(logs.json()) == 2
    assert all(r["request_id"] for r in logs.json())
    assert "scans_enabled" in logs.json()[0]["changed_fields"]
    assert (
        await client.get(f"/api/v1/admin/audit?organization_id={uuid4()}")
    ).status_code == 404


@pytest.mark.integration
@pytest.mark.parametrize("role", [Role.VIEWER, Role.DEVELOPER])
async def test_every_admin_operation_denies_non_admin(client, db, monkeypatch, role):
    org, _ = await prepared(client, monkeypatch)
    member = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == UUID(org)
        )
    )
    member.role = role
    await db.commit()
    for method, path, body in [
        ("GET", "/controls", None),
        ("PUT", "/controls", Controls().model_dump()),
        ("GET", "/audit", None),
        ("GET", "/system", None),
        ("GET", "/jobs", None),
        ("POST", f"/reports/{uuid4()}/retry", None),
        ("POST", f"/policies/{uuid4()}/publish", None),
        ("POST", f"/policies/{uuid4()}/deactivate", None),
        ("POST", f"/members/{uuid4()}/activate", None),
        ("POST", f"/members/{uuid4()}/revoke-sessions", None),
    ]:
        response = await client.request(
            method, f"/api/v1/admin{path}?organization_id={org}", json=body
        )
        assert response.status_code == 403, (path, response.text)


@pytest.mark.integration
async def test_retention_preserves_provenance_and_only_expired_objects(db, tmp_path):
    from factories import scan, tenant

    from aegis_api.db.enums import ScanState
    from aegis_api.db.models import ArtifactPurge, RawScanArtifact
    from aegis_api.maintenance import expire_artifact

    org, member, target, policy = await tenant(db)
    row = scan(org, member, target, policy)
    from aegis_api.db.enums import Completeness

    row.state = ScanState.FAILED
    row.completeness = Completeness.NONE
    db.add(row)
    await db.flush()
    prefix = f"{org.id}/{row.id}"
    for name in ("raw.fernet", "redacted.json"):
        path = tmp_path / prefix / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic")
    artifact = RawScanArtifact(
        organization_id=org.id,
        scan_id=row.id,
        artifact_kind="test",
        restricted_object_key=prefix + "/raw.fernet",
        redacted_object_key=prefix + "/redacted.json",
        encryption_key_reference="synthetic",
        content_hash="0" * 64,
        scanner_version="test",
        size_bytes=1,
        content_type="application/json",
        restricted_expires_at=now() - timedelta(days=1),
        redacted_expires_at=now() + timedelta(days=1),
    )
    db.add(artifact)
    await db.flush()
    config = Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        redis_url="redis://localhost",
        zap_artifact_root=str(tmp_path),
    )
    assert await expire_artifact(db, config)
    await db.flush()
    assert not (tmp_path / prefix / "raw.fernet").exists()
    assert (tmp_path / prefix / "redacted.json").exists()
    assert not await expire_artifact(db, config)
    assert await db.get(RawScanArtifact, artifact.id)
    assert await db.scalar(
        select(ArtifactPurge).where(ArtifactPurge.artifact_id == artifact.id)
    )
    assert await db.scalar(select(AuditLog).where(AuditLog.resource_id == artifact.id))


async def test_queued_dispatch_honors_stop(monkeypatch):
    from test_scans import memory_scan

    from aegis_api.db.enums import ScanState
    from aegis_api.scan_coordinator import prepare

    db = AsyncMock()
    db.add = lambda row: None
    import aegis_api.admin_controls as module

    monkeypatch.setattr(
        module, "controls", AsyncMock(return_value=Controls(scans_enabled=False))
    )
    cfg = Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        redis_url="redis://localhost",
    )
    row = memory_scan()
    assert await prepare(db, row, cfg) is None
    assert row.state == ScanState.FAILED


@pytest.mark.integration
async def test_concurrent_admission_has_one_target_slot(
    client, migrated_database, monkeypatch
):
    import asyncio

    import test_configuration
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from test_auth import register

    from aegis_api import auth

    engine = create_async_engine(migrated_database, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def independent_session():
        async with sessions() as session:
            yield session

    # Every HTTP request gets a separate real DB connection/transaction.
    client.app.dependency_overrides[auth.session] = independent_session
    email = f"race-{uuid4()}@example.test"

    async def unique_register(http):
        return await register(http, email)

    from test_auth import login

    async def unique_login(http):
        return await login(http, email)

    monkeypatch.setattr(test_configuration, "register", unique_register)
    monkeypatch.setattr(test_configuration, "login", unique_login)
    try:
        org, body = await prepared(client, monkeypatch)
        controls = Controls(target_concurrency=1).model_dump(mode="json")
        assert (
            await client.put(
                f"/api/v1/admin/controls?organization_id={org}", json=controls
            )
        ).status_code == 200
        results = await asyncio.gather(*(create(client, org, body) for _ in range(6)))
        assert sorted(r.status_code for r in results) == [202, 429, 429, 429, 429, 429]
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_policy_deactivation_and_cross_tenant_denial(client, monkeypatch):
    org, body = await prepared(client, monkeypatch)
    base = f"/api/v1/admin/policies/{body['policy_id']}"
    assert (
        await client.post(base + f"/deactivate?organization_id={org}")
    ).status_code == 200
    assert (await create(client, org, body)).status_code == 409
    assert (
        await client.post(base + f"/publish?organization_id={uuid4()}")
    ).status_code == 404
    assert (
        await client.post(base + f"/publish?organization_id={org}")
    ).status_code == 200
    assert (await create(client, org, body)).status_code == 202


@pytest.mark.integration
async def test_member_activation_revocation_and_audit_redaction(
    client, db, monkeypatch
):
    from aegis_api.auth_models import AccessCredential
    from aegis_api.db.enums import RecordState
    from aegis_api.db.models import User

    org, _ = await prepared(client, monkeypatch)
    user = User(
        normalized_email=f"member-{uuid4()}@example.invalid",
        display_name="Synthetic member",
    )
    db.add(user)
    await db.flush()
    target = OrganizationMember(
        organization_id=UUID(org),
        user_id=user.id,
        role=Role.ADMIN,
        status=RecordState.DEACTIVATED,
    )
    credential = AccessCredential(
        user_id=user.id,
        family_id=uuid4(),
        token_hash=uuid4().hex * 2,
        expires_at=now() + timedelta(minutes=5),
    )
    db.add_all([target, credential])
    await db.commit()
    base = f"/api/v1/admin/members/{target.id}"
    assert (
        await client.post(base + f"/activate?organization_id={org}")
    ).status_code == 200
    await db.refresh(target)
    assert target.status == RecordState.ACTIVE
    assert (
        await client.post(base + f"/revoke-sessions?organization_id={org}")
    ).status_code == 200
    await db.refresh(credential)
    assert credential.revoked_at is not None
    audit = AuditLog(
        organization_id=UUID(org),
        actor_id=target.id,
        action="test.redaction",
        resource_type="organization_member",
        resource_id=target.id,
        request_id=uuid4(),
        changed_fields=["role", "password=CANARY", "token", "cookie"],
    )
    db.add(audit)
    await db.commit()
    await db.refresh(audit)
    assert audit.changed_fields == ["role"]
    response = await client.get(f"/api/v1/admin/audit?organization_id={org}")
    assert "CANARY" not in response.text and credential.token_hash not in response.text


@pytest.mark.integration
async def test_expired_session_cleanup_preserves_live_family(db):
    from aegis_api.auth_models import AccessCredential
    from aegis_api.db.models import RefreshSession, User
    from aegis_api.maintenance import cleanup_credentials

    user = User(
        normalized_email=f"cleanup-{uuid4()}@example.invalid",
        display_name="Synthetic cleanup",
    )
    db.add(user)
    await db.flush()
    expired = RefreshSession(
        user_id=user.id,
        token_hash=uuid4().hex * 2,
        family_id=uuid4(),
        expires_at=now() - timedelta(days=1),
        idle_expires_at=now() - timedelta(days=2),
    )
    live = RefreshSession(
        user_id=user.id,
        token_hash=uuid4().hex * 2,
        family_id=uuid4(),
        expires_at=now() + timedelta(days=1),
        idle_expires_at=now() + timedelta(hours=1),
    )
    access = AccessCredential(
        user_id=user.id,
        token_hash=uuid4().hex * 2,
        family_id=expired.family_id,
        expires_at=now() - timedelta(minutes=1),
    )
    db.add_all([expired, live, access])
    await db.flush()
    ids = expired.id, live.id, access.id
    await cleanup_credentials(db)
    assert await db.get(RefreshSession, ids[0]) is None
    assert await db.get(RefreshSession, ids[1]) is not None
    assert await db.get(AccessCredential, ids[2]) is None


@pytest.mark.integration
async def test_audit_database_blocks_truncate(db):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    for table in ("audit_logs", "artifact_purges"):
        with pytest.raises(DBAPIError):
            async with db.begin_nested():
                await db.execute(text(f"TRUNCATE {table}"))
