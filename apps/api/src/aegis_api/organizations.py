"""Organization commands and project-scoped reads. No scanner execution."""

import secrets
from datetime import timedelta
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from aegis_api.auth import (
    DB,
    EmailPayload,
    Message,
    Payload,
    Principal,
    TokenPayload,
    csrf,
    deliver,
    digest,
    now,
    rate_limit,
)
from aegis_api.auth_models import Invitation
from aegis_api.conventions import APIError
from aegis_api.db.enums import Completeness, RecordState, Role, ScanMode, ScanState
from aegis_api.db.models import (
    AuditLog,
    Finding,
    Integration,
    Organization,
    OrganizationMember,
    Project,
    ProjectMember,
    Report,
    Scan,
    Target,
    User,
)

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])
ADMIN = {Role.OWNER, Role.ADMIN}


def permitted(role: Role, action: str) -> bool:
    """Future commands must use this policy AND a project scope check."""
    if action in {"organization.write", "ownership.transfer"}:
        return role == Role.OWNER
    if action in {
        "members.write",
        "policies.write",
        "integrations.write",
        "projects.write",
    }:
        return role in ADMIN
    if action in {"targets.write", "scans.write", "findings.write", "reports.write"}:
        return role in ADMIN | {Role.DEVELOPER}
    return action == "project.read"


async def membership(
    organization_id: UUID, actor: Principal, db: DB
) -> OrganizationMember:
    # Serialize organization commands: role, deactivation and ownership decisions
    # are evaluated against locked, current membership state.
    org = await db.scalar(
        select(Organization)
        .where(
            Organization.id == organization_id,
            Organization.status == RecordState.ACTIVE,
        )
        .with_for_update()
    )
    member = await db.scalar(
        select(OrganizationMember)
        .where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == actor[0].id,
            OrganizationMember.status == RecordState.ACTIVE,
        )
        .execution_options(populate_existing=True)
    )
    if not org or not member:
        raise APIError(404, "not_found", "Organization not found.")
    return member


Member = Annotated[OrganizationMember, Depends(membership)]


def require(member: OrganizationMember, action: str) -> None:
    if not permitted(member.role, action):
        raise APIError(403, "forbidden", "Your role does not permit this action.")


def event(db: DB, member: OrganizationMember, action: str, resource_id: UUID) -> None:
    db.add(
        AuditLog(
            organization_id=member.organization_id,
            actor_id=member.id,
            action=action,
            resource_type=(
                "invitation"
                if action == "membership.invited"
                else "organization_member"
                if action.startswith("membership.")
                else "organization"
            ),
            resource_id=resource_id,
            changed_fields=["role"]
            if "role" in action or "ownership" in action
            else [],
            request_id=uuid4(),
        )
    )


class Name(Payload):
    name: str = Field(min_length=1, max_length=120)


class OrgView(BaseModel):
    id: UUID
    name: str
    role: Role
    status: RecordState


def view(org: Organization, role: Role) -> OrgView:
    return OrgView(id=org.id, name=org.name, role=role, status=org.status)


class Invite(EmailPayload):
    role: Literal[Role.ADMIN, Role.DEVELOPER, Role.VIEWER]


class RoleChange(Payload):
    role: Literal[Role.ADMIN, Role.DEVELOPER, Role.VIEWER]


class Transfer(Payload):
    member_id: UUID


class MemberView(BaseModel):
    id: UUID
    email: str
    display_name: str
    role: Role
    status: RecordState


@router.get("", response_model=list[OrgView])
async def list_organizations(actor: Principal, db: DB) -> list[OrgView]:
    rows = (
        await db.execute(
            select(Organization, OrganizationMember)
            .join(OrganizationMember)
            .where(
                OrganizationMember.user_id == actor[0].id,
                OrganizationMember.status == RecordState.ACTIVE,
                Organization.status == RecordState.ACTIVE,
            )
        )
    ).all()
    return [view(o, m.role) for o, m in rows]


@router.post("", response_model=OrgView, dependencies=[Depends(csrf)])
async def create(body: Name, actor: Principal, db: DB) -> OrgView:
    org = Organization(name=body.name, slug=uuid4().hex)
    db.add(org)
    await db.flush()
    member = OrganizationMember(
        organization_id=org.id, user_id=actor[0].id, role=Role.OWNER
    )
    db.add(member)
    await db.flush()
    event(db, member, "organization.created", org.id)
    await db.commit()
    return view(org, member.role)


@router.get("/{organization_id}", response_model=OrgView)
async def get_organization(member: Member, db: DB) -> OrgView:
    org = await db.get(Organization, member.organization_id)
    assert org
    return view(org, member.role)


@router.patch(
    "/{organization_id}", response_model=OrgView, dependencies=[Depends(csrf)]
)
async def rename(body: Name, member: Member, db: DB) -> OrgView:
    require(member, "organization.write")
    org = await db.get(Organization, member.organization_id)
    assert org
    org.name, org.version = body.name, org.version + 1
    event(db, member, "organization.renamed", org.id)
    await db.commit()
    return view(org, member.role)


@router.delete(
    "/{organization_id}", response_model=Message, dependencies=[Depends(csrf)]
)
async def deactivate_org(member: Member, db: DB) -> Message:
    require(member, "organization.write")
    org = await db.get(Organization, member.organization_id)
    assert org
    org.status, org.version = RecordState.DEACTIVATED, org.version + 1
    event(db, member, "organization.deactivated", org.id)
    await db.commit()
    return Message(
        message=(
            "Organization deactivated. "
            "Retained evidence and audit history are preserved."
        )
    )


@router.get("/{organization_id}/members", response_model=list[MemberView])
async def members(member: Member, db: DB) -> list[MemberView]:
    require(member, "members.write")
    rows = (
        await db.execute(
            select(OrganizationMember, User)
            .join(User)
            .where(OrganizationMember.organization_id == member.organization_id)
            .order_by(User.display_name)
        )
    ).all()
    return [
        MemberView(
            id=m.id,
            email=u.normalized_email,
            display_name=u.display_name,
            role=m.role,
            status=m.status,
        )
        for m, u in rows
    ]


@router.post(
    "/{organization_id}/invitations",
    response_model=Message,
    dependencies=[Depends(csrf)],
)
async def invite(body: Invite, request: Request, member: Member, db: DB) -> Message:
    require(member, "members.write")
    await rate_limit(request, db)
    if body.role == Role.ADMIN and member.role != Role.OWNER:
        raise APIError(403, "forbidden", "Only the owner can invite an administrator.")
    token = secrets.token_urlsafe(48)
    invitation = Invitation(
        organization_id=member.organization_id,
        normalized_email=body.email,
        role=body.role,
        token_hash=digest(token),
        expires_at=now() + timedelta(days=3),
    )
    db.add(invitation)
    await db.flush()
    event(db, member, "membership.invited", invitation.id)
    await deliver(request, db, body.email, "invite", token)
    await db.commit()
    return Message(
        message="Invitation created. Delivery requires configured email service."
    )


@router.post("/accept-invite", response_model=Message, dependencies=[Depends(csrf)])
async def accept(
    body: TokenPayload, actor: Principal, request: Request, db: DB
) -> Message:
    await rate_limit(request, db)
    invitation = await db.scalar(
        select(Invitation).where(Invitation.token_hash == digest(body.token))
    )
    if invitation:
        org = await db.scalar(
            select(Organization)
            .where(Organization.id == invitation.organization_id)
            .with_for_update()
        )
        await db.refresh(invitation)
    else:
        org = None
    if (
        not invitation
        or invitation.used_at
        or invitation.expires_at <= now()
        or not org
        or org.status != RecordState.ACTIVE
        or invitation.normalized_email != actor[0].normalized_email
    ):
        raise APIError(400, "invalid_invite", "Invitation is invalid or expired.")
    existing = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == invitation.organization_id,
            OrganizationMember.user_id == actor[0].id,
        )
    )
    if existing:
        # Invites cannot change or resurrect an existing member's privileges.
        raise APIError(
            409,
            "membership_exists",
            "Membership already exists. Contact the organization owner.",
        )
    member = OrganizationMember(
        organization_id=invitation.organization_id,
        user_id=actor[0].id,
        role=invitation.role,
    )
    db.add(member)
    await db.flush()
    invitation.used_at = now()
    event(db, member, "membership.accepted", member.id)
    await db.commit()
    return Message(message="Invitation accepted.")


async def target_member(
    member_id: UUID, member: OrganizationMember, db: DB
) -> OrganizationMember:
    target = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.id == member_id,
            OrganizationMember.organization_id == member.organization_id,
        )
    )
    if not target:
        raise APIError(404, "not_found", "Member not found.")
    return target


@router.patch(
    "/{organization_id}/members/{member_id}",
    response_model=Message,
    dependencies=[Depends(csrf)],
)
async def change_role(
    member_id: UUID, body: RoleChange, member: Member, db: DB
) -> Message:
    require(member, "members.write")
    target = await target_member(member_id, member, db)
    if (
        target.role == Role.OWNER
        or target.status != RecordState.ACTIVE
        or (
            member.role != Role.OWNER
            and (target.role == Role.ADMIN or body.role == Role.ADMIN)
        )
    ):
        raise APIError(
            403,
            "forbidden",
            "This role change requires the organization owner or ownership transfer.",
        )
    target.role, target.version = body.role, target.version + 1
    event(db, member, "membership.role_changed", target.id)
    await db.commit()
    return Message(message="Role updated.")


@router.delete(
    "/{organization_id}/members/{member_id}",
    response_model=Message,
    dependencies=[Depends(csrf)],
)
async def deactivate_member(member_id: UUID, member: Member, db: DB) -> Message:
    require(member, "members.write")
    target = await target_member(member_id, member, db)
    if target.role == Role.OWNER or (
        target.role == Role.ADMIN and member.role != Role.OWNER
    ):
        raise APIError(
            403, "forbidden", "Transfer ownership first or contact the owner."
        )
    target.status, target.version = RecordState.DEACTIVATED, target.version + 1
    event(db, member, "membership.deactivated", target.id)
    await db.commit()
    return Message(message="Member deactivated.")


@router.post(
    "/{organization_id}/transfer-ownership",
    response_model=Message,
    dependencies=[Depends(csrf)],
)
async def transfer(body: Transfer, member: Member, db: DB) -> Message:
    require(member, "ownership.transfer")
    target = await target_member(body.member_id, member, db)
    if target.id == member.id or target.status != RecordState.ACTIVE:
        raise APIError(400, "invalid_member", "Choose another active member.")
    member.role, target.role = Role.ADMIN, Role.OWNER
    member.version += 1
    target.version += 1
    event(db, member, "membership.ownership_transferred", target.id)
    await db.commit()
    return Message(message="Ownership transferred.")


async def project_ids(member: OrganizationMember, db: DB) -> list[UUID]:
    query = select(Project.id).where(
        Project.organization_id == member.organization_id,
        Project.status == RecordState.ACTIVE,
    )
    if member.role not in ADMIN:
        query = query.join(
            ProjectMember,
            (ProjectMember.project_id == Project.id)
            & (ProjectMember.organization_id == Project.organization_id),
        ).where(
            ProjectMember.member_id == member.id,
            ProjectMember.status == RecordState.ACTIVE,
        )
    return list((await db.scalars(query)).all())


class ResourceView(BaseModel):
    id: UUID
    project_id: UUID
    label: str


RESOURCES = {
    "projects": Project,
    "targets": Target,
    "scans": Scan,
    "findings": Finding,
    "reports": Report,
}


async def resources(
    kind: str,
    member: OrganizationMember,
    db: DB,
    resource_id: UUID | None = None,
    offset: int = 0,
    project_id: UUID | None = None,
) -> list[ResourceView]:
    ids = await project_ids(member, db)
    model: Any = RESOURCES.get(kind)
    if model is None:
        raise APIError(404, "not_found", "Resource not found.")
    project_column = Project.id if model == Project else Target.project_id
    if model == Project:
        query = select(model, project_column).where(Project.id.in_(ids))
    elif model == Target:
        query = select(model, project_column).where(Target.project_id.in_(ids))
    else:
        query = select(model, project_column)
        if model == Report:
            query = query.join(
                Scan,
                (Report.scan_id == Scan.id)
                & (Report.organization_id == Scan.organization_id),
            )
            source = Scan
        else:
            source = model
        query = query.join(
            Target,
            (source.target_id == Target.id)
            & (source.organization_id == Target.organization_id),
        )
        query = query.where(Target.project_id.in_(ids))
    query = query.where(model.organization_id == member.organization_id)
    if project_id is not None:
        query = query.where(project_column == project_id)
    if resource_id is not None:
        query = query.where(model.id == resource_id)
    rows = (
        await db.execute(
            query.order_by(model.created_at.desc(), model.id.desc())
            .offset(offset)
            .limit(200)
        )
    ).all()
    return [
        ResourceView(
            id=row.id,
            project_id=pid,
            label=row.name
            if model == Project
            else row.display_name
            if model == Target
            else f"{kind[:-1].title()} {row.id}",
        )
        for row, pid in rows
    ]


class Progress(BaseModel):
    create_project: bool
    register_target: bool
    run_safe_baseline: bool
    configure_ci: bool


@router.get("/{organization_id}/onboarding", response_model=Progress)
async def onboarding(member: Member, db: DB) -> Progress:
    ids = await project_ids(member, db)
    target = await db.scalar(
        select(Target.id).where(
            Target.organization_id == member.organization_id,
            Target.project_id.in_(ids),
            Target.status == RecordState.ACTIVE,
        )
    )
    scan = await db.scalar(
        select(Scan.id)
        .join(
            Target,
            (Scan.target_id == Target.id)
            & (Scan.organization_id == Target.organization_id),
        )
        .where(
            Scan.organization_id == member.organization_id,
            Target.project_id.in_(ids),
            Scan.mode == ScanMode.BASELINE,
            Scan.state == ScanState.COMPLETED,
            Scan.completeness == Completeness.COMPLETE,
        )
    )
    ci = await db.scalar(
        select(Integration.id).where(
            Integration.organization_id == member.organization_id,
            Integration.status == RecordState.ACTIVE,
        )
    )
    return Progress(
        create_project=bool(ids),
        register_target=target is not None,
        run_safe_baseline=scan is not None,
        configure_ci=ci is not None,
    )


@router.get("/{organization_id}/resources/{kind}", response_model=list[ResourceView])
async def list_resources(
    kind: str,
    member: Member,
    db: DB,
    offset: Annotated[int, Query(ge=0)] = 0,
    project_id: UUID | None = None,
) -> list[ResourceView]:
    return await resources(kind, member, db, offset=offset, project_id=project_id)


@router.get(
    "/{organization_id}/resources/{kind}/{resource_id}", response_model=ResourceView
)
async def get_resource(
    kind: str, resource_id: UUID, member: Member, db: DB
) -> ResourceView:
    rows = await resources(kind, member, db, resource_id)
    for row in rows:
        if row.id == resource_id:
            return row
    raise APIError(404, "not_found", "Resource not found.")
