"""Typed API-key endpoints; organization is always derived from the credential."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select

from aegis_api import configuration, notifications, policies, reporting, scans
from aegis_api.api_keys import access
from aegis_api.auth import DB
from aegis_api.configuration_schemas import ProjectView, TargetView
from aegis_api.conventions import ErrorResponse
from aegis_api.db.models import OrganizationMember, Scan, ScanEvent
from aegis_api.findings import FindingPage, listing

router = APIRouter(
    prefix="/api/public/v1",
    tags=["Public API (API key only)"],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
Read = Annotated[OrganizationMember, Depends(access("scans:read"))]
Create = Annotated[OrganizationMember, Depends(access("scans:create"))]
Find = Annotated[OrganizationMember, Depends(access("findings:read"))]
Reports = Annotated[OrganizationMember, Depends(access("reports:read"))]
Integrate = Annotated[OrganizationMember, Depends(access("integrations:write"))]


@router.get("/projects", response_model=list[ProjectView])
async def projects(
    member: Read, db: DB, offset: int = Query(0, ge=0)
) -> list[ProjectView]:
    return await configuration.projects(member, db, offset)


@router.get("/targets", response_model=list[TargetView])
async def targets(
    member: Read, db: DB, project_id: UUID | None = None, offset: int = Query(0, ge=0)
) -> list[TargetView]:
    return await configuration.targets(member, db, project_id, offset)


@router.post("/scans/confirmations", response_model=scans.ConfirmationView)
async def confirmation(
    body: scans.ScanInput, member: Create, db: DB
) -> scans.ConfirmationView:
    return await scans.confirmation(body, member, db)


@router.post("/scans", response_model=scans.ScanView, status_code=202)
async def create_scan(
    body: scans.ScanInput,
    request: Request,
    member: Create,
    db: DB,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=200)],
) -> scans.ScanView:
    # Separate key namespaces prevent two machine credentials sharing a creator
    # from replaying one another's idempotency result.
    import hashlib

    key = hashlib.sha256(
        f"{request.state.api_key_id}:{idempotency_key}".encode()
    ).hexdigest()
    return await scans.create_scan(body, request, member, db, key)


@router.get("/scans", response_model=list[scans.ScanView])
async def scan_list(
    member: Read, db: DB, offset: int = Query(0, ge=0)
) -> list[scans.ScanView]:
    rows = (
        await db.scalars(
            select(Scan)
            .where(Scan.organization_id == member.organization_id)
            .order_by(Scan.created_at.desc(), Scan.id)
            .offset(offset)
            .limit(100)
        )
    ).all()
    return [await scans.view(row, db) for row in rows]


@router.get("/scans/{scan_id}", response_model=scans.ScanView)
async def status(scan_id: UUID, member: Read, db: DB) -> scans.ScanView:
    return await scans.detail(scan_id, member, db)


@router.get("/scans/{scan_id}/events", response_model=list[scans.EventView])
async def events(
    scan_id: UUID, member: Read, db: DB, after: int = Query(0, ge=0)
) -> list[scans.EventView]:
    await scans.resource(scan_id, member, db)
    rows = (
        await db.scalars(
            select(ScanEvent)
            .where(
                ScanEvent.organization_id == member.organization_id,
                ScanEvent.scan_id == scan_id,
                ScanEvent.sequence > after,
            )
            .order_by(ScanEvent.sequence)
            .limit(100)
        )
    ).all()
    return [scans.EventView.model_validate(r, from_attributes=True) for r in rows]


@router.get("/findings", response_model=FindingPage)
async def findings(
    member: Find,
    db: DB,
    scan: UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> FindingPage:
    return await listing(
        member, db, scan=scan, owasp=None, route=None, page=page, page_size=page_size
    )


@router.get(
    "/scans/{scan_id}/policy-result", response_model=list[policies.EvaluationView]
)
async def policy(
    scan_id: UUID, member: Read, db: DB, offset: int = Query(0, ge=0)
) -> list[policies.EvaluationView]:
    return await policies.evaluations(scan_id, member, db, offset)


@router.get("/reports", response_model=list[reporting.ReportView])
async def reports(
    scan_id: UUID, member: Reports, db: DB, offset: int = Query(0, ge=0)
) -> list[reporting.ReportView]:
    return await reporting.listing(scan_id, member, db, offset)


@router.get("/reports/{report_id}", response_model=reporting.ReportView)
async def report(report_id: UUID, member: Reports, db: DB) -> reporting.ReportView:
    return await reporting.detail(report_id, member, db)


@router.post("/reports/{report_id}/download", response_model=reporting.Download)
async def download(
    report_id: UUID, member: Reports, db: DB, request: Request
) -> reporting.Download:
    return await reporting.download(report_id, member, db, request)


@router.post(
    "/notifications/destinations",
    response_model=notifications.DestinationView,
    status_code=201,
)
async def destination(
    body: notifications.DestinationInput, member: Integrate, db: DB, request: Request
) -> notifications.DestinationView:
    return await notifications.create(body, member, db, request)
