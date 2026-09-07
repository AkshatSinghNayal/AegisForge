"""Opaque credentials, transactional rotation and reusable authorization boundaries."""

import asyncio
import hashlib
import hmac
import secrets
import smtplib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from aegis_api.auth_models import (
    AccessCredential,
    IdentityAudit,
    IdentityToken,
    MailDelivery,
)
from aegis_api.conventions import APIError
from aegis_api.db.enums import RecordState
from aegis_api.db.models import Organization, OrganizationMember, RefreshSession, User

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


def now() -> datetime:
    return datetime.now(UTC)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(
        password.encode(),
        salt=bytes.fromhex(salt),
        n=2**15,
        r=8,
        p=3,
        maxmem=64 * 1024 * 1024,
    ).hex()
    return f"scrypt${salt}${value}"


DUMMY_HASH = password_hash("dummy password that is never a credential")


def password_matches(password: str, encoded: str | None) -> bool:
    target = encoded or DUMMY_HASH
    matches = hmac.compare_digest(password_hash(password, target.split("$")[1]), target)
    return matches and encoded is not None


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class EmailPayload(Payload):
    email: str = Field(max_length=320)

    @field_validator("email")
    @classmethod
    def normalize(cls, value: str) -> str:
        value = value.strip().lower()
        if value.count("@") != 1 or any(c.isspace() for c in value):
            raise ValueError("Enter a valid email address")
        local, domain = value.split("@")
        if (
            not local
            or "." not in domain
            or domain.startswith(".")
            or domain.endswith(".")
        ):
            raise ValueError("Enter a valid email address")
        return value


class Login(EmailPayload):
    password: str = Field(min_length=1, max_length=128)


class Register(Login):
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    organization_name: str = Field(min_length=1, max_length=120)


class TokenPayload(Payload):
    token: str = Field(min_length=32, max_length=128)


class Reset(TokenPayload):
    password: str = Field(min_length=12, max_length=128)


class Message(BaseModel):
    message: str


class Credential(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


class OrganizationView(BaseModel):
    id: UUID
    name: str
    role: str


class Me(BaseModel):
    id: UUID
    email: str
    display_name: str
    email_verified: bool
    organizations: list[OrganizationView]


async def session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessions() as db:
        try:
            yield db
        except APIError:
            await db.rollback()
            audit(db, request, "authorization.request_rejected")
            await db.commit()
            raise


DB = Annotated[AsyncSession, Depends(session)]


def audit(
    db: AsyncSession, request: Request, action: str, user_id: UUID | None = None
) -> None:
    db.add(IdentityAudit(user_id=user_id, action=action, request_id=uuid4()))


async def rate_limit(request: Request, db: AsyncSession, identity: str = "") -> None:
    # Atomic fixed window, shared by all API processes. Never trust forwarded IPs.
    ip = request.client.host if request.client else "unknown"
    keys = ["auth:ip:" + digest(ip)]
    if identity:
        keys.append("auth:identity:" + digest(identity))
    script = (
        "local n=redis.call('INCR',KEYS[1]); "
        "if n==1 then redis.call('EXPIRE',KEYS[1],300) end; return n"
    )
    for key in keys:
        count = await request.app.state.redis.eval(script, 1, key)
        if int(count) > request.app.state.config.auth_rate_limit:
            audit(db, request, "authentication.rate_limited")
            await db.commit()
            raise APIError(429, "rate_limited", "Too many attempts. Try again later.")


async def csrf(request: Request, db: DB) -> None:
    origin = request.headers.get("origin")
    cookie = request.cookies.get("aegis_csrf", "")
    header = request.headers.get("x-csrf-token", "")
    if (
        origin != request.app.state.config.app_origin
        or len(cookie) < 32
        or not hmac.compare_digest(cookie, header)
    ):
        raise APIError(403, "csrf_failed", "Request could not be verified.")


@router.get("/csrf")
async def csrf_cookie(request: Request, response: Response) -> dict[str, str]:
    token = request.cookies.get("aegis_csrf") or secrets.token_urlsafe(32)
    response.set_cookie(
        "aegis_csrf",
        token,
        secure=request.app.state.config.cookie_secure,
        httponly=True,
        samesite="strict",
        path="/api/v1",
        max_age=86400,
    )
    return {"csrf_token": token}


async def principal(request: Request, db: DB) -> tuple[User, AccessCredential]:
    raw = request.headers.get("authorization", "")
    if not raw.startswith("Bearer ") or len(raw) > 256:
        raise APIError(401, "unauthorized", "Sign in to continue.")
    credential = await db.scalar(
        select(AccessCredential).where(
            AccessCredential.token_hash == digest(raw[7:]),
            AccessCredential.revoked_at.is_(None),
            AccessCredential.expires_at > now(),
        )
    )
    user = await db.get(User, credential.user_id) if credential else None
    if not user or user.status != RecordState.ACTIVE or not credential:
        raise APIError(401, "unauthorized", "Sign in to continue.")
    return user, credential


Principal = Annotated[tuple[User, AccessCredential], Depends(principal)]


async def revoke(
    db: AsyncSession, user_id: UUID, family_id: UUID | None = None
) -> None:
    for model in (RefreshSession, AccessCredential):
        query = update(model).where(
            model.user_id == user_id, model.revoked_at.is_(None)
        )
        if family_id:
            query = query.where(model.family_id == family_id)
        await db.execute(query.values(revoked_at=now()))


async def issue(
    request: Request,
    response: Response,
    db: AsyncSession,
    user: User,
    previous: RefreshSession | None = None,
) -> Credential:
    config = request.app.state.config
    refresh, access = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    expiry = (
        previous.expires_at if previous else now() + timedelta(days=config.refresh_days)
    )
    item = RefreshSession(
        id=uuid4(),
        user_id=user.id,
        token_hash=digest(refresh),
        family_id=previous.family_id if previous else uuid4(),
        expires_at=expiry,
        idle_expires_at=min(expiry, now() + timedelta(days=7)),
    )
    db.add(item)
    await db.flush()
    if previous:
        previous.replaced_by_id = item.id
        previous.revoked_at = now()
        previous.last_used_at = now()
    db.add(
        AccessCredential(
            user_id=user.id,
            family_id=item.family_id,
            token_hash=digest(access),
            expires_at=now() + timedelta(seconds=config.access_seconds),
        )
    )
    response.set_cookie(
        "aegis_refresh",
        refresh,
        httponly=True,
        secure=config.cookie_secure,
        samesite="strict",
        path="/api/v1/auth",
        max_age=int((expiry - now()).total_seconds()),
    )
    return Credential(access_token=access, expires_in=config.access_seconds)


async def deliver(
    request: Request,
    db: AsyncSession,
    email: str,
    purpose: str,
    token: str,
    user_id: UUID | None = None,
) -> None:
    config = request.app.state.config
    route = {
        "reset": "reset-password",
        "verify": "verify-email",
        "invite": "accept-invite",
    }[purpose]
    message = EmailMessage()
    message["From"], message["To"] = config.smtp_sender, email
    message["Subject"] = f"AegisForge: {purpose}"
    message.set_content(
        f"Open this single-use link: {config.app_origin}/auth/{route}#token={token}\n"
        "If you did not request this, ignore this message."
    )

    def send() -> None:
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=10) as smtp:
            if config.smtp_starttls:
                smtp.starttls()
            if config.smtp_username:
                smtp.login(
                    config.smtp_username, config.smtp_password.get_secret_value()
                )
            smtp.send_message(message)

    status = "unconfigured"
    if config.smtp_host:
        try:
            await asyncio.to_thread(send)
            status = "sent"
        except (OSError, smtplib.SMTPException):
            status = "failed"
    db.add(MailDelivery(user_id=user_id, purpose=purpose, status=status))


async def identity_token(
    request: Request, db: AsyncSession, user: User, purpose: str
) -> None:
    token = secrets.token_urlsafe(48)
    db.add(
        IdentityToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=digest(token),
            expires_at=now()
            + timedelta(minutes=request.app.state.config.reset_minutes),
        )
    )
    await deliver(request, db, user.normalized_email, purpose, token, user.id)


@router.post("/register", response_model=Message, dependencies=[Depends(csrf)])
async def register(body: Register, request: Request, db: DB) -> Message:
    await rate_limit(request, db, body.email)
    # Serialize account creation/reset/login without holding a password in SQL or logs.
    from sqlalchemy import text

    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": int(digest(body.email)[:15], 16)},
    )
    existing = await db.scalar(select(User).where(User.normalized_email == body.email))
    encoded = await run_in_threadpool(password_hash, body.password)
    if not existing:
        from aegis_api.db.enums import Role

        user = User(
            normalized_email=body.email,
            password_hash=encoded,
            display_name=body.display_name,
        )
        org = Organization(name=body.organization_name, slug=uuid4().hex)
        db.add_all([user, org])
        await db.flush()
        member = OrganizationMember(
            organization_id=org.id, user_id=user.id, role=Role.OWNER
        )
        db.add(member)
        await db.flush()
        from aegis_api.organizations import event

        event(db, member, "organization.created", org.id)
        event(db, member, "membership.created", member.id)
        audit(db, request, "authentication.registered", user.id)
        await identity_token(request, db, user, "verify")
    else:
        audit(db, request, "authentication.registration_requested")
    await db.commit()
    return Message(
        message=(
            "Registration received. You can sign in if your account is available. "
            "Check your email for verification."
        )
    )


@router.post("/sign-in", response_model=Credential, dependencies=[Depends(csrf)])
async def sign_in(
    body: Login, request: Request, response: Response, db: DB
) -> Credential:
    await rate_limit(request, db, body.email)
    user = await db.scalar(
        select(User).where(User.normalized_email == body.email).with_for_update()
    )
    valid = await run_in_threadpool(
        password_matches, body.password, user.password_hash if user else None
    )
    if not user or not valid or user.status != RecordState.ACTIVE:
        audit(db, request, "authentication.sign_in_failed")
        await db.commit()
        raise APIError(401, "invalid_credentials", "Email or password is incorrect.")
    result = await issue(request, response, db, user)
    audit(db, request, "authentication.signed_in", user.id)
    await db.commit()
    return result


@router.post("/refresh", response_model=Credential, dependencies=[Depends(csrf)])
async def refresh(request: Request, response: Response, db: DB) -> Credential:
    raw = request.cookies.get("aegis_refresh", "")
    item = await db.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == digest(raw))
    )
    if not item:
        audit(db, request, "authentication.refresh_failed")
        await db.commit()
        raise APIError(401, "invalid_session", "Sign in to continue.")
    # All session mutations serialize on user, avoiding refresh/reset/revoke races.
    user = await db.scalar(
        select(User).where(User.id == item.user_id).with_for_update()
    )
    await db.refresh(item)
    if (
        item.revoked_at
        or item.replaced_by_id
        or item.expires_at <= now()
        or item.idle_expires_at <= now()
        or not user
        or user.status != RecordState.ACTIVE
    ):
        await revoke(db, item.user_id, item.family_id)
        audit(db, request, "authentication.refresh_rejected", item.user_id)
        await db.commit()
        raise APIError(401, "invalid_session", "Sign in to continue.")
    result = await issue(request, response, db, user, item)
    audit(db, request, "authentication.refreshed", user.id)
    await db.commit()
    return result


@router.get("/me", response_model=Me)
async def me(actor: Principal, db: DB) -> Me:
    user, _ = actor
    rows = (
        await db.execute(
            select(Organization, OrganizationMember)
            .join(
                OrganizationMember,
                OrganizationMember.organization_id == Organization.id,
            )
            .where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.status == RecordState.ACTIVE,
                Organization.status == RecordState.ACTIVE,
            )
            .order_by(Organization.name)
        )
    ).all()
    return Me(
        id=user.id,
        email=user.normalized_email,
        display_name=user.display_name,
        email_verified=user.email_verified_at is not None,
        organizations=[
            OrganizationView(id=o.id, name=o.name, role=m.role) for o, m in rows
        ],
    )


@router.post("/sign-out", response_model=Message, dependencies=[Depends(csrf)])
@router.post("/revoke-all", response_model=Message, dependencies=[Depends(csrf)])
async def sign_out(
    request: Request, response: Response, actor: Principal, db: DB
) -> Message:
    user, credential = actor
    await db.scalar(select(User).where(User.id == user.id).with_for_update())
    all_sessions = request.url.path.endswith("revoke-all")
    await revoke(db, user.id, None if all_sessions else credential.family_id)
    audit(
        db,
        request,
        "authentication.revoked_all" if all_sessions else "authentication.signed_out",
        user.id,
    )
    await db.commit()
    response.delete_cookie(
        "aegis_refresh",
        path="/api/v1/auth",
        secure=request.app.state.config.cookie_secure,
        httponly=True,
        samesite="strict",
    )
    return Message(message="Signed out.")


@router.post("/forgot-password", response_model=Message, dependencies=[Depends(csrf)])
async def forgot(body: EmailPayload, request: Request, db: DB) -> Message:
    await rate_limit(request, db, body.email)
    user = await db.scalar(select(User).where(User.normalized_email == body.email))
    if user and user.status == RecordState.ACTIVE:
        await identity_token(request, db, user, "reset")
    audit(db, request, "authentication.password_reset_requested")
    await db.commit()
    return Message(message="If the account is available, a reset link will be sent.")


@router.post("/reset-password", response_model=Message, dependencies=[Depends(csrf)])
@router.post("/verify-email", response_model=Message, dependencies=[Depends(csrf)])
async def consume(body: Reset | TokenPayload, request: Request, db: DB) -> Message:
    await rate_limit(request, db)
    purpose = "reset" if request.url.path.endswith("reset-password") else "verify"
    item = await db.scalar(
        select(IdentityToken).where(
            IdentityToken.token_hash == digest(body.token),
            IdentityToken.purpose == purpose,
        )
    )
    if item:
        user = await db.scalar(
            select(User).where(User.id == item.user_id).with_for_update()
        )
        await db.refresh(item)
    else:
        user = None
    if (
        not item
        or item.used_at
        or item.expires_at <= now()
        or not user
        or user.status != RecordState.ACTIVE
    ):
        audit(db, request, "authentication.token_rejected")
        await db.commit()
        raise APIError(400, "invalid_token", "Link is invalid or expired.")
    if purpose == "reset":
        if not isinstance(body, Reset):
            raise APIError(422, "invalid_request", "A new password is required.")
        user.password_hash = await run_in_threadpool(password_hash, body.password)
        await revoke(db, user.id)
        await db.execute(
            update(IdentityToken)
            .where(
                IdentityToken.user_id == user.id,
                IdentityToken.purpose == "reset",
                IdentityToken.used_at.is_(None),
            )
            .values(used_at=now())
        )
    else:
        user.email_verified_at = now()
    item.used_at = now()
    audit(
        db,
        request,
        "authentication.password_reset"
        if purpose == "reset"
        else "authentication.email_verified",
        user.id,
    )
    await db.commit()
    return Message(
        message="Password updated. Sign in again."
        if purpose == "reset"
        else "Email verified."
    )
