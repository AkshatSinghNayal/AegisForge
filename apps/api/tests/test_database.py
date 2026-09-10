import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from conftest import migration_config
from factories import finding, scan
from sqlalchemy import delete, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from aegis_api.conventions import APIError, CursorCodec, FindingQuery, request_digest
from aegis_api.db.enums import Completeness, EnrichmentState, PolicyOutcome, ScanState
from aegis_api.db.models import (
    Base,
    Finding,
    IdempotencyRecord,
    PolicyEvaluation,
    Project,
    ProjectMember,
    Scan,
    ScanEvent,
    Target,
)
from aegis_api.db.repository import (
    Repository,
    TargetRepository,
    TenantScope,
    TimelineRepository,
)
from aegis_api.db.service import CommandService

pytestmark = pytest.mark.integration


@asynccontextmanager
async def rejected(db, exception=IntegrityError):
    with pytest.raises(exception):
        async with db.begin_nested():
            yield


def test_migration_roundtrip(migrated_database: str) -> None:
    async def tables() -> set[str]:
        engine = create_async_engine(migrated_database, hide_parameters=True)
        async with engine.connect() as conn:
            names = await conn.run_sync(lambda c: inspect(c).get_table_names())
        await engine.dispose()
        return set(names)

    assert asyncio.run(tables()) == set(Base.metadata.tables) | {"alembic_version"}
    command.check(migration_config())

    # Latest-revision downgrade must preserve the foundation and existing data.
    async def marker(*, insert: bool = False) -> bool:
        engine = create_async_engine(migrated_database, hide_parameters=True)
        async with engine.begin() as conn:
            if insert:
                await conn.execute(
                    text(
                        "INSERT INTO organizations (name, slug, status, version) "
                        "VALUES ('Synthetic migration marker', 'migration-marker', "
                        "'active', 1)"
                    )
                )
            found = await conn.scalar(
                text(
                    "SELECT count(*) FROM organizations WHERE slug = 'migration-marker'"
                )
            )
        await engine.dispose()
        return found == 1

    async def guard_installed() -> bool:
        engine = create_async_engine(migrated_database, hide_parameters=True)
        async with engine.connect() as conn:
            count = await conn.scalar(
                text(
                    "SELECT count(*) FROM pg_trigger "
                    "WHERE tgname = 'policy_evaluations_scan_guard'"
                )
            )
            function = await conn.scalar(
                text("SELECT to_regprocedure('aegis_validate_passing_evaluation()')")
            )
        await engine.dispose()
        assert (count == 1) == (function is not None)
        return count == 1

    assert asyncio.run(guard_installed())
    assert asyncio.run(marker(insert=True))
    command.downgrade(migration_config(), "0001")
    assert not asyncio.run(guard_installed())
    assert asyncio.run(tables()) == (
        set(Base.metadata.tables)
        - {
            "access_credentials",
            "identity_tokens",
            "identity_audits",
            "invitations",
            "mail_deliveries",
            "scan_confirmations",
            "finding_reviews",
            "ai_feedback",
        }
    ) | {"alembic_version"}
    assert asyncio.run(marker())
    command.upgrade(migration_config(), "head")
    command.upgrade(migration_config(), "head")
    assert asyncio.run(marker())
    assert asyncio.run(guard_installed())
    command.check(migration_config())
    # Retain the original empty-foundation roundtrip as well.
    command.downgrade(migration_config(), "base")
    assert asyncio.run(tables()) == {"alembic_version"}
    command.upgrade(migration_config(), "head")
    command.check(migration_config())


async def test_tenant_repository_and_version(
    db: AsyncSession, two_organizations
) -> None:
    a, b = two_organizations
    org, member, target, _ = a
    repo = TargetRepository(db, TenantScope(org.id))
    assert (await repo.get(target.id)).id == target.id
    with pytest.raises(APIError) as error:
        await repo.get(b[2].id)
    assert error.value.status == 404
    with pytest.raises(APIError):
        await repo.add(b[2])
    updated = await repo.deactivate(target.id, 1)
    assert updated.version == 2
    assert updated.authorized_until is None
    with pytest.raises(APIError) as stale:
        await repo.deactivate(target.id, 1)
    assert stale.value.status == 412
    with pytest.raises(APIError) as foreign:
        await repo.deactivate(b[2].id, 1)
    assert foreign.value.status == 404
    assert b[2].version == 1


async def test_unique_and_cross_tenant_constraints(
    db: AsyncSession, two_organizations
) -> None:
    a, b = two_organizations
    for record in [
        Project(
            organization_id=a[0].id, name="Synthetic project", created_by_id=a[1].id
        ),
        Project(organization_id=a[0].id, name="Foreign creator", created_by_id=b[1].id),
        ProjectMember(
            organization_id=a[0].id, project_id=a[2].project_id, member_id=b[1].id
        ),
        Target(
            organization_id=a[0].id,
            project_id=b[2].project_id,
            canonical_url="https://foreign.example.invalid",
            kind="web",
            scope_hosts=[],
            scope_paths=[],
        ),
    ]:
        async with rejected(db):
            db.add(record)
            await db.flush()
    # Same project name in different organizations was accepted by the fixture.
    async with rejected(db):
        await db.execute(delete(Project).where(Project.id == a[2].project_id))
    project = Project(organization_id=a[0].id, name="Disposable", created_by_id=a[1].id)
    db.add(project)
    await db.flush()
    assignment = ProjectMember(
        organization_id=a[0].id, project_id=project.id, member_id=a[1].id
    )
    db.add(assignment)
    await db.flush()
    await db.execute(delete(Project).where(Project.id == project.id))
    assert (
        await db.scalar(
            select(ProjectMember.id).where(ProjectMember.id == assignment.id)
        )
        is None
    )


async def test_scans_timestamps_enums_and_fail_closed(
    db: AsyncSession, two_organizations
) -> None:
    a, b = two_organizations
    item = scan(*a)
    db.add(item)
    await db.flush()
    assert item.created_at.utcoffset() == timedelta(0)
    assert item.updated_at.utcoffset() == timedelta(0)
    assert item.state is ScanState.DRAFT
    for changes in [
        dict(policy_id=b[3].id),
        dict(mode="active"),
        dict(state=ScanState.FAILED, completeness=Completeness.COMPLETE),
    ]:
        async with rejected(db):
            await db.execute(update(Scan).where(Scan.id == item.id).values(**changes))
    async with rejected(db):
        db.add(
            PolicyEvaluation(
                organization_id=a[0].id,
                scan_id=item.id,
                policy_id=a[3].id,
                input_digest="0" * 64,
                evaluation_version="test-v1",
                outcome=PolicyOutcome.PASS,
                reason_codes=[],
                completeness=Completeness.PARTIAL,
                enrichment_status=EnrichmentState.COMPLETE,
                scan_state=ScanState.COMPLETED,
            )
        )
        await db.flush()
    event = ScanEvent(
        organization_id=a[0].id,
        scan_id=item.id,
        sequence=1,
        stage=ScanState.DRAFT,
        message_code="synthetic_fixture",
    )
    db.add(event)
    await db.flush()
    async with rejected(db):
        db.add(
            ScanEvent(
                organization_id=a[0].id,
                scan_id=item.id,
                sequence=1,
                stage=ScanState.DRAFT,
                message_code="duplicate",
            )
        )
        await db.flush()


async def test_cursor_timeline_ties_and_isolation(
    db: AsyncSession, two_organizations
) -> None:
    a, b = two_organizations
    timestamp = datetime.now(UTC)
    records = [finding(a[2], timestamp=timestamp) for _ in range(5)]
    db.add_all(records + [finding(b[2], timestamp=timestamp)])
    await db.flush()
    codec = CursorCodec(b"synthetic-test-only-signing-key-000")
    repo = TimelineRepository(db, TenantScope(a[0].id), Finding)
    for order in ["created_at", "-created_at"]:
        query = FindingQuery(limit=2, order=order)
        ids = []
        while True:
            rows, page = await repo.page(query, codec)
            ids.extend(row.id for row in rows)
            if not page.has_more:
                assert page.next_cursor is None
                break
            query = query.model_copy(update={"cursor": page.next_cursor})
        assert ids == sorted([r.id for r in records], reverse=order.startswith("-"))
    rows, _ = await repo.page(FindingQuery(target_id=b[2].id), codec)
    assert rows == []


@pytest.mark.parametrize(
    "operation",
    [
        "POST /api/v1/scans",
        "POST /api/v1/scans/synthetic/reports",
        "POST /api/v1/webhooks/github",
    ],
)
async def test_command_replay_and_conflict(
    db: AsyncSession, two_organizations, operation: str
) -> None:
    a, b = two_organizations
    service = CommandService(db, TenantScope(a[0].id), a[1].id)
    calls = []

    async def create(resource_id):
        calls.append(resource_id)

    options = dict(
        operation=operation,
        key="synthetic-fixture-key",
        digest=request_digest({"target": str(a[2].id)}),
        resource_id=uuid4(),
        status=202,
        create=create,
    )
    first = await service.execute(**options)
    replay = await service.execute(**(options | {"resource_id": uuid4()}))
    assert first.resource_id == replay.resource_id
    assert replay.replayed and len(calls) == 1
    with pytest.raises(APIError) as conflict:
        await service.execute(**(options | {"digest": "f" * 64}))
    assert conflict.value.status == 409
    other = CommandService(db, TenantScope(b[0].id), b[1].id)
    assert not (await other.execute(**options)).replayed
    await db.execute(
        update(IdempotencyRecord)
        .where(IdempotencyRecord.organization_id == a[0].id)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    assert not (await service.execute(**options)).replayed


async def test_command_rollback(db: AsyncSession, two_organizations) -> None:
    a, _ = two_organizations
    service = CommandService(db, TenantScope(a[0].id), a[1].id)

    async def fail(resource_id):
        await Repository(db, TenantScope(a[0].id), Project).add(
            Project(
                id=resource_id,
                organization_id=a[0].id,
                name="Rolled back",
                created_by_id=a[1].id,
            )
        )
        raise RuntimeError("Synthetic failure")

    resource_id = uuid4()
    async with rejected(db, RuntimeError):
        await service.execute(
            operation="POST /api/v1/scans",
            key="synthetic",
            digest="0" * 64,
            resource_id=resource_id,
            status=202,
            create=fail,
        )
    assert (
        await db.scalar(
            select(IdempotencyRecord.id).where(
                IdempotencyRecord.resource_id == resource_id
            )
        )
        is None
    )
    assert await db.scalar(select(Project.id).where(Project.id == resource_id)) is None


async def test_full_graph_tenant_foreign_keys_and_immutable_history(
    db: AsyncSession, two_organizations
) -> None:
    from factories import evidence_graph

    from aegis_api.db.models import TenantRecord

    a, b = two_organizations
    graph = await evidence_graph(db, a)
    for record in graph:
        if isinstance(record, TenantRecord):
            # All these graph records have tenant-bound parents; moving only the
            # organization must fail even through direct SQL outside repositories.
            async with rejected(db):
                await db.execute(
                    update(type(record))
                    .where(type(record).id == record.id)
                    .values(organization_id=b[0].id)
                )
            with pytest.raises(APIError) as foreign:
                await Repository(db, TenantScope(b[0].id), type(record)).get(record.id)
            assert foreign.value.status == 404
    for table in [
        "scan_policies",
        "scan_events",
        "finding_occurrences",
        "ai_analyses",
        "policy_evaluations",
        "audit_logs",
    ]:
        async with rejected(db):
            await db.execute(text(f"UPDATE {table} SET updated_at = now()"))
    before = (
        await db.execute(
            text("SELECT created_at, updated_at FROM targets WHERE id = :id"),
            {"id": a[2].id},
        )
    ).one()
    await db.execute(
        text("UPDATE targets SET kind = 'api', created_at = now() WHERE id = :id"),
        {"id": a[2].id},
    )
    after = (
        await db.execute(
            text("SELECT created_at, updated_at FROM targets WHERE id = :id"),
            {"id": a[2].id},
        )
    ).one()
    assert after.created_at == before.created_at
    assert after.updated_at > before.updated_at


async def test_concurrent_idempotency(migrated_database: str) -> None:
    from factories import tenant
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = create_async_engine(migrated_database, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            org, member, _, _ = await tenant(session)
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def run(first: bool):
            async with sessions.begin() as session:
                service = CommandService(session, TenantScope(org.id), member.id)

                async def create(resource_id):
                    calls.append(resource_id)
                    if first:
                        entered.set()
                        await release.wait()
                    session.add(
                        Project(
                            id=resource_id,
                            organization_id=org.id,
                            name="Concurrent command",
                            created_by_id=member.id,
                        )
                    )

                return await service.execute(
                    operation="POST /api/v1/scans",
                    key="synthetic-concurrent",
                    digest="0" * 64,
                    resource_id=uuid4(),
                    status=202,
                    create=create,
                )

        async with asyncio.timeout(10):
            first = asyncio.create_task(run(True))
            await entered.wait()
            second = asyncio.create_task(run(False))
            release.set()
            results = await asyncio.gather(first, second)
        assert results[0].resource_id == results[1].resource_id
        assert [r.replayed for r in results] == [False, True]
        assert len(calls) == 1
    finally:
        await engine.dispose()


async def test_event_paging_and_same_scan_provenance(
    db: AsyncSession, two_organizations
) -> None:
    from factories import evidence_graph

    from aegis_api.conventions import EventQuery
    from aegis_api.db.models import FindingOccurrence, PolicyEvaluation, Report

    a, b = two_organizations
    graph = await evidence_graph(db, a)
    item = next(r for r in graph if isinstance(r, Scan))
    occurrence = next(r for r in graph if isinstance(r, FindingOccurrence))
    evaluation = next(r for r in graph if isinstance(r, PolicyEvaluation))
    another_scan = scan(*a)
    db.add(another_scan)
    await db.flush()
    # Same organization is insufficient: artifact/evaluation provenance must
    # still point to the correct scan.
    values = {
        c.name: getattr(occurrence, c.name) for c in FindingOccurrence.__table__.columns
    }
    values.update(id=uuid4(), scan_id=another_scan.id)
    async with rejected(db):
        db.add(FindingOccurrence(**values))
        await db.flush()
    async with rejected(db):
        db.add(
            Report(
                organization_id=a[0].id,
                scan_id=another_scan.id,
                evaluation_id=evaluation.id,
                format="json",
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        await db.flush()
    codec = CursorCodec(b"synthetic-test-only-signing-key-000")
    repo = TimelineRepository(db, TenantScope(a[0].id), ScanEvent)
    rows, page = await repo.page(EventQuery(scan_id=item.id, limit=1), codec)
    assert len(rows) == 1 and rows[0].sequence == 1 and not page.has_more
    foreign_repo = TimelineRepository(db, TenantScope(b[0].id), ScanEvent)
    rows, _ = await foreign_repo.page(EventQuery(scan_id=item.id), codec)
    assert rows == []
