"""Strict-review regressions for credential recovery and scheduler isolation."""

from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from aegis_api import scans
from aegis_api.auth import now
from aegis_api.conventions import APIError
from aegis_api.db.enums import ScanState


async def test_sse_expired_access_requests_refresh_not_permanent_revocation(
    monkeypatch,
):
    scan = SimpleNamespace(next_sequence=2)
    monkeypatch.setattr(scans, "resource", AsyncMock(return_value=scan))
    monkeypatch.setattr(
        scans,
        "principal",
        AsyncMock(side_effect=APIError(401, "unauthorized", "Sign in to continue.")),
    )
    db = SimpleNamespace(rollback=AsyncMock())

    @asynccontextmanager
    async def sessions():
        yield db

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(sessions=sessions)),
        is_disconnected=AsyncMock(return_value=False),
    )
    response = await scans.events(
        uuid4(), request, SimpleNamespace(organization_id=uuid4()), db, None
    )
    frames = [frame async for frame in response.body_iterator]
    assert "event: session_expired" in "".join(frames)
    assert "access_revoked" not in "".join(frames)


@pytest.mark.integration
async def test_scheduler_prioritizes_elapsed_deadline_beyond_oldest_hundred(
    db, monkeypatch
):
    from factories import scan as factory_scan
    from factories import tenant
    from sqlalchemy import select

    from aegis_api import scan_coordinator as coordinator
    from aegis_api.db.models import Scan
    from aegis_api.settings import get_settings

    context = await tenant(db)
    rows = [factory_scan(*context) for _ in range(101)]
    for index, row in enumerate(rows):
        row.state = ScanState.QUEUED
        row.created_at = now() - timedelta(minutes=10, seconds=101 - index)
        row.deadline_at = now() + timedelta(minutes=30)
    rows[-1].deadline_at = now() - timedelta(seconds=1)
    db.add_all(rows)
    await db.flush()
    expired_id = rows[-1].id
    visited = []

    async def record(db, scan, config):
        visited.append(scan.id)

    monkeypatch.setattr(coordinator, "prepare", record)

    class Sessions:
        @asynccontextmanager
        async def __call__(self):
            yield db

        @asynccontextmanager
        async def begin(self):
            yield db

    await coordinator.tick(Sessions(), SimpleNamespace(), get_settings())
    assert expired_id in visited
    assert await db.scalar(select(Scan.id).where(Scan.id == expired_id)) == expired_id


@pytest.mark.integration
async def test_broker_stall_does_not_hold_cancel_lock(migrated_database, monkeypatch):
    import asyncio
    import threading

    from factories import scan as factory_scan
    from factories import tenant
    from sqlalchemy import select

    from aegis_api import scan_coordinator as coordinator
    from aegis_api.db.models import Organization, Scan
    from aegis_api.db.session import database
    from aegis_api.scan_lifecycle import transition
    from aegis_api.settings import get_settings

    config = get_settings()
    engine, sessions = database(config)
    entered, release = threading.Event(), threading.Event()
    task = None
    monkeypatch.setattr(
        coordinator, "current_authorization", AsyncMock(return_value=True)
    )

    class StalledBroker:
        def publish(self, payload):
            entered.set()
            release.wait(timeout=3)

    try:
        async with sessions.begin() as db:
            context = await tenant(db)
            scan = factory_scan(*context)
            scan.state = ScanState.PREPARING_SCANNER
            scan.job_id = uuid4()
            db.add(scan)
            await db.flush()
            org_id, scan_id = scan.organization_id, scan.id
        task = asyncio.create_task(coordinator.tick(sessions, StalledBroker(), config))
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.02)
        assert entered.is_set()

        async def cancel_while_transport_stalled():
            async with sessions.begin() as db:
                await db.scalar(
                    select(Organization)
                    .where(Organization.id == org_id)
                    .with_for_update()
                )
                current = await db.scalar(
                    select(Scan)
                    .where(Scan.organization_id == org_id, Scan.id == scan_id)
                    .with_for_update()
                )
                transition(db, current, ScanState.CANCELLED, "cancelled", now())

        await asyncio.wait_for(cancel_while_transport_stalled(), timeout=1)
        release.set()
        await task
        async with sessions() as db:
            current = await db.get(Scan, scan_id)
            assert (
                current.state == ScanState.CANCELLED and current.dispatched_at is None
            )
    finally:
        release.set()
        if task:
            await task
        await engine.dispose()
