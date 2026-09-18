"""One-time high-entropy organization credentials. Session auth stays separate."""

import hashlib
import secrets
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from redis.exceptions import RedisError
from sqlalchemy import select

from aegis_api.auth import DB, Payload, csrf, now
from aegis_api.conventions import APIError
from aegis_api.db.enums import RecordState
from aegis_api.db.models import APIKey, AuditLog, Organization, OrganizationMember
from aegis_api.organizations import ADMIN, Member

router = APIRouter(
    prefix="/api/v1/api-keys", tags=["API key management (session only)"]
)
Scope = Literal[
    "scans:create", "scans:read", "findings:read", "reports:read", "integrations:write"
]


class KeyInput(Payload):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[Scope] = Field(min_length=1, max_length=5)
    expires_at: datetime


class KeyView(BaseModel):
    id: UUID
    name: str
    prefix: str
    scopes: list[str]
    creator: UUID
    last_used_at: datetime | None
    expires_at: datetime
    revoked_at: datetime | None


class IssuedKey(KeyView):
    secret: str


def key_view(row: APIKey) -> KeyView:
    return KeyView(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        scopes=row.permission_scopes,
        creator=row.issued_by_id,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )


def issue_secret() -> tuple[str, str, str]:
    secret = "agf_" + secrets.token_urlsafe(32)
    return secret, secret[:16], hashlib.sha256(secret.encode()).hexdigest()


def audit_key(db: DB, row: APIKey, action: str) -> None:
    db.add(
        AuditLog(
            organization_id=row.organization_id,
            actor_id=row.issued_by_id,
            action=action,
            resource_type="api_key",
            resource_id=row.id,
            changed_fields=[],
            request_id=uuid4(),
        )
    )


@router.post(
    "", response_model=IssuedKey, status_code=201, dependencies=[Depends(csrf)]
)
async def create(body: KeyInput, member: Member, db: DB) -> IssuedKey:
    if member.role not in ADMIN:
        raise APIError(403, "forbidden", "Organization administrator required.")
    if body.expires_at.tzinfo is None or body.expires_at <= now():
        raise APIError(
            422, "invalid_expiry", "Expiry must be a future timezone-aware timestamp."
        )
    secret, prefix, digest = issue_secret()
    row = APIKey(
        id=uuid4(),
        organization_id=member.organization_id,
        issued_by_id=member.id,
        project_id=None,
        name=body.name,
        prefix=prefix,
        key_hash=digest,
        permission_scopes=sorted(set(body.scopes)),
        expires_at=body.expires_at,
    )
    db.add(row)
    audit_key(db, row, "api_key.created")
    await db.commit()
    return IssuedKey(**key_view(row).model_dump(), secret=secret)


@router.get("", response_model=list[KeyView])
async def listing(member: Member, db: DB) -> list[KeyView]:
    if member.role not in ADMIN:
        raise APIError(403, "forbidden", "Organization administrator required.")
    rows = (
        await db.scalars(
            select(APIKey)
            .where(APIKey.organization_id == member.organization_id)
            .order_by(APIKey.created_at.desc(), APIKey.id)
        )
    ).all()
    return [key_view(row) for row in rows]


@router.delete("/{key_id}", dependencies=[Depends(csrf)])
async def revoke(key_id: UUID, member: Member, db: DB) -> dict[str, bool]:
    if member.role not in ADMIN:
        raise APIError(403, "forbidden", "Organization administrator required.")
    row = await db.scalar(
        select(APIKey)
        .where(APIKey.organization_id == member.organization_id, APIKey.id == key_id)
        .with_for_update()
    )
    if not row:
        raise APIError(404, "not_found", "Key not found.")
    row.revoked_at = row.revoked_at or now()
    audit_key(db, row, "api_key.revoked")
    await db.commit()
    return {"ok": True}


bearer = HTTPBearer(
    scheme_name="OrganizationAPIKey",
    description=(
        "Organization API key, displayed once at issuance. "
        "Session credentials are not accepted."
    ),
    auto_error=False,
)


def access(
    scope: Scope,
) -> Callable[..., Awaitable[OrganizationMember]]:
    async def authenticate(
        request: Request,
        db: DB,
        credential: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
    ) -> OrganizationMember:
        if (
            credential is None
            or not credential.credentials.startswith("agf_")
            or len(credential.credentials) != 47
        ):
            raise APIError(401, "api_key_invalid", "Valid API key required.")
        digest = hashlib.sha256(credential.credentials.encode()).hexdigest()
        row = await db.scalar(select(APIKey).where(APIKey.key_hash == digest))
        if (
            not row
            or row.revoked_at
            or row.expires_at <= now()
            or row.project_id is not None
        ):
            raise APIError(401, "api_key_invalid", "Valid API key required.")
        org = await db.scalar(
            select(Organization).where(
                Organization.id == row.organization_id,
                Organization.status == RecordState.ACTIVE,
            )
        )
        member = await db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == row.organization_id,
                OrganizationMember.id == row.issued_by_id,
                OrganizationMember.status == RecordState.ACTIVE,
            )
        )
        if not org or not member or member.role not in ADMIN:
            raise APIError(401, "api_key_invalid", "Valid API key required.")
        script = (
            "local n=redis.call('INCR',KEYS[1]); "
            "if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n"
        )
        try:
            count = await request.app.state.redis.eval(script, 1, f"api-key:{row.id}")
        except RedisError:
            raise APIError(
                503,
                "rate_limit_unavailable",
                "API key authentication temporarily unavailable.",
            ) from None
        row.last_used_at = now()
        action = "api_key.used"
        error = None
        if int(count) > request.app.state.config.api_key_rate_limit:
            action = "api_key.rate_limited"
            error = APIError(429, "rate_limited", "API key minute quota exceeded.")
        elif scope not in row.permission_scopes:
            action = "api_key.scope_denied"
            error = APIError(403, "scope_required", f"Required scope: {scope}")
        audit_key(db, row, action)
        await db.commit()  # Retain usage even if the downstream request fails.
        if error:
            raise error
        # The audit commit releases locks. Revalidate current authority under
        # the same organization lock used by session commands and revocation.
        org = await db.scalar(
            select(Organization)
            .where(
                Organization.id == row.organization_id,
                Organization.status == RecordState.ACTIVE,
            )
            .with_for_update()
        )
        await db.refresh(row)
        await db.refresh(member)
        if (
            not org
            or row.revoked_at
            or row.expires_at <= now()
            or member.status != RecordState.ACTIVE
            or member.role not in ADMIN
        ):
            raise APIError(401, "api_key_invalid", "Valid API key required.")
        if scope not in row.permission_scopes:
            raise APIError(403, "scope_required", f"Required scope: {scope}")
        request.state.api_key_id = row.id
        return member

    return authenticate
