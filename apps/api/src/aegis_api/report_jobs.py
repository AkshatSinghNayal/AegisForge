"""Durable database jobs on the API side; never grant scanner workers DB access."""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import String, case, cast, exists, literal, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from aegis_api.auth import now
from aegis_api.db.enums import NotificationState, RecordState, ReportState, ScanState
from aegis_api.db.models import (
    Finding,
    GateActivation,
    GatePolicy,
    NotificationDelivery,
    NotificationDestination,
    Organization,
    PolicyEvaluation,
    Report,
    Scan,
    Target,
)
from aegis_api.notifications import EventKind, NotificationPayload, send
from aegis_api.policy_engine import Policy
from aegis_api.reporting import ReportStore, Snapshot, render
from aegis_api.settings import Settings


async def generate_one(db: AsyncSession, config: Settings) -> bool:
    row = await db.scalar(
        select(Report)
        .where(Report.state == ReportState.PENDING)
        .order_by(Report.created_at, Report.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if row is None:
        return False
    try:
        if row.expires_at <= now():
            row.state = ReportState.EXPIRED
            await sync_scan_status(db, row)
            return True
        snapshot = Snapshot.model_validate(row.snapshot)
        if (
            snapshot.organization_id != row.organization_id
            or snapshot.scan_id != row.scan_id
        ):
            raise ValueError("Snapshot scope mismatch")
        data = await asyncio.to_thread(render, snapshot, row.format)
        content_type = "application/pdf" if row.format == "pdf" else "application/json"
        # A new random object key per attempt prevents a crashed writer from
        # overwriting an immutable object. Bucket lifecycle reclaims orphans.
        key = f"{row.organization_id}/{row.id}/{uuid4()}.{row.format}"
        await asyncio.to_thread(ReportStore(config).write, key, data, content_type)
        row.object_key = key
        row.content_hash = hashlib.sha256(data).hexdigest()
        row.content_type = content_type
        row.redaction_version = "classification-v1"
        row.state = ReportState.COMPLETE
    except Exception:
        row.state = ReportState.FAILED
        row.failure_code = "generation_failed"
    await sync_scan_status(db, row)
    return True


async def sync_scan_status(db: AsyncSession, row: Report) -> None:
    # Serialize with report creation before deciding which version is latest.
    scan = await db.scalar(
        select(Scan)
        .where(Scan.organization_id == row.organization_id, Scan.id == row.scan_id)
        .with_for_update()
    )
    latest = await db.scalar(
        select(Report.id)
        .where(
            Report.organization_id == row.organization_id, Report.scan_id == row.scan_id
        )
        .order_by(Report.version.desc())
        .limit(1)
    )
    if scan and latest == row.id:
        scan.report_status = row.state


async def enqueue(
    db: AsyncSession,
    config: Settings,
    destination: NotificationDestination,
    kind: EventKind,
    identity: UUID,
    project_id: UUID,
    occurred_at: datetime,
    suffix: str = "",
) -> None:
    if (
        kind not in destination.subscriptions
        or (destination.project_id and destination.project_id != project_id)
        or occurred_at < destination.created_at
    ):
        return
    key = f"{kind}:{identity}{suffix}"
    # Links contain only server-owned IDs and event constants, never scan strings.
    route = (
        "reports"
        if kind == "report.ready"
        else "findings"
        if kind == "finding.high"
        else "policies"
        if kind == "exception.expiring"
        else "scans"
    )
    payload = NotificationPayload(
        event=kind,
        organization_id=destination.organization_id,
        resource_id=identity,
        link=f"{config.app_origin}/app/{route}?organization={destination.organization_id}",
    )
    await db.execute(
        insert(NotificationDelivery)
        .values(
            id=uuid4(),
            organization_id=destination.organization_id,
            destination_id=destination.id,
            event_key=key,
            event_id=None,
            template_version="notification-v1",
            payload=payload.model_dump(mode="json"),
            state=NotificationState.PENDING,
            attempts=0,
            next_attempt_at=now(),
        )
        .on_conflict_do_nothing(
            index_elements=["organization_id", "destination_id", "event_key"]
        )
    )


def unseen(
    destination: NotificationDestination,
    kind: str | ColumnElement[str],
    identity: InstrumentedAttribute[UUID],
) -> ColumnElement[bool]:
    prefix = literal(kind) if isinstance(kind, str) else kind
    return ~exists(
        select(NotificationDelivery.id).where(
            NotificationDelivery.organization_id == destination.organization_id,
            NotificationDelivery.destination_id == destination.id,
            NotificationDelivery.event_key
            == prefix + literal(":") + cast(identity, String),
        )
    )


async def fanout(db: AsyncSession, config: Settings) -> None:
    destinations = (
        await db.scalars(
            select(NotificationDestination)
            .join(
                Organization, Organization.id == NotificationDestination.organization_id
            )
            .where(
                NotificationDestination.enabled.is_(True),
                Organization.status == RecordState.ACTIVE,
            )
        )
    ).all()
    for dest in destinations:
        org = dest.organization_id
        scans = (
            await db.execute(
                select(Scan, Target.project_id)
                .join(
                    Target,
                    (Target.organization_id == Scan.organization_id)
                    & (Target.id == Scan.target_id),
                )
                .where(
                    Scan.organization_id == org,
                    Scan.finished_at >= dest.created_at,
                    Scan.state.in_(
                        [
                            ScanState.COMPLETED,
                            ScanState.FAILED,
                            ScanState.CANCELLED,
                            ScanState.TIMED_OUT,
                        ]
                    ),
                    or_(
                        Target.project_id == dest.project_id,
                        literal(dest.project_id is None),
                    ),
                    case(
                        (Scan.state == ScanState.COMPLETED, "scan.completed"),
                        else_="scan.failed",
                    ).in_(dest.subscriptions),
                    unseen(
                        dest,
                        case(
                            (Scan.state == ScanState.COMPLETED, "scan.completed"),
                            else_="scan.failed",
                        ),
                        Scan.id,
                    ),
                )
                .order_by(Scan.finished_at, Scan.id)
                .limit(100)
            )
        ).all()
        for scan, project in scans:
            if scan.state in {
                ScanState.COMPLETED,
                ScanState.FAILED,
                ScanState.CANCELLED,
                ScanState.TIMED_OUT,
            }:
                await enqueue(
                    db,
                    config,
                    dest,
                    "scan.completed"
                    if scan.state == ScanState.COMPLETED
                    else "scan.failed",
                    scan.id,
                    project,
                    scan.finished_at,
                )
        evaluations = (
            await db.execute(
                select(PolicyEvaluation, Target.project_id)
                .join(
                    Scan,
                    (Scan.organization_id == PolicyEvaluation.organization_id)
                    & (Scan.id == PolicyEvaluation.scan_id),
                )
                .join(
                    Target,
                    (Target.organization_id == Scan.organization_id)
                    & (Target.id == Scan.target_id),
                )
                .where(
                    PolicyEvaluation.organization_id == org,
                    PolicyEvaluation.created_at >= dest.created_at,
                    PolicyEvaluation.outcome == "fail",
                    literal("policy.failed").in_(dest.subscriptions),
                    or_(
                        Target.project_id == dest.project_id,
                        literal(dest.project_id is None),
                    ),
                    unseen(dest, "policy.failed", PolicyEvaluation.id),
                )
                .order_by(PolicyEvaluation.created_at, PolicyEvaluation.id)
                .limit(100)
            )
        ).all()
        for evaluation, project in evaluations:
            await enqueue(
                db,
                config,
                dest,
                "policy.failed",
                evaluation.id,
                project,
                evaluation.created_at,
            )
        findings = (
            await db.execute(
                select(Finding, Target.project_id)
                .join(
                    Target,
                    (Target.organization_id == Finding.organization_id)
                    & (Target.id == Finding.target_id),
                )
                .where(
                    Finding.organization_id == org,
                    Finding.first_seen_at >= dest.created_at,
                    Finding.scanner_severity.in_(["high", "critical"]),
                    literal("finding.high").in_(dest.subscriptions),
                    or_(
                        Target.project_id == dest.project_id,
                        literal(dest.project_id is None),
                    ),
                    unseen(dest, "finding.high", Finding.id),
                )
                .order_by(Finding.first_seen_at, Finding.id)
                .limit(100)
            )
        ).all()
        for finding, project in findings:
            await enqueue(
                db,
                config,
                dest,
                "finding.high",
                finding.id,
                project,
                finding.first_seen_at,
            )
        reports = (
            await db.scalars(
                select(Report)
                .where(
                    Report.organization_id == org,
                    Report.state == ReportState.COMPLETE,
                    Report.snapshot["schema_version"].astext == "report-v1",
                    Report.updated_at >= dest.created_at,
                    literal("report.ready").in_(dest.subscriptions),
                    or_(
                        Report.snapshot["project_id"].astext == str(dest.project_id),
                        literal(dest.project_id is None),
                    ),
                    unseen(dest, "report.ready", Report.id),
                )
                .order_by(Report.created_at, Report.id)
                .limit(100)
            )
        ).all()
        for report in reports:
            snapshot = Snapshot.model_validate(report.snapshot)
            await enqueue(
                db,
                config,
                dest,
                "report.ready",
                report.id,
                snapshot.project_id,
                report.updated_at,
            )
        activations = (
            await db.scalars(
                select(GateActivation)
                .where(GateActivation.organization_id == org)
                .order_by(GateActivation.sequence.desc())
            )
        ).all()
        seen: set[UUID] = set()
        for activation in activations:
            if activation.project_id in seen:
                continue
            seen.add(activation.project_id)
            policy = await db.scalar(
                select(GatePolicy).where(
                    GatePolicy.organization_id == org,
                    GatePolicy.id == activation.gate_policy_id,
                )
            )
            if not policy:
                continue
            definition = Policy.model_validate(policy.snapshot)
            if not definition.allow_exceptions:
                continue
            for exception in definition.exceptions:
                if now() < exception.expires_at <= now() + timedelta(days=7):
                    await enqueue(
                        db,
                        config,
                        dest,
                        "exception.expiring",
                        policy.id,
                        policy.project_id,
                        now(),
                        f":{exception.finding_id}",
                    )


async def deliver_one(db: AsyncSession, config: Settings) -> bool:
    row = await db.scalar(
        select(NotificationDelivery)
        .where(
            NotificationDelivery.state.in_(
                [NotificationState.PENDING, NotificationState.FAILED]
            ),
            or_(
                NotificationDelivery.next_attempt_at.is_(None),
                NotificationDelivery.next_attempt_at <= now(),
            ),
        )
        .order_by(NotificationDelivery.created_at, NotificationDelivery.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if row is None:
        return False
    dest = await db.scalar(
        select(NotificationDestination)
        .where(
            NotificationDestination.organization_id == row.organization_id,
            NotificationDestination.id == row.destination_id,
        )
        .with_for_update()
    )
    active = await db.scalar(
        select(Organization.id).where(
            Organization.id == row.organization_id,
            Organization.status == RecordState.ACTIVE,
        )
    )
    row.attempts += 1
    try:
        if not dest or not dest.enabled or not active:
            raise ValueError("Destination disabled")
        payload = NotificationPayload.model_validate(row.payload)
        if payload.organization_id != row.organization_id:
            raise ValueError("Payload scope mismatch")
        await send(config, dest, payload, row.id)
        row.state = NotificationState.SENT
        row.failure_code = None
        row.next_attempt_at = None
    except Exception:
        row.state = (
            NotificationState.DEAD_LETTER
            if row.attempts >= 5
            else NotificationState.FAILED
        )
        row.failure_code = "delivery_failed"
        row.next_attempt_at = (
            now() + timedelta(seconds=min(3600, 30 * 2 ** min(row.attempts - 1, 7)))
            if row.state == NotificationState.FAILED
            else None
        )
    return True


async def expire_one(db: AsyncSession, config: Settings) -> None:
    row = await db.scalar(
        select(Report)
        .where(Report.expires_at <= now(), Report.state != ReportState.EXPIRED)
        .order_by(Report.expires_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if row:
        if row.object_key:
            await asyncio.to_thread(ReportStore(config).delete, row.object_key)
        row.state = ReportState.EXPIRED
        await sync_scan_status(db, row)


async def coordinate(
    sessions: async_sessionmaker[AsyncSession], config: Settings
) -> None:
    while True:
        try:
            async with sessions.begin() as db:
                await generate_one(db, config)
            async with sessions.begin() as db:
                await fanout(db, config)
            async with sessions.begin() as db:
                await deliver_one(db, config)
            async with sessions.begin() as db:
                await expire_one(db, config)
        except Exception:
            logging.getLogger("aegis.reporting").error(
                "", extra={"event": "report_jobs_unavailable"}
            )
        await asyncio.sleep(2)
