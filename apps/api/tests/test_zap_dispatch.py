"""Real PostgreSQL scanner handoff, tenant and immutable provenance regressions."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_scans import client as auth_client
from test_scans import create, prepared

from aegis_api.db.enums import Completeness, ScanState
from aegis_api.db.models import RawScanArtifact, Scan, ScanEvent
from aegis_api.scan_coordinator import finish, prepare
from aegis_api.scanner import StageResult
from aegis_api.zap.contracts import ArtifactReceipt, Execution
from aegis_api.zap_dispatch import collected, envelope, progress

client = auth_client
pytestmark = pytest.mark.integration


async def real_job(client, db, monkeypatch):
    org, body = await prepared(client, monkeypatch)
    config = client.app.state.config
    config.scanner_provider = "zap"
    config.zap_dispatch_key = SecretStr(Fernet.generate_key().decode())
    response = await create(client, org, body)
    assert response.status_code == 202
    scan = await db.get(Scan, UUID(response.json()["id"]))
    for _ in range(3):
        job = await prepare(db, scan, config)
        await db.flush()
    assert job and job.real and job.execution
    return scan, job, config


def receipt(scan):
    id = uuid4()
    prefix = f"{scan.organization_id}/{scan.id}/{id}"
    return ArtifactReceipt(
        id=id,
        organization_id=scan.organization_id,
        scan_id=scan.id,
        restricted_object_key=f"{prefix}.fernet",
        redacted_object_key=f"{prefix}.json",
        content_hash="a" * 64,
        redacted_hash="b" * 64,
        scanner_version="2.17.0",
        size_bytes=50,
    )


async def test_sealed_handoff_preserves_binding(client, db, monkeypatch):
    scan, job, config = await real_job(client, db, monkeypatch)
    sealed = await envelope(db, scan, config)
    payload = Execution.model_validate_json(
        Fernet(config.zap_dispatch_key.get_secret_value()).decrypt(
            sealed.get_secret_value()
        )
    )
    assert (
        payload.organization_id,
        payload.scan_id,
        payload.job_id,
        payload.fence,
    ) == (scan.organization_id, scan.id, scan.job_id, scan.fence)
    assert payload.policy_version == scan.config_snapshot["policy_version"]
    assert payload.target_url not in repr(job)


async def test_collection_persists_immutable_artifact_without_passing_gate(
    client, db, monkeypatch
):
    scan, job, config = await real_job(client, db, monkeypatch)
    await finish(db, scan, job, ("PUBLISHED", None), config)
    job = replace(job, publish=False)
    await progress(db, scan, ["preparing_scanner", "spidering", "passive_scanning"])
    assert scan.state == ScanState.PASSIVE_SCANNING
    job = replace(job, stage=scan.state)
    result = StageResult(
        scan_id=scan.id,
        job_id=job.job_id,
        fence=job.fence,
        stage=ScanState.VALIDATING_TARGET,
        status="ok",
        fixture_version="zap-v1",
        artifact=receipt(scan),
    )
    await finish(db, scan, job, ("SUCCESS", result.model_dump(mode="json")), config)
    await db.flush()
    assert (
        scan.state == ScanState.COMPLETED and scan.completeness == Completeness.PARTIAL
    )
    assert scan.mock_manifest is None
    artifact = await db.scalar(
        select(RawScanArtifact).where(RawScanArtifact.scan_id == scan.id)
    )
    assert artifact and artifact.scanner_version == "2.17.0"
    with pytest.raises(DBAPIError):
        async with db.begin_nested():
            await db.execute(
                text("UPDATE raw_scan_artifacts SET content_hash=:hash WHERE id=:id"),
                {"hash": "c" * 64, "id": artifact.id},
            )


async def test_cross_tenant_artifact_denied_before_insert(client, db, monkeypatch):
    scan, job, config = await real_job(client, db, monkeypatch)
    value = receipt(scan).model_copy(update={"organization_id": uuid4()})
    with pytest.raises(ValueError):
        await collected(db, scan, value)
    assert scan.state == ScanState.VALIDATING_TARGET
    assert not await db.scalar(
        select(RawScanArtifact.id).where(RawScanArtifact.scan_id == scan.id)
    )


async def test_progress_sanitized_order_and_replay(client, db, monkeypatch):
    scan, job, config = await real_job(client, db, monkeypatch)
    for _ in range(2):
        await progress(db, scan, ["preparing_scanner", "spidering"])
        await db.flush()
    rows = list(
        (
            await db.scalars(
                select(ScanEvent).where(
                    ScanEvent.scan_id == scan.id,
                    ScanEvent.message_code == "scanner_progress",
                )
            )
        ).all()
    )
    assert len(rows) == 2 and len({r.sequence for r in rows}) == 2
    with pytest.raises(ValueError):
        await progress(db, scan, ["Authorization: private"])


async def test_zap_failure_does_not_retry_active_execution(client, db, monkeypatch):
    scan, job, config = await real_job(client, db, monkeypatch)
    await finish(db, scan, job, ("PUBLISHED", None), config)
    job = replace(job, publish=False)
    await finish(db, scan, job, ("FAILURE", None), config)
    assert scan.state == ScanState.FAILED and scan.completeness == Completeness.NONE
    assert scan.stage_attempt == 1
