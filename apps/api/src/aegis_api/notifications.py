"""Encrypted destinations and bounded, DNS-pinned outbound notification adapters."""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import re
import smtplib
import socket
from datetime import datetime
from email.message import EmailMessage
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import aiohttp
from aiohttp.abc import AbstractResolver, ResolveResult
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, HttpUrl, SecretStr
from sqlalchemy import select

from aegis_api.auth import DB, EmailPayload, Payload, csrf, now
from aegis_api.configuration import scoped_project
from aegis_api.conventions import APIError
from aegis_api.db.enums import NotificationState
from aegis_api.db.models import NotificationDelivery, NotificationDestination
from aegis_api.organizations import Member, require
from aegis_api.settings import Settings
from aegis_api.target_validation import permitted_ip

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])
EventKind = Literal[
    "scan.completed",
    "scan.failed",
    "policy.failed",
    "finding.high",
    "report.ready",
    "exception.expiring",
]


class DestinationInput(Payload):
    name: str = Field(min_length=1, max_length=120)
    project_id: UUID | None = None
    kind: Literal["email", "slack", "webhook", "github"]
    address: SecretStr = Field(max_length=2000)
    secret: SecretStr = Field(default=SecretStr(""), max_length=2000)
    subscriptions: list[EventKind] = Field(min_length=1, max_length=6)


class DestinationView(BaseModel):
    id: UUID
    name: str
    project_id: UUID | None
    kind: str
    enabled: bool
    subscriptions: list[str]


class DeliveryView(BaseModel):
    id: UUID
    destination_id: UUID
    event_key: str | None
    state: NotificationState
    attempts: int
    next_attempt_at: datetime | None
    failure_code: str | None


class NotificationPayload(BaseModel):
    event: EventKind
    organization_id: UUID
    resource_id: UUID
    link: str
    notice: Literal[
        "Redacted notification; details require AegisForge authorization."
    ] = "Redacted notification; details require AegisForge authorization."


def seal(config: Settings, org: UUID, identity: UUID, body: DestinationInput) -> str:
    key = config.notification_encryption_key.get_secret_value()
    try:
        cipher = Fernet(key)
    except (ValueError, TypeError):
        raise APIError(
            503,
            "encryption_unavailable",
            "Notification encryption key is not configured.",
        ) from None
    return cipher.encrypt(
        json.dumps(
            {
                "organization_id": str(org),
                "id": str(identity),
                "address": body.address.get_secret_value(),
                "secret": body.secret.get_secret_value(),
            }
        ).encode()
    ).decode()


def unseal(config: Settings, row: NotificationDestination) -> tuple[str, str]:
    data = json.loads(
        Fernet(config.notification_encryption_key.get_secret_value()).decrypt(
            (row.configuration_ciphertext or "").encode()
        )
    )
    if data["organization_id"] != str(row.organization_id) or data["id"] != str(row.id):
        raise ValueError("Destination scope mismatch")
    return str(data["address"]), str(data["secret"])


def validate_url(address: str) -> str:
    url = urlsplit(address)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.port not in (None, 443)
        or url.fragment
        or any(ord(c) < 33 for c in address)
    ):
        raise ValueError(
            "Use an HTTPS destination on port 443 without credentials or fragment"
        )
    try:
        ip = ipaddress.ip_address(url.hostname)
    except ValueError:
        if url.hostname.lower() == "localhost" or url.hostname.endswith(
            (".localhost", ".local", ".internal")
        ):
            raise ValueError("Private destination") from None
    else:
        if not permitted_ip(str(ip)):
            raise ValueError("Private destination")
    return url.hostname


class PublicResolver(AbstractResolver):
    async def resolve(
        self, host: str, port: int = 0, family: int = socket.AF_INET
    ) -> list[ResolveResult]:
        results = await asyncio.get_running_loop().getaddrinfo(
            host, port, family=family, type=socket.SOCK_STREAM
        )
        if not results or any(not permitted_ip(str(item[4][0])) for item in results):
            raise ValueError("Private DNS destination")
        return [
            ResolveResult(
                hostname=host,
                host=str(item[4][0]),
                port=port,
                family=item[0],
                proto=item[2],
                flags=socket.AI_NUMERICHOST,
            )
            for item in results
        ]

    async def close(self) -> None:
        pass


def signed_headers(secret: str, timestamp: int, payload: bytes) -> dict[str, str]:
    signature = hmac.new(
        secret.encode(), str(timestamp).encode() + b"." + payload, hashlib.sha256
    ).hexdigest()
    return {
        "X-Aegis-Timestamp": str(timestamp),
        "X-Aegis-Signature": "sha256=" + signature,
    }


async def validate_destination(body: DestinationInput) -> None:
    address = body.address.get_secret_value()
    if body.kind == "email":
        EmailPayload(email=address)
        if any(c in address for c in "\r\n"):
            raise ValueError("Invalid email")
        return
    host = validate_url(address)
    if body.kind == "slack" and (
        host != "hooks.slack.com" or not urlsplit(address).path.startswith("/services/")
    ):
        raise ValueError("Slack incoming webhook required")
    if body.kind == "github" and (
        host != "api.github.com"
        or not re.fullmatch(
            r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*/comments",
            urlsplit(address).path,
        )
        or urlsplit(address).query
    ):
        raise ValueError("GitHub pull request comment endpoint required")
    if body.kind in {"github", "webhook"} and len(body.secret.get_secret_value()) < 32:
        raise ValueError("A secret of at least 32 characters is required")
    await asyncio.wait_for(
        PublicResolver().resolve(host, 443, socket.AF_UNSPEC), timeout=10
    )


class PullRequestLink(BaseModel):
    url: HttpUrl


class GitHubIssue(BaseModel):
    pull_request: PullRequestLink


async def send(
    config: Settings,
    destination: NotificationDestination,
    payload: NotificationPayload,
    delivery_id: UUID,
) -> None:
    address, secret = unseal(config, destination)
    text = f"AegisForge: {payload.event}\n{payload.link}\n{payload.notice}"
    if destination.kind == "email":
        EmailPayload(email=address)
        message = EmailMessage()
        message["From"] = config.smtp_sender
        message["To"] = address
        message["Subject"] = f"AegisForge: {payload.event}"
        message["Message-ID"] = f"<{delivery_id}@aegisforge>"
        message.set_content(text)

        def email() -> None:
            if not config.smtp_host:
                raise ValueError("SMTP unavailable")
            with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=10) as smtp:
                if config.smtp_starttls:
                    smtp.starttls()
                if config.smtp_username:
                    smtp.login(
                        config.smtp_username, config.smtp_password.get_secret_value()
                    )
                smtp.send_message(message)

        await asyncio.to_thread(email)
        return
    validate_url(address)
    headers = {"Content-Type": "application/json", "X-Aegis-Delivery": str(delivery_id)}
    if destination.kind == "webhook":
        data = payload.model_dump_json().encode()
        headers.update(signed_headers(secret, int(now().timestamp()), data))
    elif destination.kind == "slack":
        data = json.dumps({"text": text}).encode()
    elif destination.kind == "github":
        # Only an issue URL verified as a PR during the delivery is eligible.
        data = json.dumps(
            {"body": text + f"\n<!-- aegis-delivery:{delivery_id} -->"}
        ).encode()
        headers["Authorization"] = "Bearer " + secret
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    else:
        raise ValueError("Unknown adapter")
    connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False)
    async with aiohttp.ClientSession(
        connector=connector, timeout=aiohttp.ClientTimeout(total=15), trust_env=False
    ) as client:
        if destination.kind == "github":
            async with client.get(
                address.removesuffix("/comments"),
                headers=headers,
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    raise ValueError("PR unavailable")
                raw = b""
                while len(raw) <= 65536:
                    chunk = await response.content.read(65537 - len(raw))
                    if not chunk:
                        break
                    raw += chunk
                if len(raw) > 65536:
                    raise ValueError("Not a pull request")
                GitHubIssue.model_validate_json(raw)
        async with client.post(
            address, data=data, headers=headers, allow_redirects=False
        ) as response:
            if not 200 <= response.status < 300:
                raise ValueError("Notification delivery rejected")
            # Never retain or log provider response bodies.


def destination_view(row: NotificationDestination) -> DestinationView:
    return DestinationView(
        id=row.id,
        name=row.name,
        project_id=row.project_id,
        kind=row.kind,
        enabled=row.enabled,
        subscriptions=row.subscriptions,
    )


@router.post(
    "/destinations",
    response_model=DestinationView,
    status_code=201,
    dependencies=[Depends(csrf)],
)
async def create(
    body: DestinationInput, member: Member, db: DB, request: Request
) -> DestinationView:
    require(member, "integrations.write")
    if body.project_id:
        await scoped_project(body.project_id, member, db)
    try:
        await validate_destination(body)
    except (ValueError, OSError):
        raise APIError(
            422,
            "destination_invalid",
            "Destination or secret is invalid, private, or unresolved.",
        ) from None
    identity = uuid4()
    row = NotificationDestination(
        id=identity,
        organization_id=member.organization_id,
        name=body.name,
        project_id=body.project_id,
        kind=body.kind,
        address_reference=f"encrypted:{identity}",
        enabled=True,
        verified_at=now(),
        subscriptions=sorted(set(body.subscriptions)),
        configuration_ciphertext=seal(
            request.app.state.config, member.organization_id, identity, body
        ),
    )
    db.add(row)
    await db.commit()
    return destination_view(row)


@router.get("/destinations", response_model=list[DestinationView])
async def listing(member: Member, db: DB) -> list[DestinationView]:
    require(member, "integrations.write")
    return [
        destination_view(r)
        for r in (
            await db.scalars(
                select(NotificationDestination)
                .where(
                    NotificationDestination.organization_id == member.organization_id
                )
                .order_by(
                    NotificationDestination.created_at, NotificationDestination.id
                )
            )
        ).all()
    ]


@router.delete("/destinations/{destination_id}", dependencies=[Depends(csrf)])
async def disable(destination_id: UUID, member: Member, db: DB) -> dict[str, bool]:
    require(member, "integrations.write")
    row = await db.scalar(
        select(NotificationDestination)
        .where(
            NotificationDestination.organization_id == member.organization_id,
            NotificationDestination.id == destination_id,
        )
        .with_for_update()
    )
    if not row:
        raise APIError(404, "not_found", "Destination not found.")
    row.enabled = False
    row.version += 1
    await db.commit()
    return {"ok": True}


@router.get("/deliveries", response_model=list[DeliveryView])
async def deliveries(
    member: Member, db: DB, offset: int = Query(0, ge=0)
) -> list[DeliveryView]:
    require(member, "integrations.write")
    rows = (
        await db.scalars(
            select(NotificationDelivery)
            .where(NotificationDelivery.organization_id == member.organization_id)
            .order_by(NotificationDelivery.created_at.desc(), NotificationDelivery.id)
            .offset(offset)
            .limit(100)
        )
    ).all()
    return [DeliveryView.model_validate(r, from_attributes=True) for r in rows]


@router.post(
    "/deliveries/{delivery_id}/retry",
    response_model=DeliveryView,
    dependencies=[Depends(csrf)],
)
async def retry(delivery_id: UUID, member: Member, db: DB) -> DeliveryView:
    require(member, "integrations.write")
    row = await db.scalar(
        select(NotificationDelivery)
        .where(
            NotificationDelivery.organization_id == member.organization_id,
            NotificationDelivery.id == delivery_id,
        )
        .with_for_update()
    )
    if not row:
        raise APIError(404, "not_found", "Delivery not found.")
    if row.state not in {NotificationState.DEAD_LETTER, NotificationState.FAILED}:
        raise APIError(
            409, "retry_unavailable", "Only failed deliveries can be retried."
        )
    row.state = NotificationState.PENDING
    row.next_attempt_at = now()
    # Keep lifetime attempts; each manual retry permits one additional attempt.
    await db.commit()
    return DeliveryView.model_validate(row, from_attributes=True)
