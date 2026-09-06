"""Regression reproductions from the strict Phase 4 review."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from factories import scan, tenant
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aegis_api.conventions import APIError
from aegis_api.db.enums import Completeness, EnrichmentState, PolicyOutcome, ScanState
from aegis_api.db.models import IdempotencyRecord, PolicyEvaluation, Project
from aegis_api.db.repository import TenantScope
from aegis_api.db.service import CommandService

pytestmark = pytest.mark.integration


async def test_failed_callback_cannot_leave_success_receipt(
    db: AsyncSession, two_organizations
) -> None:
    org, member, _, _ = two_organizations[0]
    resource_id = uuid4()
    service = CommandService(db, TenantScope(org.id), member.id)

    async def fail(record_id: UUID) -> None:
        db.add(
            Project(
                id=record_id,
                organization_id=org.id,
                name="Synthetic partial command",
                created_by_id=member.id,
            )
        )
        await db.flush()
        raise RuntimeError("Synthetic callback failure")

    # Deliberately catch the exception without a caller-created savepoint.
    # The service must not retain either partial work or a successful receipt.
    with pytest.raises(RuntimeError):
        await service.execute(
            operation="POST /api/v1/scans",
            key="review-failure",
            digest="0" * 64,
            resource_id=resource_id,
            status=202,
            create=fail,
        )
    assert (
        await db.scalar(
            select(IdempotencyRecord.id).where(
                IdempotencyRecord.organization_id == org.id,
                IdempotencyRecord.resource_id == resource_id,
            )
        )
        is None
    )
    assert (
        await db.scalar(
            select(Project.id).where(
                Project.organization_id == org.id, Project.id == resource_id
            )
        )
        is None
    )


async def test_locked_receipt_refreshes_cached_expired_row(
    migrated_database: str,
) -> None:
    engine = create_async_engine(migrated_database, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as setup:
            org, member, _, _ = await tenant(setup)
            receipt = IdempotencyRecord(
                organization_id=org.id,
                actor_id=member.id,
                operation="POST /api/v1/scans",
                key_hash=hashlib.sha256(b"review-cached").hexdigest(),
                request_digest="0" * 64,
                resource_id=uuid4(),
                response_status=202,
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
            setup.add(receipt)
        async with sessions.begin() as stale_session:
            cached = await stale_session.get(IdempotencyRecord, receipt.id)
            assert cached is not None
            renewed_id = uuid4()
            async with sessions.begin() as renewal:
                await renewal.execute(
                    update(IdempotencyRecord)
                    .where(
                        IdempotencyRecord.organization_id == org.id,
                        IdempotencyRecord.id == receipt.id,
                    )
                    .values(
                        resource_id=renewed_id,
                        expires_at=datetime.now(UTC) + timedelta(hours=24),
                    )
                )
            calls: list[UUID] = []

            async def create(resource_id: UUID) -> None:
                calls.append(resource_id)

            result = await CommandService(
                stale_session, TenantScope(org.id), member.id
            ).execute(
                operation="POST /api/v1/scans",
                key="review-cached",
                digest="0" * 64,
                resource_id=uuid4(),
                status=202,
                create=create,
            )
            assert result.replayed and result.resource_id == renewed_id
            assert calls == []
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "state,completeness,enrichment",
    [
        (ScanState.FAILED, Completeness.NONE, EnrichmentState.DEGRADED),
        (ScanState.CANCELLED, Completeness.PARTIAL, EnrichmentState.COMPLETE),
        (ScanState.TIMED_OUT, Completeness.NONE, EnrichmentState.COMPLETE),
        (ScanState.COMPLETED, Completeness.PARTIAL, EnrichmentState.COMPLETE),
        (ScanState.COMPLETED, Completeness.COMPLETE, EnrichmentState.DEGRADED),
        (ScanState.DRAFT, Completeness.UNKNOWN, EnrichmentState.PENDING),
        (ScanState.EVALUATING_POLICY, Completeness.COMPLETE, EnrichmentState.COMPLETE),
    ],
)
async def test_passing_snapshot_cannot_disagree_with_scan(
    db: AsyncSession,
    two_organizations,
    state: ScanState,
    completeness: Completeness,
    enrichment: EnrichmentState,
) -> None:
    context = two_organizations[0]
    item = scan(*context)
    item.state, item.completeness, item.enrichment_status = (
        state,
        completeness,
        enrichment,
    )
    db.add(item)
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                PolicyEvaluation(
                    organization_id=context[0].id,
                    scan_id=item.id,
                    policy_id=context[3].id,
                    input_digest="0" * 64,
                    evaluation_version="synthetic-review",
                    outcome=PolicyOutcome.PASS,
                    reason_codes=[],
                    scan_state=ScanState.COMPLETED,
                    completeness=Completeness.COMPLETE,
                    enrichment_status=EnrichmentState.COMPLETE,
                )
            )
            await db.flush()


@pytest.mark.parametrize(
    "state",
    [ScanState.EVALUATING_POLICY, ScanState.GENERATING_REPORT, ScanState.COMPLETED],
)
async def test_passing_evaluation_accepts_matching_complete_scan(
    db: AsyncSession,
    two_organizations,
    state: ScanState,
) -> None:
    context = two_organizations[0]
    item = scan(*context)
    item.state = state
    item.completeness = Completeness.COMPLETE
    item.enrichment_status = EnrichmentState.COMPLETE
    db.add(item)
    await db.flush()
    evaluation = PolicyEvaluation(
        organization_id=context[0].id,
        scan_id=item.id,
        policy_id=context[3].id,
        input_digest="0" * 64,
        evaluation_version="synthetic-review",
        outcome=PolicyOutcome.PASS,
        reason_codes=[],
        scan_state=state,
        completeness=Completeness.COMPLETE,
        enrichment_status=EnrichmentState.COMPLETE,
    )
    db.add(evaluation)
    await db.flush()
    assert evaluation.id is not None


async def test_failed_scan_can_record_failure(
    db: AsyncSession, two_organizations
) -> None:
    context = two_organizations[0]
    item = scan(*context)
    item.state, item.completeness = ScanState.FAILED, Completeness.PARTIAL
    db.add(item)
    await db.flush()
    evaluation = PolicyEvaluation(
        organization_id=context[0].id,
        scan_id=item.id,
        policy_id=context[3].id,
        input_digest="0" * 64,
        evaluation_version="synthetic-review",
        outcome=PolicyOutcome.FAIL,
        reason_codes=["synthetic_failure"],
        scan_state=ScanState.FAILED,
        completeness=Completeness.PARTIAL,
        enrichment_status=EnrichmentState.PENDING,
    )
    db.add(evaluation)
    await db.flush()
    assert evaluation.id is not None


@pytest.mark.parametrize("key", [None, "", "contains space", "\n", "é", "x" * 201])
async def test_invalid_idempotency_keys_never_run_callback(
    db: AsyncSession,
    two_organizations,
    key: str | None,
) -> None:
    org, member, _, _ = two_organizations[0]
    calls: list[UUID] = []

    async def create(resource_id: UUID) -> None:
        calls.append(resource_id)

    with pytest.raises(APIError) as error:
        await CommandService(db, TenantScope(org.id), member.id).execute(
            operation="POST /api/v1/scans",
            key=key,
            digest="0" * 64,
            resource_id=uuid4(),
            status=202,
            create=create,
        )
    assert error.value.status == 400 and calls == []
    assert (
        await db.scalar(
            select(IdempotencyRecord.id).where(
                IdempotencyRecord.organization_id == org.id
            )
        )
        is None
    )


async def test_callback_retry_after_caught_failure(
    db: AsyncSession, two_organizations
) -> None:
    org, member, _, _ = two_organizations[0]
    service = CommandService(db, TenantScope(org.id), member.id)
    options = dict(
        operation="POST /api/v1/scans",
        key="review-retry",
        digest="0" * 64,
        resource_id=uuid4(),
        status=202,
    )

    async def failed_create(resource_id: UUID) -> None:
        raise RuntimeError("Synthetic pre-write failure")

    with pytest.raises(RuntimeError):
        await service.execute(**options, create=failed_create)

    async def successful_create(resource_id: UUID) -> None:
        db.add(
            Project(
                id=resource_id,
                organization_id=org.id,
                name="Synthetic recovered command",
                created_by_id=member.id,
            )
        )

    result = await service.execute(**options, create=successful_create)
    assert not result.replayed
    replay = await service.execute(**options, create=successful_create)
    assert replay.replayed and replay.resource_id == result.resource_id
