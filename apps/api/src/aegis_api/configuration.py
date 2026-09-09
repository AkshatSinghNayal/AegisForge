"""Tenant-scoped Phase 6 services and routes. No scanner commands."""

import base64
import hashlib
import json
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from aegis_api.auth import DB, Message, csrf, now
from aegis_api.configuration_schemas import (
    CredentialInput,
    CredentialView,
    PolicyInput,
    PolicyView,
    ProjectInput,
    ProjectOverview,
    ProjectView,
    ScanSummary,
    TargetInput,
    TargetView,
    ValidationView,
)
from aegis_api.conventions import APIError
from aegis_api.db.enums import FindingState, RecordState, ScanMode
from aegis_api.db.models import (
    AuditLog,
    Finding,
    OrganizationMember,
    Project,
    ProjectMember,
    Scan,
    ScanPolicy,
    Target,
    TargetSecretReference,
)
from aegis_api.organizations import ADMIN, Member, require
from aegis_api.secret_store import LocalSecretStore
from aegis_api.target_validation import probe_url, sanitize_openapi

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}", tags=["configuration"]
)
WRITE = [Depends(csrf)]


def audit(
    db: DB, member: OrganizationMember, action: str, resource: str, id: UUID
) -> None:
    db.add(
        AuditLog(
            organization_id=member.organization_id,
            actor_id=member.id,
            action=action,
            resource_type=resource,
            resource_id=id,
            changed_fields=[],
            request_id=uuid4(),
        )
    )


async def commit(db: DB) -> None:
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise APIError(
            409,
            "configuration_conflict",
            "A conflicting name, slug or target already exists.",
        ) from None


async def scoped_project(
    id: UUID, member: OrganizationMember, db: DB, write: bool = False
) -> Project:
    row = await db.scalar(
        select(Project).where(
            Project.organization_id == member.organization_id, Project.id == id
        )
    )
    if not row:
        raise APIError(404, "not_found", "Project not found.")
    if member.role not in ADMIN:
        assignment = await db.scalar(
            select(ProjectMember.id).where(
                ProjectMember.organization_id == member.organization_id,
                ProjectMember.project_id == id,
                ProjectMember.member_id == member.id,
                ProjectMember.status == RecordState.ACTIVE,
            )
        )
        if not assignment:
            raise APIError(404, "not_found", "Project not found.")
    if write:
        require(member, "targets.write")
        if row.status != RecordState.ACTIVE:
            raise APIError(
                409, "archived_project", "Restore the project before changing targets."
            )
    return row


async def active_members(ids: list[UUID], member: OrganizationMember, db: DB) -> None:
    found = set(
        (
            await db.scalars(
                select(OrganizationMember.id).where(
                    OrganizationMember.organization_id == member.organization_id,
                    OrganizationMember.id.in_(ids),
                    OrganizationMember.status == RecordState.ACTIVE,
                )
            )
        ).all()
    )
    if found != set(ids):
        raise APIError(
            422, "invalid_members", "Choose active members of this organization."
        )


async def project_view(row: Project, db: DB) -> ProjectView:
    ids = list(
        (
            await db.scalars(
                select(ProjectMember.member_id).where(
                    ProjectMember.organization_id == row.organization_id,
                    ProjectMember.project_id == row.id,
                    ProjectMember.status == RecordState.ACTIVE,
                )
            )
        ).all()
    )
    return ProjectView(
        id=row.id,
        name=row.name,
        slug=row.slug or str(row.id),
        description=row.description,
        repository_url=row.repository_ref,
        default_branch=row.default_branch,
        environment=row.environment,
        owner_id=row.owner_id or row.created_by_id,
        member_ids=ids,
        status=row.status,
        version=row.version,
    )


async def set_project(
    row: Project, body: ProjectInput, member: OrganizationMember, db: DB
) -> None:
    with db.no_autoflush:
        await active_members([body.owner_id, *body.member_ids], member, db)
    row.name, row.slug, row.description = body.name, body.slug, body.description
    row.repository_ref, row.default_branch, row.environment, row.owner_id = (
        body.repository_url,
        body.default_branch,
        body.environment,
        body.owner_id,
    )
    await db.flush()
    await db.execute(
        delete(ProjectMember).where(
            ProjectMember.organization_id == member.organization_id,
            ProjectMember.project_id == row.id,
        )
    )
    for id in set([body.owner_id, *body.member_ids]):
        db.add(
            ProjectMember(
                organization_id=member.organization_id, project_id=row.id, member_id=id
            )
        )


@router.get("/projects", response_model=list[ProjectView])
async def projects(member: Member, db: DB) -> list[ProjectView]:
    query = select(Project).where(Project.organization_id == member.organization_id)
    if member.role not in ADMIN:
        query = query.where(
            Project.id.in_(
                select(ProjectMember.project_id).where(
                    ProjectMember.organization_id == member.organization_id,
                    ProjectMember.member_id == member.id,
                    ProjectMember.status == RecordState.ACTIVE,
                )
            )
        )
    return [
        await project_view(row, db)
        for row in (
            await db.scalars(query.order_by(Project.created_at.desc()).limit(200))
        ).all()
    ]


@router.post("/projects", response_model=ProjectView, dependencies=WRITE)
async def create_project(body: ProjectInput, member: Member, db: DB) -> ProjectView:
    require(member, "projects.write")
    row = Project(organization_id=member.organization_id, created_by_id=member.id)
    await active_members([body.owner_id, *body.member_ids], member, db)
    db.add(row)
    try:
        await set_project(row, body, member, db)
    except IntegrityError:
        await db.rollback()
        raise APIError(
            409, "configuration_conflict", "Project name or slug already exists."
        ) from None
    audit(db, member, "project.created", "project", row.id)
    await commit(db)
    return await project_view(row, db)


@router.put("/projects/{project_id}", response_model=ProjectView, dependencies=WRITE)
async def edit_project(
    project_id: UUID, body: ProjectInput, member: Member, db: DB
) -> ProjectView:
    row = await scoped_project(project_id, member, db)
    require(member, "projects.write")
    try:
        await set_project(row, body, member, db)
    except IntegrityError:
        await db.rollback()
        raise APIError(
            409, "configuration_conflict", "Project name or slug already exists."
        ) from None
    row.version += 1
    audit(db, member, "project.updated", "project", row.id)
    await commit(db)
    return await project_view(row, db)


@router.delete("/projects/{project_id}", response_model=Message, dependencies=WRITE)
async def archive_project(project_id: UUID, member: Member, db: DB) -> Message:
    row = await scoped_project(project_id, member, db)
    require(member, "projects.write")
    row.status, row.version = RecordState.DEACTIVATED, row.version + 1
    audit(db, member, "project.archived", "project", row.id)
    await commit(db)
    return Message(message="Project archived; history retained.")


@router.post(
    "/projects/{project_id}/restore", response_model=Message, dependencies=WRITE
)
async def restore_project(project_id: UUID, member: Member, db: DB) -> Message:
    row = await scoped_project(project_id, member, db)
    require(member, "projects.write")
    row.status, row.version = RecordState.ACTIVE, row.version + 1
    audit(db, member, "project.restored", "project", row.id)
    await commit(db)
    return Message(message="Project restored.")


async def get_policy(id: UUID, member: OrganizationMember, db: DB) -> ScanPolicy:
    row = await db.scalar(
        select(ScanPolicy).where(
            ScanPolicy.organization_id == member.organization_id, ScanPolicy.id == id
        )
    )
    if not row:
        raise APIError(404, "not_found", "Policy not found.")
    return row


def policy_view(row: ScanPolicy) -> PolicyView:
    if row.schema_version != "phase6.v1":
        raise APIError(
            409, "legacy_policy", "Create a current policy for this legacy record."
        )
    return PolicyView(**row.rules_snapshot, id=row.id, version=row.version)


async def add_policy(
    body: PolicyInput, member: OrganizationMember, db: DB
) -> ScanPolicy:
    latest = await db.scalar(
        select(func.max(ScanPolicy.version)).where(
            ScanPolicy.organization_id == member.organization_id,
            ScanPolicy.name == body.name,
        )
    )
    row = ScanPolicy(
        organization_id=member.organization_id,
        name=body.name,
        version=(latest or 0) + 1,
        mode=body.mode,
        fail_severity=body.fail_severity,
        max_duration_seconds=body.max_duration_seconds,
        max_requests=body.max_requests,
        max_depth=body.max_depth,
        require_enrichment=False,
        require_report=False,
        allow_waivers=False,
        required_coverage=["passive"],
        schema_version="phase6.v1",
        rules_snapshot=body.model_dump(mode="json"),
    )
    db.add(row)
    await db.flush()
    audit(db, member, "policy.version_created", "scan_policy", row.id)
    return row


@router.get("/policies", response_model=list[PolicyView])
async def policies(member: Member, db: DB) -> list[PolicyView]:
    rows = (
        await db.scalars(
            select(ScanPolicy)
            .where(
                ScanPolicy.organization_id == member.organization_id,
                ScanPolicy.schema_version == "phase6.v1",
            )
            .order_by(ScanPolicy.name, ScanPolicy.version.desc())
            .limit(200)
        )
    ).all()
    return [policy_view(row) for row in rows]


@router.post("/policies", response_model=PolicyView, dependencies=WRITE)
async def create_policy(body: PolicyInput, member: Member, db: DB) -> PolicyView:
    require(member, "policies.write")
    row = await add_policy(body, member, db)
    await commit(db)
    return policy_view(row)


@router.post("/policies/presets", response_model=list[PolicyView], dependencies=WRITE)
async def presets(member: Member, db: DB) -> list[PolicyView]:
    require(member, "policies.write")
    bodies = [
        PolicyInput(name="Passive baseline"),
        PolicyInput(name="API import / passive", mode=ScanMode.PASSIVE, spider="none"),
        PolicyInput(
            name="Authorized standard active",
            mode=ScanMode.ACTIVE,
            active_rule_allowlist=["40012", "40018"],
            active_warning_acknowledged=True,
        ),
    ]
    rows = []
    for body in bodies:
        existing = await db.scalar(
            select(ScanPolicy)
            .where(
                ScanPolicy.organization_id == member.organization_id,
                ScanPolicy.name == body.name,
                ScanPolicy.schema_version == "phase6.v1",
            )
            .order_by(ScanPolicy.version.desc())
        )
        rows.append(existing or await add_policy(body, member, db))
    await commit(db)
    return [policy_view(row) for row in rows]


@router.get("/policies/{policy_id}", response_model=PolicyView)
async def policy_detail(policy_id: UUID, member: Member, db: DB) -> PolicyView:
    return policy_view(await get_policy(policy_id, member, db))


@router.put("/policies/{policy_id}", response_model=PolicyView, dependencies=WRITE)
async def revise_policy(
    policy_id: UUID, body: PolicyInput, member: Member, db: DB
) -> PolicyView:
    require(member, "policies.write")
    old = await get_policy(policy_id, member, db)
    if old.name != body.name:
        raise APIError(
            422,
            "policy_name",
            "Versioned policies retain their name. Create a new policy to use "
            "a different name.",
        )
    row = await add_policy(body, member, db)
    await commit(db)
    return policy_view(row)


def credential_view(row: TargetSecretReference) -> CredentialView:
    return CredentialView(
        id=row.id,
        auth_type=row.auth_type,
        header_name=row.header_name,
        version=row.version,
        revoked=row.revoked_at is not None,
    )


async def target_view(row: Target, db: DB) -> TargetView:
    refs = (
        await db.scalars(
            select(TargetSecretReference).where(
                TargetSecretReference.organization_id == row.organization_id,
                TargetSecretReference.target_id == row.id,
                TargetSecretReference.revoked_at.is_(None),
            )
        )
    ).all()
    cfg = row.configuration
    return TargetView(
        id=row.id,
        project_id=row.project_id,
        display_name=row.display_name,
        kind=row.kind,
        base_url=row.canonical_url,
        environment=row.environment,
        policy_id=row.policy_id,
        consent_at=row.consent_at,
        authorization_owner_id=row.authorization_actor_id,
        authorization_declaration=cfg.get("authorization_declaration", ""),
        inclusion_patterns=row.scope_paths,
        exclusion_patterns=cfg.get("exclusion_patterns", []),
        allowed_methods=cfg.get("allowed_methods", []),
        rate_limit=cfg.get("rate_limit", 2),
        timeout_seconds=cfg.get("timeout_seconds", 300),
        status=row.status,
        version=row.version,
        verified_at=row.verified_at,
        has_openapi=row.sanitized_spec is not None,
        credentials=[credential_view(ref) for ref in refs],
    )


async def scoped_target(
    id: UUID, member: OrganizationMember, db: DB, write: bool = False
) -> Target:
    row = await db.scalar(
        select(Target).where(
            Target.organization_id == member.organization_id, Target.id == id
        )
    )
    if not row:
        raise APIError(404, "not_found", "Target not found.")
    await scoped_project(row.project_id, member, db, write)
    return row


async def validate_target(
    body: TargetInput, member: OrganizationMember, db: DB
) -> tuple[ValidationView, dict[str, Any] | None]:
    await scoped_project(body.project_id, member, db, True)
    await active_members([body.authorization_owner_id], member, db)
    # A member may declare their own authorization; only admins may record delegation.
    if body.authorization_owner_id != member.id and member.role not in ADMIN:
        raise APIError(
            403, "forbidden", "Record your own authorization or ask an administrator."
        )
    policy = policy_view(await get_policy(body.policy_id, member, db))
    if policy.allow_private and member.role not in ADMIN:
        raise APIError(
            403, "forbidden", "Only administrators may register internal-test targets."
        )
    if (
        body.rate_limit > policy.rate_limit
        or body.timeout_seconds > policy.max_duration_seconds
    ):
        raise APIError(
            422,
            "policy_limits",
            "Target rate and timeout must not exceed its policy limits.",
        )
    if policy.mode != ScanMode.ACTIVE and set(body.allowed_methods) - {
        "GET",
        "HEAD",
        "OPTIONS",
    }:
        raise APIError(
            422,
            "passive_methods",
            "Passive policies permit only GET, HEAD and OPTIONS.",
        )
    spec = None
    if body.kind == "openapi_upload":
        assert body.upload_content and body.upload_filename
        spec = sanitize_openapi(
            body.upload_content.get_secret_value().encode(), body.upload_filename
        )
    url, status, _ = await probe_url(body.base_url, policy.allow_private)
    if body.kind == "openapi_url":
        assert body.openapi_url
        _, _, content = await probe_url(body.openapi_url, policy.allow_private, True)
        spec = sanitize_openapi(
            content,
            "document.json" if content.lstrip().startswith(b"{") else "document.yaml",
        )
    if urlsplit(url).netloc != urlsplit(body.base_url).netloc:
        raise APIError(
            422,
            "redirect_scope",
            "The target redirects to another authority. Register the final "
            "destination explicitly.",
        )
    return ValidationView(
        valid=True,
        final_url=url,
        http_status=status,
        openapi_valid=spec is not None,
        message=(
            "Reachability and scope checks passed. "
            "This is not scan authorization or a security finding."
        ),
    ), spec


@router.post("/targets/validate", response_model=ValidationView, dependencies=WRITE)
async def validate_endpoint(
    body: TargetInput, member: Member, db: DB
) -> ValidationView:
    result, _ = await validate_target(body, member, db)
    return result


async def store_credential(
    row: Target, body: CredentialInput, request: Request, db: DB
) -> TargetSecretReference:
    store = LocalSecretStore(request.app.state.config)
    old = (
        await db.scalars(
            select(TargetSecretReference).where(
                TargetSecretReference.organization_id == row.organization_id,
                TargetSecretReference.target_id == row.id,
            )
        )
    ).all()
    for ref in old:
        if ref.revoked_at is None:
            ref.revoked_at = now()
    id = uuid4()
    value = body.value.get_secret_value()
    if body.auth_type == "basic":
        assert body.username
        value = (
            "Basic "
            + base64.b64encode(
                f"{body.username.get_secret_value()}:{value}".encode()
            ).decode()
        )
    elif body.auth_type == "bearer":
        value = "Bearer " + value
    ref = TargetSecretReference(
        id=id,
        organization_id=row.organization_id,
        target_id=row.id,
        auth_type=body.auth_type,
        header_name=body.header_name
        if body.auth_type == "api_key"
        else "Authorization",
        secret_provider_ref=f"local:{id}",
        ciphertext=store.seal(row.organization_id, id, value),
        version=max([r.version for r in old], default=0) + 1,
    )
    db.add(ref)
    await db.flush()
    return ref


@router.post("/targets", response_model=TargetView, dependencies=WRITE)
async def create_target(
    body: TargetInput, member: Member, db: DB, request: Request
) -> TargetView:
    _, spec = await validate_target(body, member, db)
    cfg = body.model_dump(
        mode="json",
        exclude={"credential", "upload_content", "upload_filename", "openapi_url"},
    )
    row = Target(
        organization_id=member.organization_id,
        project_id=body.project_id,
        display_name=body.display_name,
        canonical_url=body.base_url,
        kind=body.kind,
        environment=body.environment,
        scope_hosts=[urlsplit(body.base_url).hostname],
        scope_paths=body.inclusion_patterns,
        configuration=cfg,
        policy_id=body.policy_id,
        consent_at=now(),
        authorization_actor_id=body.authorization_owner_id,
        authorization_method="explicit_declaration",
        authorized_scope_digest=hashlib.sha256(
            json.dumps(cfg, sort_keys=True).encode()
        ).hexdigest(),
        authorized_until=now() + timedelta(days=30),
        verified_at=now(),
        sanitized_spec=spec,
    )
    db.add(row)
    try:
        await db.flush()
        if body.credential:
            await store_credential(row, body.credential, request, db)
    except IntegrityError:
        await db.rollback()
        raise APIError(
            409,
            "configuration_conflict",
            "This target is already registered in the project.",
        ) from None
    audit(db, member, "target.authorized", "target", row.id)
    await commit(db)
    return await target_view(row, db)


@router.get("/targets", response_model=list[TargetView])
async def targets(
    member: Member, db: DB, project_id: UUID | None = None
) -> list[TargetView]:
    if project_id:
        await scoped_project(project_id, member, db)
    query = select(Target).where(Target.organization_id == member.organization_id)
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
    if project_id:
        query = query.where(Target.project_id == project_id)
    return [
        await target_view(row, db)
        for row in (
            await db.scalars(query.order_by(Target.created_at.desc()).limit(200))
        ).all()
    ]


@router.get("/targets/{target_id}", response_model=TargetView)
async def target_detail(target_id: UUID, member: Member, db: DB) -> TargetView:
    return await target_view(await scoped_target(target_id, member, db), db)


@router.delete("/targets/{target_id}", response_model=Message, dependencies=WRITE)
async def deactivate_target(target_id: UUID, member: Member, db: DB) -> Message:
    row = await scoped_target(target_id, member, db)
    require(member, "targets.write")
    row.status, row.authorized_until, row.version = (
        RecordState.DEACTIVATED,
        now(),
        row.version + 1,
    )
    audit(db, member, "target.deactivated", "target", row.id)
    await commit(db)
    return Message(message="Target deactivated and authorization revoked.")


@router.post(
    "/targets/{target_id}/credentials",
    response_model=CredentialView,
    dependencies=WRITE,
)
async def credential(
    target_id: UUID, body: CredentialInput, member: Member, db: DB, request: Request
) -> CredentialView:
    row = await scoped_target(target_id, member, db, True)
    if row.status != RecordState.ACTIVE:
        raise APIError(409, "inactive_target", "Target is inactive.")
    ref = await store_credential(row, body, request, db)
    row.version += 1
    audit(db, member, "credential.rotated", "target", row.id)
    await commit(db)
    return credential_view(ref)


@router.delete(
    "/targets/{target_id}/credentials/{credential_id}",
    response_model=Message,
    dependencies=WRITE,
)
async def revoke_credential(
    target_id: UUID, credential_id: UUID, member: Member, db: DB
) -> Message:
    row = await scoped_target(target_id, member, db)
    require(member, "targets.write")
    ref = await db.scalar(
        select(TargetSecretReference).where(
            TargetSecretReference.organization_id == member.organization_id,
            TargetSecretReference.target_id == row.id,
            TargetSecretReference.id == credential_id,
        )
    )
    if not ref:
        raise APIError(404, "not_found", "Credential not found.")
    ref.revoked_at, row.version = now(), row.version + 1
    audit(db, member, "credential.revoked", "target", row.id)
    await commit(db)
    return Message(message="Credential revoked.")


@router.get("/projects/{project_id}", response_model=ProjectOverview)
async def overview(project_id: UUID, member: Member, db: DB) -> ProjectOverview:
    project = await scoped_project(project_id, member, db)
    target_rows = await targets(member, db, project_id)
    ids = select(Target.id).where(
        Target.organization_id == member.organization_id,
        Target.project_id == project_id,
    )
    scans = (
        await db.scalars(
            select(Scan)
            .where(
                Scan.organization_id == member.organization_id, Scan.target_id.in_(ids)
            )
            .order_by(Scan.created_at.desc())
            .limit(10)
        )
    ).all()
    count = await db.scalar(
        select(func.count())
        .select_from(Finding)
        .where(
            Finding.organization_id == member.organization_id,
            Finding.target_id.in_(ids),
            Finding.state.in_(
                [FindingState.NEW, FindingState.RECURRING, FindingState.CHANGED]
            ),
        )
    )
    return ProjectOverview(
        project=await project_view(project, db),
        targets=target_rows,
        recent_scans=[
            ScanSummary(
                id=s.id,
                state=s.state,
                completeness=s.completeness,
                created_at=s.created_at,
            )
            for s in scans
        ],
        open_findings=count or 0,
    )


class ConfigurationIdentity(BaseModel):
    member_id: UUID


@router.get("/configuration-identity", response_model=ConfigurationIdentity)
async def configuration_identity(member: Member) -> ConfigurationIdentity:
    return ConfigurationIdentity(member_id=member.id)
