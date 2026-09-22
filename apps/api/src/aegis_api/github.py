"""Signed inbound events resolve only administrator-pinned passive targets."""

import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import or_, select

from aegis_api import ci, scans
from aegis_api.auth import DB, csrf
from aegis_api.conventions import APIError
from aegis_api.db.enums import RecordState
from aegis_api.db.models import (
    GitHubDelivery,
    GitHubMapping,
    Integration,
    Organization,
    OrganizationMember,
)
from aegis_api.organizations import ADMIN, Member, event, require
from aegis_api.settings import Settings

router = APIRouter(tags=["GitHub integration"])
PREFIX = "/api/v1/github"
REPO = r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
BRANCH = r"^[A-Za-z0-9._/\-]+$"
SHA = r"^[0-9a-fA-F]{40}$"


class MappingInput(ci.Selection):
    repository: str = Field(pattern=REPO, max_length=200)
    branch: str = Field(pattern=BRANCH, min_length=1, max_length=120)
    events: list[Literal["push", "pull_request"]] = Field(min_length=1, max_length=2)


class MappingView(ci.Context):
    id: UUID
    integration_id: UUID
    repository: str
    branch: str
    events: list[str]
    enabled: bool
    webhook_path: str


class IssuedMapping(MappingView):
    secret: str


def cipher(config: Settings) -> Fernet:
    try:
        return Fernet(config.notification_encryption_key.get_secret_value())
    except (ValueError, TypeError):
        raise APIError(
            503, "encryption_unavailable", "Integration encryption is not configured."
        ) from None


def seal(config: Settings, row: GitHubMapping, secret: str) -> str:
    return (
        cipher(config)
        .encrypt(
            json.dumps(
                ["github-v1", str(row.organization_id), str(row.id), secret]
            ).encode()
        )
        .decode()
    )


def unseal(config: Settings, row: GitHubMapping) -> str:
    try:
        data = json.loads(cipher(config).decrypt(row.secret_ciphertext.encode()))
        if data[:3] != ["github-v1", str(row.organization_id), str(row.id)]:
            raise ValueError()
        return str(data[3])
    except (InvalidToken, ValueError, IndexError):
        raise APIError(
            503, "encryption_unavailable", "Integration secret is unavailable."
        ) from None


def valid_signature(raw: bytes, secret: str, signature: str) -> bool:
    return bool(
        re.fullmatch(r"sha256=[0-9a-f]{64}", signature)
    ) and hmac.compare_digest(
        signature, "sha256=" + hmac.digest(secret.encode(), raw, "sha256").hex()
    )


async def mapping_view(row: GitHubMapping, db: DB) -> MappingView:
    from aegis_api.db.models import GatePolicy

    gate = await db.scalar(
        select(GatePolicy).where(
            GatePolicy.organization_id == row.organization_id,
            GatePolicy.id == row.gate_policy_id,
        )
    )
    integration = await db.scalar(
        select(Integration).where(
            Integration.organization_id == row.organization_id,
            Integration.id == row.integration_id,
        )
    )
    assert gate and integration
    return MappingView(
        id=row.id,
        integration_id=row.integration_id,
        project_id=row.project_id,
        target_id=row.target_id,
        policy_id=row.policy_id,
        target_version=row.target_version,
        policy_version=row.policy_version,
        gate_policy_id=row.gate_policy_id,
        gate_policy_version=gate.version,
        environment=row.environment,
        repository=row.repository,
        branch=row.branch,
        events=row.events,
        enabled=integration.status == RecordState.ACTIVE,
        webhook_path=f"/api/hooks/github/{row.id}",
    )


@router.post(
    PREFIX + "/mappings", response_model=IssuedMapping, dependencies=[Depends(csrf)]
)
async def create(
    body: MappingInput, member: Member, db: DB, request: Request
) -> IssuedMapping:
    require(member, "integrations.write")
    context = await ci.resolve(body, member, db)
    identity, integration_id = uuid4(), uuid4()
    secret = secrets.token_urlsafe(32)
    db.add(
        Integration(
            id=integration_id,
            organization_id=member.organization_id,
            provider="github",
            external_installation_id=str(identity),
            allowed_repositories=[body.repository.lower()],
            credential_reference=f"github:{identity}",
            status=RecordState.ACTIVE,
        )
    )
    await db.flush()
    row = GitHubMapping(
        id=identity,
        organization_id=member.organization_id,
        integration_id=integration_id,
        creator_id=member.id,
        **context.model_dump(exclude={"gate_policy_version"}),
        repository=body.repository.lower(),
        branch=body.branch,
        events=sorted(set(body.events)),
        secret_ciphertext="",
    )
    row.secret_ciphertext = seal(request.app.state.config, row, secret)
    db.add(row)
    event(db, member, "github.mapping_created", row.id)
    await db.commit()
    return IssuedMapping(**(await mapping_view(row, db)).model_dump(), secret=secret)


@router.get(PREFIX + "/mappings", response_model=list[MappingView])
async def listing(
    member: Member, db: DB, offset: int = Query(0, ge=0)
) -> list[MappingView]:
    require(member, "integrations.write")
    rows = (
        await db.scalars(
            select(GitHubMapping)
            .where(GitHubMapping.organization_id == member.organization_id)
            .order_by(GitHubMapping.created_at.desc(), GitHubMapping.id)
            .offset(offset)
            .limit(100)
        )
    ).all()
    return [await mapping_view(r, db) for r in rows]


async def scoped(identity: UUID, member: Member, db: DB) -> GitHubMapping:
    require(member, "integrations.write")
    row = await db.scalar(
        select(GitHubMapping).where(
            GitHubMapping.organization_id == member.organization_id,
            GitHubMapping.id == identity,
        )
    )
    if not row:
        raise APIError(404, "not_found", "Mapping not found.")
    return row


class TestResult(BaseModel):
    ok: bool
    message: str


@router.post(
    PREFIX + "/mappings/{identity}/test",
    response_model=TestResult,
    dependencies=[Depends(csrf)],
)
async def test(identity: UUID, member: Member, db: DB, request: Request) -> TestResult:
    row = await scoped(identity, member, db)
    actor = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == member.organization_id,
            OrganizationMember.id == row.creator_id,
            OrganizationMember.status == RecordState.ACTIVE,
        )
    )
    if not actor or actor.role not in ADMIN:
        raise APIError(
            409, "integration_inactive", "Mapping creator authorization is inactive."
        )
    view = await mapping_view(row, db)
    unseal(request.app.state.config, row)
    current = await ci.resolve(view, member, db)
    if not view.enabled or current.model_dump() != view.model_dump(
        include=set(ci.Context.model_fields)
    ):
        raise APIError(
            409,
            "configuration_changed",
            "Recreate the mapping with current configuration.",
        )
    return TestResult(
        ok=True,
        message=(
            "Local authorization, encryption and versions verified. "
            "Send a GitHub ping to verify inbound connectivity."
        ),
    )


class DeliveryView(BaseModel):
    id: UUID
    mapping_id: UUID
    delivery_id: UUID
    event: str
    state: str
    scan_id: UUID | None
    created_at: datetime


@router.get(PREFIX + "/deliveries", response_model=list[DeliveryView])
async def deliveries(
    member: Member, db: DB, offset: int = Query(0, ge=0)
) -> list[DeliveryView]:
    require(member, "integrations.write")
    rows = (
        await db.scalars(
            select(GitHubDelivery)
            .where(GitHubDelivery.organization_id == member.organization_id)
            .order_by(GitHubDelivery.created_at.desc(), GitHubDelivery.id)
            .offset(offset)
            .limit(100)
        )
    ).all()
    return [DeliveryView.model_validate(r, from_attributes=True) for r in rows]


class External(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)


class Repository(External):
    full_name: str = Field(pattern=REPO, max_length=200)


class Ref(External):
    ref: str = Field(pattern=BRANCH, max_length=120)
    sha: str = Field(pattern=SHA)
    repo: Repository


class PullRequest(External):
    number: int = Field(ge=1)
    head: Ref
    base: Ref


class Payload(External):
    repository: Repository
    ref: str | None = Field(default=None, max_length=140)
    after: str | None = Field(default=None, pattern=SHA)
    deleted: bool = False
    action: str | None = Field(default=None, max_length=40)
    pull_request: PullRequest | None = None


def trigger(
    raw: bytes, event_name: str, mapping: GitHubMapping
) -> scans.Trigger | None:
    payload = Payload.model_validate_json(raw)
    if payload.repository.full_name.lower() != mapping.repository:
        raise ValueError("repository")
    if event_name == "ping":
        return None
    if event_name not in mapping.events:
        raise ValueError("event")
    if event_name == "push":
        if (
            payload.deleted
            or payload.ref != f"refs/heads/{mapping.branch}"
            or not payload.after
            or payload.after == "0" * 40
        ):
            raise ValueError("branch")
        return scans.Trigger(
            source="ci",
            repository=mapping.repository,
            branch=mapping.branch,
            commit=payload.after,
        )
    pr = payload.pull_request
    if (
        not pr
        or payload.action not in {"opened", "synchronize", "reopened"}
        or pr.base.ref != mapping.branch
        or pr.base.repo.full_name.lower() != mapping.repository
        or pr.head.repo.full_name.lower() != mapping.repository
    ):
        raise ValueError("pull_request")
    return scans.Trigger(
        source="ci",
        repository=mapping.repository,
        branch=pr.head.ref,
        commit=pr.head.sha,
        pull_request=pr.number,
    )


@router.post("/api/hooks/github/{identity}")
async def receive(identity: UUID, request: Request, db: DB) -> dict[str, str | None]:
    # Identity locates a secret, never grants access. Lock org before mapping.
    row = await db.scalar(select(GitHubMapping).where(GitHubMapping.id == identity))
    if not row:
        raise APIError(404, "not_found", "Integration unavailable.")
    raw = await request.body()
    if not valid_signature(
        raw,
        unseal(request.app.state.config, row),
        request.headers.get("X-Hub-Signature-256", ""),
    ):
        raise APIError(401, "invalid_signature", "Invalid webhook signature.")
    try:
        delivery_id = UUID(request.headers.get("X-GitHub-Delivery", ""))
    except ValueError:
        raise APIError(
            400, "invalid_delivery", "A UUID delivery ID is required."
        ) from None
    event_name = request.headers.get("X-GitHub-Event", "")
    if event_name not in {"push", "pull_request", "ping"}:
        raise APIError(422, "unsupported_event", "Unsupported GitHub event.")
    org = await db.scalar(
        select(Organization)
        .where(
            Organization.id == row.organization_id,
            Organization.status == RecordState.ACTIVE,
        )
        .with_for_update()
    )
    integration = await db.scalar(
        select(Integration)
        .where(
            Integration.organization_id == row.organization_id,
            Integration.id == row.integration_id,
        )
        .execution_options(populate_existing=True)
    )
    member = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == row.organization_id,
            OrganizationMember.id == row.creator_id,
            OrganizationMember.status == RecordState.ACTIVE,
        )
    )
    if (
        not org
        or not integration
        or integration.status != RecordState.ACTIVE
        or not member
        or member.role not in ADMIN
    ):
        raise APIError(
            403, "integration_inactive", "Integration authorization is inactive."
        )
    digest = hashlib.sha256(raw).hexdigest()
    previous = await db.scalar(
        select(GitHubDelivery).where(
            GitHubDelivery.organization_id == row.organization_id,
            GitHubDelivery.mapping_id == row.id,
            or_(
                GitHubDelivery.delivery_id == delivery_id,
                (GitHubDelivery.payload_digest == digest)
                & (GitHubDelivery.event == event_name),
            ),
        )
    )
    if previous:
        if previous.payload_digest != digest or previous.event != event_name:
            raise APIError(409, "delivery_conflict", "Delivery ID was already used.")
        return {
            "state": previous.state,
            "scan_id": str(previous.scan_id) if previous.scan_id else None,
        }
    receipt = GitHubDelivery(
        organization_id=row.organization_id,
        mapping_id=row.id,
        delivery_id=delivery_id,
        payload_digest=digest,
        event=event_name,
        state="rejected",
    )
    db.add(receipt)
    try:
        metadata = trigger(raw, event_name, row)
    except (ValueError, ValidationError):
        await db.commit()
        raise APIError(
            422, "unmapped_event", "Repository, branch or event is not configured."
        ) from None
    if metadata:
        view = await mapping_view(row, db)
        body = ci.Submission(
            **view.model_dump(include=set(ci.Context.model_fields)), trigger=metadata
        )
        try:
            async with db.begin_nested():
                scan = await ci.submit(
                    body,
                    request,
                    member,
                    db,
                    f"github:{row.id}:{delivery_id}",
                    commit=False,
                )
                receipt.scan_id = scan.id
                receipt.state = "accepted"
        except APIError:
            # Retain safe failure metadata; a new delivery is needed after repair.
            receipt.state = "blocked"
    else:
        receipt.state = "ping"
    await db.commit()
    return {
        "state": receipt.state,
        "scan_id": str(receipt.scan_id) if receipt.scan_id else None,
    }
