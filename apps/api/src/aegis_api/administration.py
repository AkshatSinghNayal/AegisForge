"""Organization administration: closed responses, current RBAC and audited reads."""

from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select, update

from aegis_api.admin_controls import Controls, controls
from aegis_api.auth import DB, Message, csrf, now
from aegis_api.auth_models import AccessCredential
from aegis_api.conventions import APIError
from aegis_api.db.enums import RecordState, Role
from aegis_api.db.models import (
    AuditLog,
    Organization,
    OrganizationMember,
    RefreshSession,
)
from aegis_api.logging import correlation_id
from aegis_api.organizations import ADMIN, Member, require, target_member

router = APIRouter(prefix="/api/v1/admin", tags=["administration"])


def audit(
    db: DB,
    member: Member,
    action: str,
    resource: str,
    identity: UUID,
    fields: list[str] | None = None,
    result: str = "success",
) -> None:
    try:
        request_id = UUID(correlation_id.get())
    except ValueError:
        request_id = uuid4()
    db.add(
        AuditLog(
            organization_id=member.organization_id,
            actor_id=member.id,
            action=action,
            resource_type=resource,
            resource_id=identity,
            request_id=request_id,
            changed_fields=fields or [],
            result=result,
        )
    )


async def admin_membership(member: Member, db: DB) -> OrganizationMember:
    if member.role not in ADMIN:
        audit(
            db,
            member,
            "administration.denied",
            "organization",
            member.organization_id,
            result="denied",
        )
        await db.commit()
        raise APIError(
            403, "forbidden", "Organization administration access is required."
        )
    return member


AdminMember = Annotated[OrganizationMember, Depends(admin_membership)]


@router.get("/controls", response_model=Controls)
async def get_controls(member: AdminMember, db: DB) -> Controls:
    require(member, "members.write")
    result = await controls(db, member.organization_id)
    audit(db, member, "administration.read", "organization", member.organization_id)
    await db.commit()
    return result


@router.put("/controls", response_model=Controls, dependencies=[Depends(csrf)])
async def set_controls(body: Controls, member: AdminMember, db: DB) -> Controls:
    require(member, "members.write")
    org = await db.get(Organization, member.organization_id)
    assert org
    from aegis_api.configuration import get_policy

    for identity in body.disabled_policy_ids:
        await get_policy(identity, member, db)
    before = await controls(db, member.organization_id)
    org.administration = body.model_dump(mode="json")
    org.version += 1
    fields = [
        key
        for key, value in body.model_dump().items()
        if before.model_dump()[key] != value
    ]
    audit(db, member, "administration.updated", "organization", org.id, fields)
    await db.commit()
    return body


@router.post(
    "/members/{member_id}/{operation}",
    response_model=Message,
    dependencies=[Depends(csrf)],
)
async def member_command(
    member_id: UUID,
    operation: Literal["activate", "revoke-sessions"],
    member: AdminMember,
    db: DB,
) -> Message:
    require(member, "members.write")
    target = await target_member(member_id, member, db)
    if target.role == Role.OWNER or (
        target.role == Role.ADMIN and member.role != Role.OWNER
    ):
        raise APIError(403, "forbidden", "Contact the organization owner.")
    if operation == "activate":
        target.status = RecordState.ACTIVE
        target.version += 1
    else:
        # Authentication sessions are global. Only the owner can deliberately
        # revoke these; this also signs the user out of their other organizations.
        if member.role != Role.OWNER:
            raise APIError(
                403, "forbidden", "Only the owner can revoke global sessions."
            )
        for model in (RefreshSession, AccessCredential):
            await db.execute(
                update(model)
                .where(model.user_id == target.user_id, model.revoked_at.is_(None))
                .values(revoked_at=now())
            )
    audit(db, member, "membership." + operation, "organization_member", target.id)
    await db.commit()
    return Message(
        message="Member updated."
        if operation == "activate"
        else "All user sessions revoked."
    )


class AuditView(BaseModel):
    organization_id: UUID
    id: UUID
    actor_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID
    request_id: UUID
    timestamp: datetime
    result: str
    source_ip: str | None
    changed_fields: list[str]


@router.get("/audit", response_model=list[AuditView])
async def audit_log(
    member: AdminMember,
    db: DB,
    action: Annotated[str | None, Query(max_length=100)] = None,
    actor_id: UUID | None = None,
    resource_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[AuditView]:
    require(member, "members.write")
    query = select(AuditLog).where(AuditLog.organization_id == member.organization_id)
    if action is not None:
        query = query.where(AuditLog.action == action)
    if actor_id is not None:
        query = query.where(AuditLog.actor_id == actor_id)
    if resource_id is not None:
        query = query.where(AuditLog.resource_id == resource_id)
    if since is not None:
        query = query.where(AuditLog.created_at >= since)
    if until is not None:
        query = query.where(AuditLog.created_at <= until)
    rows = (
        await db.scalars(
            query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    result = [
        AuditView(
            organization_id=r.organization_id,
            id=r.id,
            actor_id=r.actor_id,
            action=r.action,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            request_id=r.request_id,
            timestamp=r.created_at,
            changed_fields=r.changed_fields,
            result=r.result,
            source_ip=r.source_ip,
        )
        for r in rows
    ]
    audit(db, member, "audit.read", "organization", member.organization_id)
    await db.commit()
    return result


class SystemView(BaseModel):
    api: str
    database: str
    redis: str
    worker: str
    scanner: str
    storage: str
    ai_provider: str
    emergency_stop: bool
    active_scans_enabled: bool


@router.get("/system", response_model=SystemView)
async def system(member: AdminMember, db: DB, request: Request) -> SystemView:
    import asyncio
    from pathlib import Path

    require(member, "members.write")
    config = request.app.state.config
    redis_state = "unavailable"
    try:
        async with asyncio.timeout(2):
            if await request.app.state.redis.ping():
                redis_state = "ready"
    except Exception:
        pass
    from aegis_api.scan_coordinator import Broker

    worker = "unavailable"
    try:
        replies = await asyncio.wait_for(
            asyncio.to_thread(Broker(config).app.control.ping, timeout=1), timeout=2
        )
        if replies:
            worker = "responding"
    except Exception:
        pass
    storage = "unverified"
    if config.report_storage == "local":
        storage = (
            "directory_present"
            if await asyncio.to_thread(Path(config.report_root).is_dir)
            else "unavailable"
        )
    audit(db, member, "system.read", "organization", member.organization_id)
    await db.commit()
    return SystemView(
        api="ready",
        database="ready",
        redis=redis_state,
        worker=worker,
        scanner="disabled"
        if config.scanner_provider == "none"
        else "configured_unverified",
        storage=storage,
        ai_provider="disabled"
        if config.ai_provider == "none"
        else "configured_unverified",
        emergency_stop=config.emergency_stop,
        active_scans_enabled=config.active_scans_enabled,
    )


class JobView(BaseModel):
    id: UUID
    kind: str
    state: str
    retry: Literal["regenerate_report", "new_authorized_scan"]
    created_at: datetime


@router.get("/jobs", response_model=list[JobView])
async def jobs(
    member: AdminMember, db: DB, offset: Annotated[int, Query(ge=0)] = 0
) -> list[JobView]:
    from aegis_api.db.models import Report, Scan

    require(member, "members.write")
    result: list[JobView] = []
    models: list[tuple[type[Report] | type[Scan], str]] = [
        (Report, "report"),
        (Scan, "scan"),
    ]
    for model, kind in models:
        rows = (
            await db.scalars(
                select(model)
                .where(
                    model.organization_id == member.organization_id,
                    model.state.in_(
                        ["failed"] if kind == "report" else ["failed", "timed_out"]
                    ),
                )
                .order_by(model.created_at.desc(), model.id)
                .offset(offset)
                .limit(100)
            )
        ).all()
        result.extend(
            JobView(
                id=r.id,
                kind=kind,
                state=cast(Report | Scan, r).state,
                retry="regenerate_report"
                if kind == "report"
                else "new_authorized_scan",
                created_at=r.created_at,
            )
            for r in rows
        )
    audit(db, member, "jobs.read", "organization", member.organization_id)
    await db.commit()
    return result


@router.post(
    "/reports/{report_id}/retry", response_model=Message, dependencies=[Depends(csrf)]
)
async def retry_report(report_id: UUID, member: AdminMember, db: DB) -> Message:
    from aegis_api.db.enums import ReportState
    from aegis_api.db.models import Report

    require(member, "members.write")
    row = await db.scalar(
        select(Report)
        .where(Report.organization_id == member.organization_id, Report.id == report_id)
        .with_for_update()
    )
    if row is None:
        raise APIError(404, "not_found", "Report not found.")
    if row.state != ReportState.FAILED or row.expires_at <= now():
        raise APIError(
            409, "retry_unavailable", "Only unexpired failed reports can be retried."
        )
    row.state = ReportState.PENDING
    row.failure_code = None
    audit(db, member, "report.retry", "report", row.id, ["state"])
    await db.commit()
    return Message(message="Report queued using its retained snapshot.")


@router.post(
    "/policies/{policy_id}/{operation}",
    response_model=Message,
    dependencies=[Depends(csrf)],
)
async def policy_availability(
    policy_id: UUID,
    operation: Literal["publish", "deactivate"],
    member: AdminMember,
    db: DB,
) -> Message:
    from aegis_api.configuration import get_policy

    require(member, "policies.write")
    await get_policy(policy_id, member, db)
    limits = await controls(db, member.organization_id)
    disabled = set(limits.disabled_policy_ids)
    if operation == "deactivate":
        disabled.add(policy_id)
    else:
        disabled.discard(policy_id)
    if len(disabled) > 1000:
        raise APIError(409, "policy_limit", "Policy availability limit reached.")
    limits.disabled_policy_ids = sorted(disabled)
    org = await db.get(Organization, member.organization_id)
    assert org
    org.administration = limits.model_dump(mode="json")
    org.version += 1
    audit(db, member, "policy." + operation, "scan_policy", policy_id, ["status"])
    await db.commit()
    return Message(
        message="Policy published."
        if operation == "publish"
        else "Policy deactivated for new execution."
    )
