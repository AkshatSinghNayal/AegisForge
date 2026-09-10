"""Tenant/project-scoped finding queries and audited reviewer commands."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import case, func, select

from aegis_api.auth import DB, Payload, csrf, now
from aegis_api.configuration import scoped_target
from aegis_api.conventions import APIError
from aegis_api.db.enums import Completeness, FindingState, ScanState, Severity
from aegis_api.db.models import (
    AIAnalysis,
    AuditLog,
    Finding,
    FindingOccurrence,
    FindingReview,
    PolicyEvaluation,
    Scan,
    Target,
)
from aegis_api.organizations import Member, project_ids, require

router = APIRouter(prefix="/api/v1/findings", tags=["findings"])


class FindingView(BaseModel):
    id: UUID
    target_id: UUID
    title: str
    severity: Severity
    confidence: str
    status: FindingState
    route: str
    cwe: int | None
    owasp: list[str]
    first_seen_at: datetime
    last_seen_at: datetime
    version: int


def view(item: Finding) -> FindingView:
    return FindingView(
        id=item.id,
        target_id=item.target_id,
        title=item.title,
        severity=item.scanner_severity,
        confidence=item.scanner_confidence,
        status=item.state,
        route=item.canonical_route,
        cwe=item.cwe,
        owasp=item.normalized.get("owasp", []),
        first_seen_at=item.first_seen_at,
        last_seen_at=item.last_seen_at,
        version=item.version,
    )


class FindingPage(BaseModel):
    items: list[FindingView]
    total: int
    page: int
    page_size: int


@router.get("", response_model=FindingPage)
async def listing(
    member: Member,
    db: DB,
    project: UUID | None = None,
    target: UUID | None = None,
    scan: UUID | None = None,
    severity: Severity | None = None,
    confidence: Literal["false_positive", "low", "medium", "high", "confirmed"]
    | None = None,
    status: FindingState | None = None,
    cwe: int | None = None,
    owasp: str | None = Query(default=None, max_length=120),
    route: str | None = Query(default=None, max_length=2048),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(default=1, ge=1, le=100000),
    page_size: int = Query(default=25, ge=1, le=100),
    sort: Literal[
        "title",
        "severity",
        "confidence",
        "status",
        "route",
        "first_seen_at",
        "last_seen_at",
    ] = "last_seen_at",
    direction: Literal["asc", "desc"] = "desc",
) -> FindingPage:
    ids = await project_ids(member, db)
    query = (
        select(Finding)
        .join(
            Target,
            (Target.id == Finding.target_id)
            & (Target.organization_id == Finding.organization_id),
        )
        .where(
            Finding.organization_id == member.organization_id,
            Target.project_id.in_(ids),
        )
    )
    for value, column in [
        (project, Target.project_id),
        (target, Finding.target_id),
        (severity, Finding.scanner_severity),
        (confidence, Finding.scanner_confidence),
        (status, Finding.state),
        (cwe, Finding.cwe),
    ]:
        if value is not None:
            query = query.where(column == value)
    if scan:
        query = query.where(
            Finding.id.in_(
                select(FindingOccurrence.finding_id).where(
                    FindingOccurrence.organization_id == member.organization_id,
                    FindingOccurrence.scan_id == scan,
                )
            )
        )
    if owasp:
        query = query.where(Finding.normalized["owasp"].contains([owasp]))
    if route:
        query = query.where(Finding.canonical_route.contains(route, autoescape=True))
    if date_from:
        query = query.where(
            Finding.last_seen_at
            >= (date_from if date_from.tzinfo else date_from.replace(tzinfo=UTC))
        )
    if date_to:
        query = query.where(
            Finding.last_seen_at
            <= (date_to if date_to.tzinfo else date_to.replace(tzinfo=UTC))
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    sort_column = {
        "severity": Finding.scanner_severity,
        "confidence": case(
            {"false_positive": 0, "low": 1, "medium": 2, "high": 3, "confirmed": 4},
            value=Finding.scanner_confidence,
        ),
        "route": Finding.canonical_route,
        "status": Finding.state,
    }.get(sort, getattr(Finding, sort, Finding.last_seen_at))
    query = query.order_by(
        sort_column.asc() if direction == "asc" else sort_column.desc(), Finding.id
    )
    rows = (
        await db.scalars(query.offset((page - 1) * page_size).limit(page_size))
    ).all()
    return FindingPage(
        items=[view(row) for row in rows],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


async def scoped(finding_id: UUID, member: Member, db: DB) -> Finding:
    item = await db.scalar(
        select(Finding)
        .where(
            Finding.organization_id == member.organization_id, Finding.id == finding_id
        )
        .with_for_update()
    )
    if item is None:
        raise APIError(404, "not_found", "Finding not found.")
    await scoped_target(item.target_id, member, db)
    return item


@router.get("/comparison/{scan_id}")
async def comparison(scan_id: UUID, member: Member, db: DB) -> dict[str, Any]:
    scan = await db.scalar(
        select(Scan).where(
            Scan.organization_id == member.organization_id, Scan.id == scan_id
        )
    )
    if not scan:
        raise APIError(404, "not_found", "Scan not found.")
    await scoped_target(scan.target_id, member, db)
    return {
        "scan_id": str(scan.id),
        "state": scan.state.value,
        "completeness": scan.completeness.value,
        "comparison": scan.normalization,
    }


@router.get("/{finding_id}")
async def detail(finding_id: UUID, member: Member, db: DB) -> dict[str, Any]:
    item = await scoped(finding_id, member, db)
    occurrences = (
        await db.scalars(
            select(FindingOccurrence)
            .where(
                FindingOccurrence.organization_id == member.organization_id,
                FindingOccurrence.finding_id == item.id,
            )
            .order_by(FindingOccurrence.created_at.desc(), FindingOccurrence.id)
        )
    ).all()
    history = (
        await db.scalars(
            select(FindingReview)
            .where(
                FindingReview.organization_id == member.organization_id,
                FindingReview.finding_id == item.id,
            )
            .order_by(FindingReview.created_at, FindingReview.id)
        )
    ).all()
    analyses = (
        await db.scalars(
            select(AIAnalysis).where(
                AIAnalysis.organization_id == member.organization_id,
                AIAnalysis.occurrence_id.in_([o.id for o in occurrences]),
            )
        )
    ).all()
    policies = (
        await db.scalars(
            select(PolicyEvaluation).where(
                PolicyEvaluation.organization_id == member.organization_id,
                PolicyEvaluation.scan_id.in_([o.scan_id for o in occurrences]),
            )
        )
    ).all()
    return {
        "finding": view(item),
        "fingerprint": item.fingerprint,
        "fingerprint_version": item.fingerprint_version,
        "normalized": item.normalized,
        "occurrences": [
            {
                "id": str(o.id),
                "scan_id": str(o.scan_id),
                "artifact_id": str(o.artifact_id),
                "normalizer": o.normalization_version,
                "evidence_reference": o.redacted_evidence_pointer,
                "observed_at": o.created_at,
                "normalized": o.normalized,
            }
            for o in occurrences
        ],
        "history": [
            {
                "id": str(h.id),
                "action": h.action,
                "previous_state": h.previous_state,
                "state": h.state,
                "note": h.note,
                "actor_id": h.actor_id,
                "scan_id": h.scan_id,
                "created_at": h.created_at,
            }
            for h in history
        ],
        "analysis_status": [
            {"id": str(a.id), "status": a.status, "advisory": a.advisory}
            for a in analyses
        ],
        "policy_impact": [
            {"id": str(p.id), "scan_id": str(p.scan_id), "outcome": p.outcome}
            for p in policies
        ],
    }


class Review(Payload):
    action: Literal["accept_risk", "false_positive", "reopen", "resolve", "note"]
    note: str = Field(min_length=1, max_length=2000)
    version: int = Field(ge=1)
    verification_scan_id: UUID | None = None

    @field_validator("note")
    @classmethod
    def nonempty_note(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A reviewer rationale is required")
        return value.strip()


@router.post(
    "/{finding_id}/review", dependencies=[Depends(csrf)], response_model=FindingView
)
async def review(finding_id: UUID, body: Review, member: Member, db: DB) -> FindingView:
    require(member, "findings.write")
    item = await scoped(finding_id, member, db)
    if item.version != body.version:
        raise APIError(
            409, "stale_version", "Finding changed. Reload before reviewing."
        )
    if body.action == "resolve":
        scan = await db.scalar(
            select(Scan).where(
                Scan.organization_id == member.organization_id,
                Scan.id == body.verification_scan_id,
                Scan.target_id == item.target_id,
                Scan.state == ScanState.COMPLETED,
                Scan.completeness == Completeness.COMPLETE,
            )
        )
        metadata = scan.normalization if scan else None
        if (
            not metadata
            or metadata.get("family") != item.comparison_family
            or str(item.id) in metadata.get("observed", [])
            or not scan
            or not scan.finished_at
            or scan.finished_at < item.last_seen_at
        ):
            raise APIError(
                409,
                "verification_required",
                "A later complete comparable scan must verify absence.",
            )
    previous = item.state
    states = {
        "accept_risk": FindingState.ACCEPTED_RISK,
        "false_positive": FindingState.FALSE_POSITIVE,
        "reopen": FindingState.REOPENED,
        "resolve": FindingState.RESOLVED,
    }
    item.state = states.get(body.action, item.state)
    item.version += 1
    item.resolved_at = now() if item.state == FindingState.RESOLVED else None
    # Reviewer text is explicit user input, kept in review history only, never logs.
    db.add(
        FindingReview(
            organization_id=member.organization_id,
            finding_id=item.id,
            actor_id=member.id,
            scan_id=body.verification_scan_id if body.action == "resolve" else None,
            action=body.action,
            previous_state=previous.value,
            state=item.state.value,
            note=body.note.strip(),
        )
    )
    db.add(
        AuditLog(
            organization_id=member.organization_id,
            actor_id=member.id,
            action=f"finding.{body.action}",
            resource_type="finding",
            resource_id=item.id,
            changed_fields=["state", "version"] if body.action != "note" else ["note"],
            request_id=uuid4(),
        )
    )
    await db.commit()
    return view(item)
