"""Safe metadata registries for the authenticated workspace."""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from aegis_api.auth import DB, csrf
from aegis_api.conventions import APIError
from aegis_api.db.enums import RecordState, Role
from aegis_api.db.models import APIKey, AuditLog, Integration, Report, Scan, Target
from aegis_api.organizations import Member, project_ids

router = APIRouter(prefix="/api/v1/workspace", tags=["workspace"])
Kind = Literal["reports", "integrations", "api-keys", "audit-log"]


class RegistryRow(BaseModel):
    id: UUID
    label: str
    status: str
    created_at: datetime
    expires_at: datetime | None = None
    scan_id: UUID | None = None


class RegistryPage(BaseModel):
    items: list[RegistryRow]
    total: int
    page: int
    page_size: int = 50


@router.get("/{kind}", response_model=RegistryPage)
async def registry(
    kind: Kind, member: Member, db: DB, page: int = Query(default=1, ge=1, le=100000)
) -> RegistryPage:
    ids = await project_ids(member, db)
    if kind != "reports" and member.role not in (Role.OWNER, Role.ADMIN):
        raise APIError(
            403, "forbidden", "Organization administration access is required."
        )
    if kind == "reports":
        query = (
            select(Report)
            .join(
                Scan,
                (Scan.id == Report.scan_id)
                & (Scan.organization_id == Report.organization_id),
            )
            .join(
                Target,
                (Target.id == Scan.target_id)
                & (Target.organization_id == Scan.organization_id),
            )
            .where(
                Report.organization_id == member.organization_id,
                Target.project_id.in_(ids),
            )
        )
        total = await db.scalar(select(func.count()).select_from(query.subquery()))
        reports = (
            await db.scalars(
                query.order_by(Report.created_at.desc(), Report.id)
                .offset((page - 1) * 50)
                .limit(50)
            )
        ).all()
        items = [
            RegistryRow(
                id=r.id,
                label=r.format.upper() + " report",
                status=r.state,
                created_at=r.created_at,
                expires_at=r.expires_at,
                scan_id=r.scan_id,
            )
            for r in reports
        ]
    elif kind == "integrations":
        iq = select(Integration).where(
            Integration.organization_id == member.organization_id
        )
        total = await db.scalar(select(func.count()).select_from(iq.subquery()))
        integrations = (
            await db.scalars(
                iq.order_by(Integration.created_at.desc(), Integration.id)
                .offset((page - 1) * 50)
                .limit(50)
            )
        ).all()
        items = [
            RegistryRow(
                id=r.id, label=r.provider, status=r.status, created_at=r.created_at
            )
            for r in integrations
        ]
    elif kind == "api-keys":
        kq = select(APIKey).where(APIKey.organization_id == member.organization_id)
        total = await db.scalar(select(func.count()).select_from(kq.subquery()))
        keys = (
            await db.scalars(
                kq.order_by(APIKey.created_at.desc(), APIKey.id)
                .offset((page - 1) * 50)
                .limit(50)
            )
        ).all()
        from aegis_api.auth import now

        items = [
            RegistryRow(
                id=r.id,
                label=f"{r.name} ({r.prefix})",
                status="revoked"
                if r.revoked_at
                else "expired"
                if r.expires_at <= now()
                else "active",
                created_at=r.created_at,
                expires_at=r.expires_at,
            )
            for r in keys
        ]
    else:
        aq = select(AuditLog).where(AuditLog.organization_id == member.organization_id)
        total = await db.scalar(select(func.count()).select_from(aq.subquery()))
        audits = (
            await db.scalars(
                aq.order_by(AuditLog.created_at.desc(), AuditLog.id)
                .offset((page - 1) * 50)
                .limit(50)
            )
        ).all()
        items = [
            RegistryRow(
                id=r.id, label=r.action, status=r.resource_type, created_at=r.created_at
            )
            for r in audits
        ]
    return RegistryPage(items=items, total=total or 0, page=page)


@router.delete("/{kind}/{resource_id}", dependencies=[Depends(csrf)])
async def deactivate(
    kind: Literal["integrations", "api-keys"], resource_id: UUID, member: Member, db: DB
) -> dict[str, bool]:
    if member.role not in (Role.OWNER, Role.ADMIN):
        raise APIError(
            403, "forbidden", "Organization administration access is required."
        )
    if kind == "integrations":
        integration = await db.scalar(
            select(Integration)
            .where(
                Integration.id == resource_id,
                Integration.organization_id == member.organization_id,
            )
            .with_for_update()
        )
        if not integration:
            raise APIError(404, "not_found", "Integration not found.")
        integration.status = RecordState.DEACTIVATED
        integration.version += 1
    else:
        key = await db.scalar(
            select(APIKey)
            .where(
                APIKey.id == resource_id,
                APIKey.organization_id == member.organization_id,
            )
            .with_for_update()
        )
        if not key:
            raise APIError(404, "not_found", "API key not found.")
        from aegis_api.auth import now

        key.revoked_at = key.revoked_at or now()
    db.add(
        AuditLog(
            organization_id=member.organization_id,
            actor_id=member.id,
            action=kind + ".deactivated",
            resource_type="integration" if kind == "integrations" else "api_key",
            resource_id=resource_id,
            changed_fields=["status" if kind == "integrations" else "revoked_at"],
            request_id=uuid4(),
        )
    )
    await db.commit()
    return {"ok": True}
