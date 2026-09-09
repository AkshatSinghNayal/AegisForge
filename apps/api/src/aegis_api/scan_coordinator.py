"""API-side durable outbox/reconciler. Multiple instances serialize on DB locks.

Broker messages contain only opaque IDs and closed stage enums. Redis is transport,
not scan history. A committed stage/job/fence is the outbox record; unacknowledged
publishes reuse that job ID. Results can only advance its current fenced stage.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from celery import Celery
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aegis_api.auth import now
from aegis_api.conventions import APIError
from aegis_api.db.enums import (
    Completeness,
    EnrichmentState,
    RecordState,
    ReportState,
    ScanMode,
    ScanState,
)
from aegis_api.db.models import Organization, OrganizationMember, Scan, ScanEvent
from aegis_api.scan_lifecycle import PATH, SAFE_RETRY, TERMINAL, event, transition
from aegis_api.scanner import StageRequest, StageResult
from aegis_api.scans import ScanInput, validate
from aegis_api.settings import Settings


class Broker:
    def __init__(self, config: Settings) -> None:
        url = config.redis_url.get_secret_value()
        self.url = url
        self.app = Celery("scan_dispatch", broker=url, backend=url)
        self.app.conf.update(
            task_serializer="json",
            accept_content=["json"],
            result_serializer="json",
            task_publish_retry=False,
            broker_connection_timeout=2,
            broker_transport_options={"socket_connect_timeout": 2, "socket_timeout": 2},
            redis_socket_timeout=2,
            redis_socket_connect_timeout=2,
        )

    def publish(self, payload: StageRequest) -> None:
        data = payload.model_dump(mode="json")
        if payload.execution:
            data["execution"] = payload.execution.get_secret_value()
        self.app.send_task(
            "aegis.scan_stage",
            args=[data],
            queue="zap" if payload.execution else "celery",
            task_id=str(payload.job_id),
            retry=False,
        )

    def renew(self, job: "Job") -> None:
        from redis import Redis

        with Redis.from_url(
            self.url, socket_timeout=2, socket_connect_timeout=2
        ) as redis:
            redis.set(f"zap-lease:{job.job_id}", str(job.fence), ex=10)

    def progress(self, job_id: UUID) -> list[str]:
        from redis import Redis

        with Redis.from_url(
            self.url, socket_timeout=2, socket_connect_timeout=2
        ) as redis:
            return [v.decode() for v in redis.lrange(f"zap-progress:{job_id}", 0, 5)]

    def result(self, job_id: UUID) -> tuple[str, Any]:
        result = self.app.AsyncResult(str(job_id))
        state = str(result.state)
        return state, result.result if state == "SUCCESS" else None


async def current_authorization(db: AsyncSession, scan: Scan) -> bool:
    member = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == scan.organization_id,
            OrganizationMember.id == scan.initiator_id,
            OrganizationMember.status == RecordState.ACTIVE,
        )
    )
    if not member or scan.authorized_until <= now():
        return False
    try:
        target, _ = await validate(
            ScanInput(
                target_id=scan.target_id,
                target_version=scan.config_snapshot["target_version"],
                policy_id=scan.policy_id,
                policy_version=scan.config_snapshot["policy_version"],
                secret_reference_ids=scan.config_snapshot["secret_reference_ids"],
                active_acknowledgement=scan.mode == ScanMode.ACTIVE,
            ),
            member,
            db,
        )
        return (
            target.authorized_scope_digest == scan.authorization_scope_digest
            and target.authorization_actor_id == scan.authorization_actor_id
        )
    except (APIError, KeyError, ValidationError):
        return False


@dataclass(frozen=True)
class Job:
    organization_id: UUID
    scan_id: UUID
    job_id: UUID
    fence: int
    stage: ScanState
    demo: bool
    publish: bool
    execution: SecretStr | None = None
    real: bool = False


async def prepare(
    db: AsyncSession, scan: Scan, config: Settings | None = None
) -> "Job | None":
    if scan.state in TERMINAL:
        return None
    if scan.deadline_at <= now():
        transition(db, scan, ScanState.TIMED_OUT, "deadline_expired", now())
        return None
    if not await current_authorization(db, scan):
        transition(db, scan, ScanState.FAILED, "authorization_expired", now())
        return None
    if scan.state == ScanState.QUEUED:
        transition(db, scan, ScanState.VALIDATING_TARGET, "stage_started", now())
        return None
    if scan.state == ScanState.DRAFT:
        return None
    if not scan.job_id:
        # Commit this durable dispatch intent before making any broker call.
        scan.job_id = uuid4()
        return None
    execution = None
    real = bool(config and config.scanner_provider == "zap" and not scan.is_demo)
    if real and scan.dispatched_at is None:
        from aegis_api.zap_dispatch import envelope

        try:
            assert config
            execution = await envelope(db, scan, config)
        except Exception:
            transition(db, scan, ScanState.FAILED, "scanner_unavailable", now())
            return None
    return Job(
        scan.organization_id,
        scan.id,
        scan.job_id,
        scan.fence,
        scan.state,
        scan.is_demo,
        scan.dispatched_at is None,
        execution,
        real,
    )


async def perform(job: Job, broker: Broker) -> tuple[str, Any]:
    """Bound transport latency; never run while holding database locks."""
    try:
        if job.real:
            await asyncio.wait_for(asyncio.to_thread(broker.renew, job), timeout=3)
        if job.publish:
            await asyncio.wait_for(
                asyncio.to_thread(
                    broker.publish,
                    StageRequest(
                        scan_id=job.scan_id,
                        job_id=job.job_id,
                        fence=job.fence,
                        stage=job.stage,
                        demo=job.demo,
                        execution=job.execution,
                    ),
                ),
                timeout=3,
            )
            return "PUBLISHED", None
        outcome = await asyncio.wait_for(
            asyncio.to_thread(broker.result, job.job_id), timeout=3
        )
        if job.real and outcome[0] not in {"SUCCESS", "FAILURE"}:
            return "PROGRESS", await asyncio.wait_for(
                asyncio.to_thread(broker.progress, job.job_id),
                timeout=3,
            )
        return outcome
    except Exception:
        return "UNAVAILABLE", None


async def finish(
    db: AsyncSession, scan: Scan, job: Job, outcome: tuple[str, Any], config: Settings
) -> None:
    if scan.state in TERMINAL or (scan.job_id, scan.fence, scan.state) != (
        job.job_id,
        job.fence,
        job.stage,
    ):
        return  # Cancelled, timed out, or another coordinator already advanced it.
    if scan.deadline_at <= now():
        transition(db, scan, ScanState.TIMED_OUT, "deadline_expired", now())
        return
    if not await current_authorization(db, scan):
        transition(db, scan, ScanState.FAILED, "authorization_expired", now())
        return
    fence, job_id = scan.fence, scan.job_id
    status, payload = outcome
    if job.publish:
        if status == "PUBLISHED" and scan.dispatched_at is None:
            scan.dispatched_at = now()
        elif status != "PUBLISHED" and scan.dispatched_at is None:
            last_code = await db.scalar(
                select(ScanEvent.message_code)
                .where(
                    ScanEvent.organization_id == scan.organization_id,
                    ScanEvent.scan_id == scan.id,
                )
                .order_by(ScanEvent.sequence.desc())
                .limit(1)
            )
            if last_code != "dispatch_retry":
                event(db, scan, "dispatch_retry")
        return
    assert scan.dispatched_at is not None
    if status == "PROGRESS" and job.real:
        from aegis_api.zap_dispatch import progress

        try:
            await progress(db, scan, payload)
        except (ValueError, TypeError):
            transition(db, scan, ScanState.FAILED, "provider_failed", now())
        return
    if status == "SUCCESS":
        try:
            result = StageResult.model_validate(payload)
            if (result.scan_id, result.job_id, result.fence, result.stage) != (
                scan.id,
                job_id,
                fence,
                ScanState.VALIDATING_TARGET if job.real else scan.state,
            ):
                raise ValueError("Stale result")
        except (ValidationError, ValueError):
            transition(
                db, scan, ScanState.FAILED, "invalid_fixture", now(), fence=fence
            )
            return
        if result.status != "ok":
            transition(db, scan, ScanState.FAILED, result.status, now(), fence=fence)
            return
        if job.real:
            from aegis_api.zap_dispatch import collected

            try:
                if result.fixture_version != "zap-v1" or result.artifact is None:
                    raise ValueError("Missing scanner evidence")
                await collected(db, scan, result.artifact)
            except ValueError:
                transition(db, scan, ScanState.FAILED, "provider_failed", now())
            return
        # Only mock fixtures exist in Phase 7; untrusted result data cannot assert
        # completeness, findings, evaluation or report availability.
        if not scan.is_demo:
            transition(
                db, scan, ScanState.FAILED, "scanner_unavailable", now(), fence=fence
            )
            return
        destination = PATH[PATH.index(scan.state) + 1]
        if scan.state == ScanState.PASSIVE_SCANNING and scan.mode != ScanMode.ACTIVE:
            destination = ScanState.COLLECTING_RESULTS
        if scan.state == ScanState.COLLECTING_RESULTS:
            scan.mock_manifest = {
                "schema": "mock-v1",
                "is_demo": True,
                "coverage": "simulated",
                "observations": [],
                "security_evidence": False,
            }
        if scan.state == ScanState.NORMALIZING:
            scan.completeness = Completeness.PARTIAL
        if scan.state == ScanState.ENRICHING:
            scan.enrichment_status = EnrichmentState.MOCK
        if scan.state == ScanState.EVALUATING_POLICY:
            scan.mock_manifest = {
                **(scan.mock_manifest or {}),
                "evaluation": {
                    "outcome": "fail",
                    "reason": "demo_not_security_evidence",
                },
            }
        if scan.state == ScanState.GENERATING_REPORT:
            scan.report_status = ReportState.FAILED
            scan.mock_manifest = {
                **(scan.mock_manifest or {}),
                "report": "Mock lifecycle completed; no security report generated.",
            }
        transition(
            db,
            scan,
            destination,
            "demo_completed" if destination == ScanState.COMPLETED else "stage_started",
            now(),
            fence=fence,
        )
        return
    expired = (
        now() - scan.dispatched_at
    ).total_seconds() >= config.scan_stage_timeout_seconds
    if status == "FAILURE" or (expired and not job.real):
        if not job.real and scan.state in SAFE_RETRY and scan.stage_attempt < 3:
            scan.stage_attempt += 1
            scan.fence += 1
            scan.version += 1
            scan.job_id, scan.dispatched_at = None, None
            event(db, scan, "safe_retry")
        else:
            transition(db, scan, ScanState.FAILED, "worker_lost", now(), fence=fence)


async def tick(
    sessions: async_sessionmaker[AsyncSession], broker: Broker, config: Settings
) -> None:
    async with sessions() as db:
        candidates = list(
            (
                await db.execute(
                    select(Scan.organization_id, Scan.id)
                    .where(Scan.state.not_in(TERMINAL))
                    .order_by(Scan.deadline_at, Scan.updated_at, Scan.id)
                    .limit(100)
                )
            ).all()
        )
    for organization_id, scan_id in candidates:
        job = None
        async with sessions.begin() as db:
            org = await db.scalar(
                select(Organization)
                .where(Organization.id == organization_id)
                .with_for_update(skip_locked=True)
            )
            if not org:
                continue
            scan = await db.scalar(
                select(Scan)
                .where(Scan.organization_id == organization_id, Scan.id == scan_id)
                .with_for_update(skip_locked=True)
            )
            if scan is None or scan.state in TERMINAL:
                continue
            if org.status != RecordState.ACTIVE:
                transition(db, scan, ScanState.FAILED, "authorization_expired", now())
            else:
                job = await prepare(db, scan, config)
        if job is None:
            continue
        outcome = await perform(job, broker)
        # Reacquire in the same organization -> scan order, and reject stale I/O.
        async with sessions.begin() as db:
            org = await db.scalar(
                select(Organization)
                .where(Organization.id == organization_id)
                .with_for_update()
            )
            scan = await db.scalar(
                select(Scan)
                .where(Scan.organization_id == organization_id, Scan.id == scan_id)
                .with_for_update()
            )
            if not org or not scan or scan.state in TERMINAL:
                continue
            if org.status != RecordState.ACTIVE:
                transition(db, scan, ScanState.FAILED, "authorization_expired", now())
            else:
                await finish(db, scan, job, outcome, config)


async def coordinate(
    sessions: async_sessionmaker[AsyncSession], config: Settings
) -> None:
    broker = Broker(config)
    try:
        while True:
            try:
                await tick(sessions, broker, config)
            except Exception:
                # Database outages roll back and retry; durable deadlines remain.
                logging.getLogger("aegis.scans").error(
                    "", extra={"event": "scan_coordinator_unavailable"}
                )
            await asyncio.sleep(0.5)
    finally:
        broker.app.close()
