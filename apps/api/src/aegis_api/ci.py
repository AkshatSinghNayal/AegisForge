"""Minimal machine contract: frozen configuration and allowlisted gate summary."""

import hashlib
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from aegis_api import scans
from aegis_api.auth import DB, Payload
from aegis_api.configuration import get_policy, scoped_target
from aegis_api.conventions import APIError
from aegis_api.db.enums import Completeness, ScanMode, ScanState
from aegis_api.db.models import OrganizationMember, PolicyEvaluation
from aegis_api.normalization import digest
from aegis_api.policy_engine import Inputs
from aegis_api.policy_service import active_policy
from aegis_api.public_api import Create, Read
from aegis_api.scan_lifecycle import TERMINAL

router = APIRouter(prefix="/api/public/v1/ci", tags=["CI integration"])


class Selection(Payload):
    project_id: UUID
    target_id: UUID
    policy_id: UUID
    environment: str = Field(min_length=1, max_length=64)


class Context(Selection):
    target_version: int
    policy_version: int
    gate_policy_id: UUID
    gate_policy_version: int


class Submission(Context):
    trigger: scans.Trigger


async def resolve(body: Selection, member: OrganizationMember, db: DB) -> Context:
    target = await scoped_target(body.target_id, member, db)
    policy = await get_policy(body.policy_id, member, db)
    if target.project_id != body.project_id or target.environment != body.environment:
        raise APIError(409, "mapping_changed", "Project or environment does not match.")
    if policy.mode == ScanMode.ACTIVE:
        raise APIError(
            409, "active_confirmation_required", "CI supports passive policies only."
        )
    await scans.validate(
        scans.ScanInput(
            target_id=target.id,
            target_version=target.version,
            policy_id=policy.id,
            policy_version=policy.version,
        ),
        member,
        db,
    )
    gate = await active_policy(db, member.organization_id, target.project_id)
    if not gate:
        raise APIError(
            409, "gate_required", "Activate a deterministic project gate policy first."
        )
    return Context(
        **body.model_dump(include=set(Selection.model_fields)),
        target_version=target.version,
        policy_version=policy.version,
        gate_policy_id=gate.id,
        gate_policy_version=gate.version,
    )


@router.post("/context", response_model=Context)
async def context(body: Selection, member: Create, db: DB) -> Context:
    return await resolve(body, member, db)


async def submit(
    body: Submission,
    request: Request,
    member: OrganizationMember,
    db: DB,
    key: str,
    *,
    commit: bool = True,
) -> scans.ScanView:
    current = await resolve(body, member, db)
    if current.model_dump() != body.model_dump(exclude={"trigger"}):
        raise APIError(
            409, "configuration_changed", "Review current configuration versions."
        )
    return await scans.submit_scan(
        scans.ScanInput(
            target_id=body.target_id,
            target_version=body.target_version,
            policy_id=body.policy_id,
            policy_version=body.policy_version,
            trigger=body.trigger,
        ),
        request,
        member,
        db,
        key,
        commit=commit,
        command_digest=digest(body.model_dump(mode="json")),
    )


@router.post("/scans", response_model=scans.ScanView, status_code=202)
async def create(
    body: Submission,
    request: Request,
    member: Create,
    db: DB,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=200)],
) -> scans.ScanView:
    key = hashlib.sha256(
        f"ci:{request.state.api_key_id}:{idempotency_key}".encode()
    ).hexdigest()
    return await submit(body, request, member, db, key)


class Summary(BaseModel):
    scan_id: UUID
    state: ScanState
    terminal: bool
    outcome: Literal["pass", "warn", "fail", "incomplete"]
    counts: dict[str, int] | None
    path: str


@router.get("/scans/{scan_id}/summary", response_model=Summary)
async def summary(scan_id: UUID, member: Read, db: DB) -> Summary:
    row = await scans.resource(scan_id, member, db)
    evaluation = await db.scalar(
        select(PolicyEvaluation)
        .where(
            PolicyEvaluation.organization_id == member.organization_id,
            PolicyEvaluation.scan_id == row.id,
            PolicyEvaluation.gate_policy_id
            == row.config_snapshot.get("gate_policy_id"),
        )
        .order_by(PolicyEvaluation.created_at.desc(), PolicyEvaluation.id.desc())
        .limit(1)
    )
    outcome: Literal["pass", "warn", "fail", "incomplete"] = "incomplete"
    counts = None
    if evaluation:
        outcome = evaluation.outcome.value
        inputs = Inputs.model_validate(evaluation.input_snapshot["inputs"])
        counts = {
            s: len({f.finding_id for f in inputs.findings if f.severity == s})
            for s in ["critical", "high", "medium", "low", "informational"]
        }
    if evaluation and (
        not inputs.normalized or inputs.completeness != Completeness.COMPLETE
    ):
        counts = None
    if (
        row.state != ScanState.COMPLETED
        or row.completeness != Completeness.COMPLETE
        or row.is_demo
        or not row.normalization
    ):
        outcome = "fail" if outcome == "fail" else "incomplete"
    return Summary(
        scan_id=row.id,
        state=row.state,
        terminal=row.state in TERMINAL,
        outcome=outcome,
        counts=counts,
        path=f"/app/scans/{row.id}?organization={member.organization_id}",
    )


@router.post("/scans/{scan_id}/cancel", response_model=scans.ScanView)
async def cancel(scan_id: UUID, member: Create, db: DB) -> scans.ScanView:
    row = await scans.resource(scan_id, member, db, True)
    if row.state in TERMINAL:
        return await scans.view(row, db)
    return await scans.cancel(scan_id, member, db)
