"""Transactional encrypted identity-mail outbox; SMTP never runs in auth requests."""

import asyncio
import logging
import smtplib
import ssl
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Literal
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aegis_api.auth_models import MailDelivery
from aegis_api.conventions import APIError
from aegis_api.db.enums import RecordState
from aegis_api.db.models import Organization
from aegis_api.settings import Settings


class MailEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    kind: Literal["identity-mail-v1"] = "identity-mail-v1"
    id: UUID
    user_id: UUID | None
    organization_id: UUID | None
    purpose: Literal["reset", "verify", "invite"]
    email: str = Field(max_length=320, repr=False)
    token: str = Field(max_length=256, repr=False)


def utcnow() -> datetime:
    return datetime.now(UTC)


async def enqueue(
    db: AsyncSession,
    config: Settings,
    email: str,
    purpose: str,
    token: str,
    user_id: UUID | None,
    organization_id: UUID | None = None,
) -> None:
    if (purpose == "invite") != (organization_id is not None):
        raise ValueError("Identity mail organization binding is invalid")
    identity = uuid4()
    ciphertext = None
    if config.smtp_host:
        try:
            cipher = Fernet(config.notification_encryption_key.get_secret_value())
        except (ValueError, TypeError):
            raise APIError(
                503, "encryption_unavailable", "Mail encryption is unavailable."
            ) from None
        # Empty-token cover jobs take the same encryption/enqueue path for absent
        # accounts, but are discarded by the worker without contacting SMTP.
        payload = MailEnvelope.model_validate(
            {
                "id": identity,
                "user_id": user_id,
                "organization_id": organization_id,
                "purpose": purpose,
                "email": email,
                "token": token,
            }
        )
        ciphertext = cipher.encrypt(payload.model_dump_json().encode()).decode()

    db.add(
        MailDelivery(
            id=identity,
            user_id=user_id,
            organization_id=organization_id,
            purpose=purpose,
            status="pending" if config.smtp_host else "unconfigured",
            payload_ciphertext=ciphertext,
            attempts=0,
            retry_at=utcnow(),
            expires_at=utcnow() + timedelta(minutes=config.reset_minutes),
        )
    )


def send(config: Settings, email: str, purpose: str, token: str) -> None:
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
    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=10) as smtp:
        if config.smtp_starttls:
            smtp.starttls(context=ssl.create_default_context())
        if config.smtp_username:
            smtp.login(config.smtp_username, config.smtp_password.get_secret_value())
        smtp.send_message(message)


async def deliver_one(db: AsyncSession, config: Settings) -> bool:
    row = await db.scalar(
        select(MailDelivery)
        .where(
            MailDelivery.status == "pending",
            MailDelivery.retry_at <= utcnow(),
        )
        .order_by(MailDelivery.retry_at, MailDelivery.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if row is None:
        return False
    if row.expires_at is None or row.expires_at <= utcnow():
        row.status, row.payload_ciphertext = "expired", None
        return True
    if not config.smtp_host:
        return False
    try:
        data = MailEnvelope.model_validate_json(
            Fernet(config.notification_encryption_key.get_secret_value()).decrypt(
                (row.payload_ciphertext or "").encode()
            )
        )
        if (data.id, data.user_id, data.purpose, data.organization_id) != (
            row.id,
            row.user_id,
            row.purpose,
            row.organization_id,
        ):
            raise ValueError("Mail envelope mismatch")
        if not data.token:
            row.status, row.payload_ciphertext = "discarded", None
            return True
    except Exception:
        # Never include provider errors, recipient addresses or tokens in logs.
        row.status, row.payload_ciphertext = "failed", None
        return True
    if row.organization_id:
        org = await db.get(Organization, row.organization_id)
        if not org or org.status != RecordState.ACTIVE:
            row.status, row.payload_ciphertext = "failed", None
            return True
    row.attempts += 1
    try:
        await asyncio.to_thread(send, config, data.email, row.purpose, data.token)
    except (OSError, smtplib.SMTPException):
        if row.attempts >= 3:
            row.status, row.payload_ciphertext = "failed", None
        else:
            row.retry_at = utcnow() + timedelta(seconds=30 * row.attempts)
    else:
        row.status, row.payload_ciphertext = "sent", None
    return True


async def coordinate(
    sessions: async_sessionmaker[AsyncSession], config: Settings
) -> None:
    while True:
        try:
            async with sessions() as db, db.begin():
                found = await deliver_one(db, config)
            if not found:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger("aegis.identity_mail").error(
                "Identity mail worker unavailable"
            )
            await asyncio.sleep(5)
