"""Authorized scan commands, durable outbox checkpoints and replayable SSE."""

import asyncio
import hashlib
import json
import secrets
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from starlette.responses import StreamingResponse

from aegis_api.auth import DB, Payload, csrf, now, principal
from aegis_api.configuration import get_policy, scoped_target
from aegis_api.conventions import APIError
from aegis_api.db.enums import RecordState, ScanMode, ScanState
from aegis_api.db.models import (
    OrganizationMember,
    Project,
    ProjectMember,
    Scan,
    ScanConfirmation,
    ScanEvent,
    ScanPolicy,
    Target,
    TargetSecretReference,
    User,
)
from aegis_api.db.repository import TenantScope
from aegis_api.db.service import CommandService
from aegis_api.organizations import ADMIN, Member, membership, require
from aegis_api.scan_lifecycle import TERMINAL, transition

router = APIRouter(prefix="/api/v1/scans", tags=["scans"])
WRITE = [Depends(csrf)]


class Trigger(Payload):
    source: Literal["manual", "ci"] = "manual"
    branch: str | None = Field(
        default=None, max_length=120, pattern=r"^[A-Za-z0-9._/\-]+$"
    )
    commit: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{7,40}$")


class ScanInput(Payload):
    target_id: UUID
    target_version: int = Field(ge=1)
    policy_id: UUID
    policy_version: int = Field(ge=1)
    secret_reference_ids: list[UUID] = Field(default_factory=list, max_length=20)
    trigger: Trigger = Field(default_factory=Trigger)
    active_acknowledgement: bool = False
    confirmation_token: str | None = Field(default=None, min_length=32, max_length=100)


def fingerprint(body: ScanInput) -> str:
    return hashlib.sha256(
        json.dumps(
            body.model_dump(mode="json", exclude={"confirmation_token"}), sort_keys=True
        ).encode()
    ).hexdigest()


class ConfirmationView(BaseModel):
    token: str
    expires_at: datetime


class ScanView(BaseModel):
    id: UUID
    state: ScanState
    mode: ScanMode
    target: str
    target_id: UUID
    project: str
    project_id: UUID
    initiator: str
    trigger: Trigger
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    deadline_at: datetime
    completeness: str
    enrichment_status: str
    report_status: str
    is_demo: bool
    effective_gate: Literal["warn", "fail"]
    gate_reason: str
    failure_code: str | None


class EventView(BaseModel):
    sequence: int
    stage: ScanState
    message_code: str
    attempt: int
    created_at: datetime


async def validate(
    body: ScanInput, member: OrganizationMember, db: DB
) -> tuple[Target, ScanPolicy]:
    require(member, "scans.write")
    target = await scoped_target(body.target_id, member, db, True)
    policy = await get_policy(body.policy_id, member, db)
    if (
        target.status != RecordState.ACTIVE
        or not target.verified_at
        or not target.consent_at
        or not target.authorized_until
        or target.authorized_until <= now()
        or not target.authorized_scope_digest
        or not target.authorization_actor_id
    ):
        raise APIError(
            409,
            "target_unauthorized",
            "Target needs current authorization and verification.",
        )
    owner = await db.scalar(
        select(OrganizationMember.id).where(
            OrganizationMember.organization_id == member.organization_id,
            OrganizationMember.id == target.authorization_actor_id,
            OrganizationMember.status == RecordState.ACTIVE,
        )
    )
    if not owner:
        raise APIError(
            409, "target_unauthorized", "Target authorization owner is inactive."
        )
    if target.version != body.target_version or policy.version != body.policy_version:
        raise APIError(
            409,
            "configuration_changed",
            "Review the current target and policy versions.",
        )
    if policy.mode == ScanMode.ACTIVE and not body.active_acknowledgement:
        raise APIError(
            422,
            "active_confirmation_required",
            "Acknowledge active scan traffic before continuing.",
        )
    refs = list(
        (
            await db.scalars(
                select(TargetSecretReference).where(
                    TargetSecretReference.organization_id == member.organization_id,
                    TargetSecretReference.target_id == target.id,
                    TargetSecretReference.id.in_(body.secret_reference_ids),
                    TargetSecretReference.revoked_at.is_(None),
                )
            )
        ).all()
    )
    if len(refs) != len(body.secret_reference_ids) or any(
        not ref.secret_provider_ref or not ref.ciphertext for ref in refs
    ):
        raise APIError(
            409,
            "secret_unavailable",
            "Selected credentials are unavailable or revoked.",
        )
    return target, policy


async def resource(
    scan_id: UUID, member: OrganizationMember, db: DB, lock: bool = False
) -> Scan:
    query = select(Scan).where(
        Scan.organization_id == member.organization_id, Scan.id == scan_id
    )
    scan = await db.scalar(query.with_for_update() if lock else query)
    if not scan:
        raise APIError(404, "not_found", "Scan not found.")
    await scoped_target(scan.target_id, member, db)
    return scan


async def view(scan: Scan, db: DB) -> ScanView:
    target = await db.scalar(
        select(Target).where(
            Target.organization_id == scan.organization_id, Target.id == scan.target_id
        )
    )
    assert target
    project = await db.scalar(
        select(Project).where(
            Project.organization_id == scan.organization_id,
            Project.id == target.project_id,
        )
    )
    name = await db.scalar(
        select(User.display_name)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(
            OrganizationMember.organization_id == scan.organization_id,
            OrganizationMember.id == scan.initiator_id,
        )
    )
    return ScanView(
        id=scan.id,
        state=scan.state,
        mode=scan.mode,
        target=target.display_name,
        target_id=target.id,
        project=project.name if project else "Unavailable",
        project_id=target.project_id,
        initiator=name or "System",
        trigger=Trigger.model_validate(scan.trigger_metadata),
        created_at=scan.created_at,
        started_at=scan.started_at,
        finished_at=scan.finished_at,
        deadline_at=scan.deadline_at,
        completeness=scan.completeness,
        enrichment_status=scan.enrichment_status,
        report_status=scan.report_status,
        is_demo=scan.is_demo,
        effective_gate="fail",
        gate_reason="demo_not_security_evidence"
        if scan.is_demo and scan.state == ScanState.COMPLETED
        else "evaluation_unavailable",
        failure_code=scan.failure_code,
    )


@router.post("/confirmations", response_model=ConfirmationView, dependencies=WRITE)
async def confirmation(body: ScanInput, member: Member, db: DB) -> ConfirmationView:
    _, policy = await validate(body, member, db)
    if policy.mode != ScanMode.ACTIVE:
        raise APIError(
            422, "active_only", "Only active scans require this confirmation."
        )
    token = secrets.token_urlsafe(32)
    expires = now() + timedelta(minutes=5)
    db.add(
        ScanConfirmation(
            organization_id=member.organization_id,
            actor_id=member.id,
            request_digest=fingerprint(body),
            token_digest=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=expires,
        )
    )
    await db.commit()
    return ConfirmationView(token=token, expires_at=expires)


@router.post("", response_model=ScanView, status_code=202, dependencies=WRITE)
async def create_scan(
    body: ScanInput,
    request: Request,
    member: Member,
    db: DB,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> ScanView:
    require(member, "scans.write")

    async def create(id: UUID) -> None:
        target, policy = await validate(body, member, db)
        cfg = request.app.state.config
        running = await db.scalar(
            select(func.count())
            .select_from(Scan)
            .where(
                Scan.organization_id == member.organization_id,
                Scan.state.not_in(TERMINAL),
            )
        )
        daily = await db.scalar(
            select(func.count())
            .select_from(Scan)
            .where(
                Scan.organization_id == member.organization_id,
                Scan.created_at > now() - timedelta(days=1),
            )
        )
        if (running or 0) >= cfg.scan_concurrency or (
            daily or 0
        ) >= cfg.scan_daily_quota:
            raise APIError(
                429, "scan_quota", "Scan concurrency or daily quota reached."
            )
        grant_digest = None
        if policy.mode == ScanMode.ACTIVE:
            grant_digest = hashlib.sha256(
                (body.confirmation_token or "").encode()
            ).hexdigest()
            grant = await db.scalar(
                select(ScanConfirmation)
                .where(
                    ScanConfirmation.organization_id == member.organization_id,
                    ScanConfirmation.actor_id == member.id,
                    ScanConfirmation.token_digest == grant_digest,
                    ScanConfirmation.request_digest == fingerprint(body),
                    ScanConfirmation.consumed_at.is_(None),
                    ScanConfirmation.expires_at > now(),
                )
                .with_for_update()
            )
            if not grant:
                raise APIError(
                    409,
                    "confirmation_invalid",
                    "Active confirmation expired, changed or was already used.",
                )
            grant.consumed_at = now()
        assert (
            target.authorized_until
            and target.authorization_actor_id
            and target.authorized_scope_digest
        )
        scan = Scan(
            id=id,
            organization_id=member.organization_id,
            target_id=target.id,
            policy_id=policy.id,
            mode=policy.mode,
            state=ScanState.DRAFT,
            initiator_id=member.id,
            trigger_metadata=body.trigger.model_dump(),
            snapshot_schema_version="scan-v1",
            config_snapshot={
                "target_version": target.version,
                "policy_version": policy.version,
                "policy": policy.rules_snapshot,
                "secret_reference_ids": [str(x) for x in body.secret_reference_ids],
            },
            authorization_snapshot={"method": target.authorization_method},
            authorization_actor_id=target.authorization_actor_id,
            authorized_until=target.authorized_until,
            authorization_scope_digest=target.authorized_scope_digest,
            active_confirmation_digest=grant_digest,
            deadline_at=now() + timedelta(seconds=policy.max_duration_seconds),
            is_demo=cfg.scanner_provider == "mock"
            and (cfg.demo_mode or cfg.profile == "test"),
            next_sequence=1,
            stage_attempt=1,
            version=1,
            fence=0,
        )
        db.add(scan)
        transition(db, scan, ScanState.QUEUED, "queued", now())

    result = await CommandService(
        db, TenantScope(member.organization_id), member.id
    ).execute(
        operation="POST /api/v1/scans",
        key=idempotency_key,
        digest=fingerprint(body),
        resource_id=uuid4(),
        status=202,
        create=create,
    )
    scan = await resource(result.resource_id, member, db)
    await db.commit()
    return await view(scan, db)


@router.get("", response_model=list[ScanView])
async def list_scans(member: Member, db: DB) -> list[ScanView]:
    query = (
        select(Scan)
        .join(
            Target,
            (Target.id == Scan.target_id)
            & (Target.organization_id == Scan.organization_id),
        )
        .where(Scan.organization_id == member.organization_id)
    )
    if member.role not in ADMIN:
        query = query.where(
            Target.project_id.in_(
                select(ProjectMember.project_id).where(
                    ProjectMember.organization_id == member.organization_id,
                    ProjectMember.member_id == member.id,
                    ProjectMember.status == RecordState.ACTIVE,
                )
            )
        )
    rows = (
        await db.scalars(
            query.order_by(Scan.created_at.desc(), Scan.id.desc()).limit(200)
        )
    ).all()
    return [await view(row, db) for row in rows]


@router.get("/{scan_id}", response_model=ScanView)
async def detail(scan_id: UUID, member: Member, db: DB) -> ScanView:
    return await view(await resource(scan_id, member, db), db)


@router.post("/{scan_id}/cancel", response_model=ScanView, dependencies=WRITE)
async def cancel(scan_id: UUID, member: Member, db: DB) -> ScanView:
    require(member, "scans.write")
    scan = await resource(scan_id, member, db, True)
    transition(db, scan, ScanState.CANCELLED, "cancelled", now())
    scan.cancellation_requested_at = now()
    await db.commit()
    return await view(scan, db)


@router.get("/{scan_id}/events", response_class=StreamingResponse)
async def events(
    scan_id: UUID,
    request: Request,
    member: Member,
    db: DB,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    scan = await resource(scan_id, member, db)
    if last_event_id is not None and (
        not last_event_id.isascii()
        or not last_event_id.isdigit()
        or len(last_event_id) > 18
    ):
        raise APIError(
            400, "invalid_event_cursor", "Last-Event-ID must be an event sequence."
        )
    cursor = int(last_event_id or 0)
    if cursor >= scan.next_sequence:
        raise APIError(409, "event_cursor_ahead", "Event cursor is ahead of this scan.")
    organization_id = member.organization_id
    await db.rollback()  # Never retain an organization lock for a streaming connection.

    async def stream() -> AsyncIterator[str]:
        nonlocal cursor
        # Bounded streams force credential refresh; each read rechecks revocation/RBAC.
        for _ in range(25):
            if await request.is_disconnected():
                return
            async with request.app.state.sessions() as session:
                try:
                    actor = await principal(request, session)
                    current = await membership(organization_id, actor, session)
                    row = await resource(scan_id, current, session)
                except APIError as error:
                    kind = (
                        "session_expired" if error.status == 401 else "access_revoked"
                    )
                    yield f"event: {kind}\ndata: {{}}\n\n"
                    return
                batch = list(
                    (
                        await session.scalars(
                            select(ScanEvent)
                            .where(
                                ScanEvent.organization_id == current.organization_id,
                                ScanEvent.scan_id == scan_id,
                                ScanEvent.sequence > cursor,
                            )
                            .order_by(ScanEvent.sequence)
                            .limit(100)
                        )
                    ).all()
                )
                terminal = row.state in TERMINAL
                frames = []
                for item in batch:
                    payload = EventView(
                        sequence=item.sequence,
                        stage=item.stage,
                        message_code=item.message_code,
                        attempt=item.attempt,
                        created_at=item.created_at,
                    )
                    cursor = item.sequence
                    frames.append(
                        f"id: {cursor}\nevent: scan\n"
                        f"data: {payload.model_dump_json()}\n\n"
                    )
            for frame in frames:
                yield frame
            if terminal and len(batch) < 100:
                yield "event: end\ndata: {}\n\n"
                return
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
    )
