"""Structured project gate publication, activation, preview and retained evaluation."""

from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from aegis_api.auth import DB, Payload, csrf, now
from aegis_api.configuration import scoped_project
from aegis_api.conventions import APIError
from aegis_api.db.enums import RecordState
from aegis_api.db.models import (
    AuditLog,
    Finding,
    GateActivation,
    GatePolicy,
    OrganizationMember,
    PolicyEvaluation,
    Project,
    Target,
)
from aegis_api.organizations import Member, require
from aegis_api.policy_engine import (
    ApprovedException,
    ExceptionScope,
    Policy,
    Result,
    evaluate,
)
from aegis_api.policy_service import active_policy, capture, persist_evaluation
from aegis_api.scans import resource

router = APIRouter(prefix="/api/v1", tags=["Deterministic policies"])


class Publish(Payload):
    policy: Policy
    exceptions: list[ExceptionScope] = Field(default_factory=list, max_length=100)


class PolicyView(BaseModel):
    id: UUID
    version: int
    snapshot: Policy


class PolicyList(BaseModel):
    active_id: UUID | None
    versions: list[PolicyView]


class Activation(Payload):
    policy_id: UUID | None


class EvaluationView(BaseModel):
    id: UUID
    input_digest: str
    evaluation_version: str
    input_snapshot: dict[str, Any]
    result_snapshot: Result


def policy_view(row: GatePolicy) -> PolicyView:
    return PolicyView(
        id=row.id, version=row.version, snapshot=Policy.model_validate(row.snapshot)
    )


def evaluation_view(row: PolicyEvaluation) -> EvaluationView:
    return EvaluationView(
        id=row.id,
        input_digest=row.input_digest,
        evaluation_version=row.evaluation_version,
        input_snapshot=row.input_snapshot,
        result_snapshot=Result.model_validate(row.result_snapshot),
    )


def audit(db: DB, member: Member, action: str, identity: UUID) -> None:
    db.add(
        AuditLog(
            organization_id=member.organization_id,
            actor_id=member.id,
            action=action,
            resource_type="gate_policy",
            resource_id=identity,
            changed_fields=["policy"],
            request_id=uuid4(),
        )
    )


@router.get(
    "/organizations/{organization_id}/projects/{project_id}/gate-policies",
    response_model=PolicyList,
)
async def versions(
    organization_id: UUID, project_id: UUID, member: Member, db: DB
) -> PolicyList:
    await scoped_project(project_id, member, db)
    active = await active_policy(db, member.organization_id, project_id)
    rows = (
        await db.scalars(
            select(GatePolicy)
            .where(
                GatePolicy.organization_id == member.organization_id,
                GatePolicy.project_id == project_id,
            )
            .order_by(GatePolicy.version.desc())
        )
    ).all()
    return PolicyList(
        active_id=active.id if active else None, versions=[policy_view(r) for r in rows]
    )


@router.post(
    "/organizations/{organization_id}/projects/{project_id}/gate-policies",
    dependencies=[Depends(csrf)],
    response_model=PolicyView,
)
async def publish(
    organization_id: UUID, project_id: UUID, body: Publish, member: Member, db: DB
) -> PolicyView:
    require(member, "policies.write")
    await scoped_project(project_id, member, db, True)
    await db.scalar(
        select(Project)
        .where(
            Project.organization_id == member.organization_id, Project.id == project_id
        )
        .with_for_update()
    )
    if body.policy.exceptions:
        raise APIError(
            422,
            "approval_server_owned",
            "Submit exception scopes; approval is recorded by the server.",
        )
    approved = []
    at = now()
    for exception in body.exceptions:
        finding = await db.scalar(
            select(Finding)
            .join(
                Target,
                (Target.id == Finding.target_id)
                & (Target.organization_id == Finding.organization_id),
            )
            .where(
                Finding.organization_id == member.organization_id,
                Finding.id == exception.finding_id,
                Target.project_id == project_id,
            )
        )
        owner = await db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == member.organization_id,
                OrganizationMember.id == exception.owner_id,
                OrganizationMember.status == RecordState.ACTIVE,
            )
        )
        if finding is None or owner is None or exception.expires_at <= at:
            raise APIError(
                422,
                "invalid_exception",
                "Exception requires a project finding, active owner and future expiry.",
            )
        approved.append(
            ApprovedException(
                **exception.model_dump(), created_at=at, approved_by=member.id
            )
        )
    snapshot = Policy.model_validate(
        {**body.policy.model_dump(), "exceptions": approved}
    )
    last = await db.scalar(
        select(func.max(GatePolicy.version)).where(
            GatePolicy.organization_id == member.organization_id,
            GatePolicy.project_id == project_id,
        )
    )
    row = GatePolicy(
        id=uuid4(),
        organization_id=member.organization_id,
        project_id=project_id,
        version=(last or 0) + 1,
        published_by=member.id,
        snapshot=snapshot.model_dump(mode="json"),
    )
    db.add(row)
    audit(db, member, "policy.publish", row.id)
    await db.commit()
    return policy_view(row)


async def scoped_policy(identity: UUID, member: Member, db: DB) -> GatePolicy:
    row = await db.scalar(
        select(GatePolicy).where(
            GatePolicy.organization_id == member.organization_id,
            GatePolicy.id == identity,
        )
    )
    if row is None:
        raise APIError(404, "not_found", "Policy not found.")
    await scoped_project(row.project_id, member, db)
    return row


@router.post(
    "/organizations/{organization_id}/projects/{project_id}/gate-policies/activation",
    dependencies=[Depends(csrf)],
)
async def activate(
    organization_id: UUID, project_id: UUID, body: Activation, member: Member, db: DB
) -> dict[str, str]:
    require(member, "policies.write")
    await scoped_project(project_id, member, db, True)
    await db.scalar(
        select(Project)
        .where(
            Project.organization_id == member.organization_id, Project.id == project_id
        )
        .with_for_update()
    )
    if body.policy_id:
        row = await scoped_policy(body.policy_id, member, db)
        if row.project_id != project_id:
            raise APIError(404, "not_found", "Policy not found.")
    last = await db.scalar(
        select(func.max(GateActivation.sequence)).where(
            GateActivation.organization_id == member.organization_id,
            GateActivation.project_id == project_id,
        )
    )
    db.add(
        GateActivation(
            organization_id=member.organization_id,
            project_id=project_id,
            gate_policy_id=body.policy_id,
            actor_id=member.id,
            sequence=(last or 0) + 1,
        )
    )
    audit(
        db,
        member,
        "policy.activate" if body.policy_id else "policy.deactivate",
        body.policy_id or project_id,
    )
    await db.commit()
    return {"message": "Activation updated. Existing scan snapshots are unchanged."}


class Evaluate(Payload):
    policy_id: UUID


async def pair(
    scan_id: UUID, body: Evaluate, member: Member, db: DB
) -> tuple[Any, GatePolicy]:
    scan = await resource(scan_id, member, db, lock=True)
    policy = await scoped_policy(body.policy_id, member, db)
    target = await db.scalar(
        select(Target).where(
            Target.organization_id == member.organization_id,
            Target.id == scan.target_id,
        )
    )
    if target is None or target.project_id != policy.project_id:
        raise APIError(404, "not_found", "Policy not found for this scan.")
    return scan, policy


@router.post(
    "/scans/{scan_id}/policy-preview",
    dependencies=[Depends(csrf)],
    response_model=Result,
)
async def preview(scan_id: UUID, body: Evaluate, member: Member, db: DB) -> Result:
    scan, policy = await pair(scan_id, body, member, db)
    return evaluate(Policy.model_validate(policy.snapshot), await capture(db, scan))


@router.post(
    "/scans/{scan_id}/policy-evaluations",
    dependencies=[Depends(csrf)],
    response_model=EvaluationView,
)
async def reevaluate(
    scan_id: UUID, body: Evaluate, member: Member, db: DB
) -> EvaluationView:
    require(member, "policies.write")
    scan, policy = await pair(scan_id, body, member, db)
    row = await persist_evaluation(db, scan, policy)
    audit(db, member, "policy.evaluate", row.id)
    await db.commit()
    return evaluation_view(row)


@router.get("/scans/{scan_id}/policy-evaluations", response_model=list[EvaluationView])
async def evaluations(
    scan_id: UUID, member: Member, db: DB, offset: int = Query(default=0, ge=0)
) -> list[EvaluationView]:
    await resource(scan_id, member, db)
    rows = (
        await db.scalars(
            select(PolicyEvaluation)
            .where(
                PolicyEvaluation.organization_id == member.organization_id,
                PolicyEvaluation.scan_id == scan_id,
                PolicyEvaluation.gate_policy_id.is_not(None),
            )
            .order_by(PolicyEvaluation.created_at.desc(), PolicyEvaluation.id)
            .offset(offset)
            .limit(50)
        )
    ).all()
    return [evaluation_view(row) for row in rows]
