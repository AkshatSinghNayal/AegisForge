"""Phase 7 lifecycle, transport failure, replay and tenant security regressions."""

from contextlib import asynccontextmanager
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from test_auth import client as auth_client
from test_configuration import setup

from aegis_api import configuration
from aegis_api.auth import now
from aegis_api.conventions import APIError
from aegis_api.db.enums import Completeness, ScanMode, ScanState
from aegis_api.db.models import Scan, ScanEvent, Target
from aegis_api.scan_coordinator import finish, perform, prepare
from aegis_api.scan_lifecycle import (
    CODES,
    PATH,
    SAFE_RETRY,
    TERMINAL,
    allowed,
    event,
    transition,
)
from aegis_api.scanner import StageRequest, mock_stage
from aegis_api.settings import WorkerSettings

client = auth_client


def memory_scan(state=ScanState.QUEUED, mode=ScanMode.PASSIVE):
    return Scan(
        id=uuid4(),
        organization_id=uuid4(),
        state=state,
        mode=mode,
        next_sequence=1,
        stage_attempt=1,
        version=1,
        fence=1,
        deadline_at=now() + timedelta(minutes=1),
    )


@pytest.mark.parametrize("mode", list(ScanMode))
def test_complete_state_graph(mode):
    for source in ScanState:
        for destination in ScanState:
            expected = source not in TERMINAL and destination in TERMINAL - {
                ScanState.COMPLETED
            }
            if source == ScanState.PASSIVE_SCANNING:
                expected |= destination == (
                    ScanState.ACTIVE_SCANNING
                    if mode == ScanMode.ACTIVE
                    else ScanState.COLLECTING_RESULTS
                )
            elif source in PATH[:-1]:
                expected |= destination == PATH[PATH.index(source) + 1]
            assert allowed(source, destination, mode) == expected


def test_fence_terminal_and_event_redaction():
    class Sink:
        def __init__(self):
            self.rows = []

        def add(self, row):
            self.rows.append(row)

    db = Sink()
    scan = memory_scan()
    with pytest.raises(APIError):
        transition(
            db, scan, ScanState.VALIDATING_TARGET, "stage_started", now(), fence=0
        )
    with pytest.raises(ValueError):
        event(db, scan, "Authorization: Bearer synthetic-secret")
    transition(db, scan, ScanState.CANCELLED, "cancelled", now())
    assert scan.completeness == Completeness.NONE and db.rows[0].sequence == 1
    with pytest.raises(APIError):
        transition(db, scan, ScanState.FAILED, "worker_lost", now())
    assert set(db.rows[0].__dict__) >= {"message_code", "sequence"}
    assert db.rows[0].message_code in CODES


def test_provider_guards_and_deterministic_fixture():
    for config in [
        {"profile": "prod", "scanner_provider": "mock"},
        {"profile": "dev", "scanner_provider": "mock", "demo_mode": False},
    ]:
        with pytest.raises(ValidationError):
            WorkerSettings(redis_url="redis://localhost/0", **config)
    config = WorkerSettings(
        redis_url="redis://localhost/0",
        profile="test",
        scanner_provider="mock",
        mock_stage_seconds=0,
    )
    request = StageRequest(
        scan_id=uuid4(), job_id=uuid4(), fence=1, stage=ScanState.SPIDERING, demo=True
    )
    assert mock_stage(request, config) == mock_stage(request, config)
    config.scanner_provider = "none"
    assert mock_stage(request, config).status == "scanner_unavailable"
    with pytest.raises(ValidationError):
        StageRequest.model_validate({**request.model_dump(), "authorization": "secret"})


async def prepared(client, monkeypatch):
    monkeypatch.setattr(
        configuration,
        "probe_url",
        AsyncMock(return_value=("https://synthetic.example/", 200, b"")),
    )
    prefix, _, _, policy, target = await setup(client)
    result = await client.post(prefix + "/targets", json=target)
    assert result.status_code == 200, result.text
    target = result.json()
    body = dict(
        target_id=target["id"],
        target_version=target["version"],
        policy_id=policy["id"],
        policy_version=policy["version"],
    )
    return prefix.rsplit("/", 1)[1], body


async def create(client, org, body, key=None):
    return await client.post(
        f"/api/v1/scans?organization_id={org}",
        json=body,
        headers={"Idempotency-Key": key or str(uuid4())},
    )


@pytest.mark.integration
async def test_idempotency_quota_scope_and_cancel(client, db, monkeypatch):
    org, body = await prepared(client, monkeypatch)
    key = str(uuid4())
    first = await create(client, org, body, key)
    assert first.status_code == 202, first.text
    id = first.json()["id"]
    replay = await create(client, org, body, key)
    assert replay.status_code == 202 and replay.json()["id"] == id
    conflict = await create(
        client, org, {**body, "trigger": {"branch": "different"}}, key
    )
    assert conflict.status_code == 409
    assert (
        await client.post(f"/api/v1/scans?organization_id={org}", json=body)
    ).status_code == 400
    assert (
        await client.get(f"/api/v1/scans/{id}?organization_id={uuid4()}")
    ).status_code == 404
    client.app.state.config.scan_concurrency = 1
    assert (await create(client, org, body)).status_code == 429
    response = await client.post(f"/api/v1/scans/{id}/cancel?organization_id={org}")
    assert response.status_code == 200 and response.json()["effective_gate"] == "fail"
    assert (
        await client.post(f"/api/v1/scans/{id}/cancel?organization_id={org}")
    ).status_code == 409
    rows = list(
        (
            await db.scalars(
                select(ScanEvent)
                .where(ScanEvent.scan_id == UUID(id))
                .order_by(ScanEvent.sequence)
            )
        ).all()
    )
    assert [row.sequence for row in rows] == [1, 2]
    assert [row.message_code for row in rows] == ["queued", "cancelled"]


class FakeBroker:
    def __init__(self):
        self.payload = None
        self.down = False
        self.pending = False
        self.calls = 0

    def publish(self, payload):
        self.calls += 1
        if self.down:
            raise ConnectionError("redis://secret@internal")
        self.payload = payload

    def result(self, job_id):
        if self.down:
            raise ConnectionError("synthetic-secret")
        if self.pending:
            return "PENDING", None
        config = WorkerSettings(
            redis_url="redis://localhost/0",
            profile="test",
            scanner_provider="mock",
            mock_stage_seconds=0,
        )
        return "SUCCESS", mock_stage(self.payload, config).model_dump(mode="json")


@pytest.mark.integration
async def test_mock_lifecycle_and_sse_replay(client, db, monkeypatch):
    org, body = await prepared(client, monkeypatch)
    client.app.state.config.scanner_provider = "mock"
    result = await create(client, org, body)
    assert result.status_code == 202, result.text
    id = UUID(result.json()["id"])
    scan = await db.get(Scan, id)
    broker = FakeBroker()
    for _ in range(60):
        await advance(db, scan, broker, client.app.state.config)
        await db.flush()
        if scan.state in TERMINAL:
            break
    assert scan.state == ScanState.COMPLETED
    assert scan.completeness == Completeness.PARTIAL
    assert scan.mock_manifest["evaluation"]["outcome"] == "fail"
    await db.commit()

    @asynccontextmanager
    async def sessions():
        yield db

    client.app.state.sessions = sessions
    response = await client.get(f"/api/v1/scans/{id}/events?organization_id={org}")
    assert response.status_code == 200, response.text
    ids = [
        int(line[4:]) for line in response.text.splitlines() if line.startswith("id: ")
    ]
    assert ids == list(range(1, len(ids) + 1))
    replay = await client.get(
        f"/api/v1/scans/{id}/events?organization_id={org}",
        headers={"Last-Event-ID": "3"},
    )
    assert "id: 3\n" not in replay.text and "id: 4\n" in replay.text
    assert "event: end" in replay.text
    assert (
        await client.get(
            f"/api/v1/scans/{id}/events?organization_id={org}",
            headers={"Last-Event-ID": "secret"},
        )
    ).status_code == 400
    for secret in ["synthetic-secret", "ciphertext", "Authorization", "redis://"]:
        assert secret not in response.text


@pytest.mark.integration
@pytest.mark.parametrize(
    "stage",
    [ScanState.PREPARING_SCANNER, ScanState.SPIDERING, ScanState.ACTIVE_SCANNING],
)
async def test_worker_crash_safe_retry_and_timeout(client, db, monkeypatch, stage):
    org, body = await prepared(client, monkeypatch)
    response = await create(client, org, body)
    scan = await db.get(Scan, UUID(response.json()["id"]))
    scan.state = stage
    scan.job_id = uuid4()
    scan.dispatched_at = now() - timedelta(minutes=1)
    broker = FakeBroker()
    broker.pending = True
    await advance(db, scan, broker, client.app.state.config)
    if stage in SAFE_RETRY:
        assert scan.stage_attempt == 2 and scan.job_id is None and scan.state == stage
        scan.deadline_at = now() - timedelta(seconds=1)
        await advance(db, scan, broker, client.app.state.config)
        assert scan.state == ScanState.TIMED_OUT
    else:
        assert scan.state == ScanState.FAILED and scan.failure_code == "worker_lost"
    await db.flush()


@pytest.mark.integration
async def test_redis_interruption_duplicate_result_and_revocation(
    client, db, monkeypatch
):
    org, body = await prepared(client, monkeypatch)
    response = await create(client, org, body)
    scan = await db.get(Scan, UUID(response.json()["id"]))
    broker = FakeBroker()
    await advance(db, scan, broker, client.app.state.config)
    await advance(db, scan, broker, client.app.state.config)
    id = scan.job_id
    broker.down = True
    await advance(db, scan, broker, client.app.state.config)
    assert scan.job_id == id and scan.dispatched_at is None
    broker.down = False
    await advance(db, scan, broker, client.app.state.config)
    assert scan.job_id == id and scan.dispatched_at
    transition(db, scan, ScanState.CANCELLED, "cancelled", now())
    await advance(db, scan, broker, client.app.state.config)
    assert scan.state == ScanState.CANCELLED
    target = await db.get(Target, UUID(body["target_id"]))
    target.authorized_until = now() - timedelta(seconds=1)
    await db.flush()
    assert (await create(client, org, body)).status_code == 409


@pytest.mark.integration
async def test_active_grant_binding_and_one_use(client, db, monkeypatch):
    org, body = await prepared(client, monkeypatch)
    policy = (await client.get(f"/api/v1/organizations/{org}/policies")).json()
    active = next(p for p in policy if p["mode"] == "active")
    body.update(
        policy_id=active["id"],
        policy_version=active["version"],
        active_acknowledgement=True,
    )
    grant = await client.post(
        f"/api/v1/scans/confirmations?organization_id={org}", json=body
    )
    assert grant.status_code == 200, grant.text
    body["confirmation_token"] = grant.json()["token"]
    assert (
        await create(client, org, {**body, "trigger": {"branch": "changed"}})
    ).status_code == 409
    key = str(uuid4())
    result = await create(client, org, body, key)
    assert result.status_code == 202, result.text
    assert (await create(client, org, body, key)).status_code == 202
    assert (await create(client, org, body)).status_code == 409


@pytest.mark.integration
async def test_missing_provider_and_stale_result_fail_visibly(client, db, monkeypatch):
    org, body = await prepared(client, monkeypatch)
    response = await create(client, org, body)
    scan = await db.get(Scan, UUID(response.json()["id"]))
    broker = FakeBroker()
    for _ in range(4):
        await advance(db, scan, broker, client.app.state.config)
    assert scan.state == ScanState.FAILED
    assert scan.failure_code == "scanner_unavailable"
    assert scan.completeness == Completeness.NONE
    await db.flush()
    client.app.state.config.scanner_provider = "mock"
    response = await create(client, org, body)
    scan = await db.get(Scan, UUID(response.json()["id"]))
    for _ in range(3):
        await advance(db, scan, broker, client.app.state.config)
    broker.payload.fence -= 1
    await advance(db, scan, broker, client.app.state.config)
    assert scan.state == ScanState.FAILED and scan.failure_code == "invalid_fixture"


@pytest.mark.integration
async def test_versions_secrets_csrf_and_viewer_denial(client, db, monkeypatch):
    from aegis_api.db.enums import Role
    from aegis_api.db.models import OrganizationMember

    org, body = await prepared(client, monkeypatch)
    for patch in [
        {"policy_version": 999},
        {"target_version": 999},
        {"secret_reference_ids": [str(uuid4())]},
    ]:
        assert (await create(client, org, {**body, **patch})).status_code == 409
    response = await client.post(
        f"/api/v1/scans?organization_id={org}",
        json=body,
        headers={"X-CSRF-Token": "invalid", "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 403
    member = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == UUID(org)
        )
    )
    member.role = Role.VIEWER
    await db.flush()
    assert (await create(client, org, body)).status_code == 403


@pytest.mark.integration
async def test_real_redis_duplicate_delivery_and_fail_closed(monkeypatch):
    from celery.exceptions import Ignore
    from pydantic import SecretStr
    from redis import Redis
    from redis.exceptions import ConnectionError

    from aegis_api import worker

    monkeypatch.setattr(worker.settings, "profile", "test")
    monkeypatch.setattr(worker.settings, "scanner_provider", "mock")
    monkeypatch.setattr(worker.settings, "mock_stage_seconds", 0)
    payload = StageRequest(
        scan_id=uuid4(), job_id=uuid4(), fence=1, stage=ScanState.SPIDERING, demo=True
    ).model_dump(mode="json")
    with Redis.from_url(worker.settings.redis_url.get_secret_value()) as broker:
        try:
            assert worker.execute_stage(payload)["status"] == "ok"
            with pytest.raises(Ignore):
                worker.execute_stage(payload)
            # Another delivery for the same scan cannot enter its occupied lease.
            broker.set(f"scan-worker:{payload['scan_id']}", "other-worker", ex=25)
            payload["job_id"] = str(uuid4())
            with pytest.raises(Ignore):
                worker.execute_stage(payload)
        finally:
            broker.delete(f"scan-worker:{payload['scan_id']}")
    monkeypatch.setattr(
        worker.settings, "redis_url", SecretStr("redis://127.0.0.1:1/0")
    )
    with pytest.raises(ConnectionError):
        worker.execute_stage({**payload, "job_id": str(uuid4())})


def crashed_stage(payload):
    from aegis_api import worker

    worker.settings.profile = "test"
    worker.settings.scanner_provider = "mock"
    worker.settings.mock_stage_seconds = 10
    worker.execute_stage(payload)


@pytest.mark.integration
async def test_killed_worker_retains_fenced_admission_until_lease_expiry():
    import asyncio
    import multiprocessing

    from celery.exceptions import Ignore
    from redis import Redis

    from aegis_api import worker

    payload = StageRequest(
        scan_id=uuid4(),
        job_id=uuid4(),
        fence=1,
        stage=ScanState.ACTIVE_SCANNING,
        demo=True,
    ).model_dump(mode="json")
    process = multiprocessing.get_context("fork").Process(
        target=crashed_stage, args=(payload,)
    )
    lock = f"scan-worker:{payload['scan_id']}"
    receipt = f"scan-job:{payload['job_id']}"
    with Redis.from_url(worker.settings.redis_url.get_secret_value()) as broker:
        try:
            process.start()
            for _ in range(100):
                if broker.exists(lock):
                    break
                await asyncio.sleep(0.02)
            assert broker.get(lock).decode() == payload["job_id"]
            process.kill()
            process.join(timeout=2)
            assert not process.is_alive() and process.exitcode != 0
            assert 0 < broker.ttl(lock) <= 25
            # Redelivery after abrupt death cannot repeat active execution.
            with pytest.raises(Ignore):
                worker.execute_stage(payload)
        finally:
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            broker.delete(lock, receipt)


async def advance(db, scan, broker, config):
    job = await prepare(db, scan)
    if job:
        await finish(db, scan, job, await perform(job, broker), config)
