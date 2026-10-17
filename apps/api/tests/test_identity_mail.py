"""Public auth must not await SMTP; queued secrets are bounded and authenticated."""

import smtplib
import ssl
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from test_auth import client, register  # noqa: F401
from test_health import settings

from aegis_api import auth, identity_mail, notifications
from aegis_api.auth_models import MailDelivery
from aegis_api.settings import Settings

REAL_DELIVER = auth.deliver


def config():
    return settings().model_copy(
        update={
            "smtp_host": "smtp.example.test",
            "notification_encryption_key": SecretStr(Fernet.generate_key().decode()),
        }
    )


@pytest.mark.integration
async def test_known_and_unknown_auth_requests_only_enqueue(client, db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(auth, "deliver", REAL_DELIVER)
    client.app.state.config = config().model_copy(update={"auth_rate_limit": 100})

    def forbidden_smtp(*args, **kwargs):
        pytest.fail("SMTP ran in the authentication request")

    monkeypatch.setattr(identity_mail, "send", forbidden_smtp)
    await register(client)
    await register(client)  # Existing registration takes the cover-job path.
    results = []
    for email in ["synthetic@example.test", "absent@example.test"]:
        results.append(
            await client.post("/api/v1/auth/forgot-password", json={"email": email})
        )
    assert [r.status_code for r in results] == [200, 200]
    assert results[0].json() == results[1].json()
    rows = list(await db.scalars(select(MailDelivery)))
    assert len(rows) == 4
    assert all(row.status == "pending" for row in rows)
    assert all(
        row.payload_ciphertext and "example.test" not in row.payload_ciphertext
        for row in rows
    )
    envelopes = [
        identity_mail.MailEnvelope.model_validate_json(
            Fernet(
                client.app.state.config.notification_encryption_key.get_secret_value()
            ).decrypt(row.payload_ciphertext.encode())
        )
        for row in rows
    ]
    assert sum(bool(envelope.token) for envelope in envelopes) == 2
    assert all(
        envelope.token not in row.payload_ciphertext
        for envelope, row in zip(envelopes, rows, strict=True)
        if envelope.token
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "mode", ["success", "cover", "expired", "tampered", "swapped", "smtp_failure"]
)
async def test_outbox_terminal_and_retry_paths(db, monkeypatch, mode, caplog):
    cfg = config()
    token = "synthetic-secret-canary"
    await identity_mail.enqueue(
        db,
        cfg,
        "recipient@example.test",
        "reset",
        "" if mode == "cover" else token,
        None,
    )
    await db.flush()
    row = await db.scalar(select(MailDelivery))
    if mode == "expired":
        row.expires_at = identity_mail.utcnow() - timedelta(seconds=1)
    if mode == "tampered":
        row.payload_ciphertext = "invalid-envelope"
    if mode == "swapped":
        cipher = Fernet(cfg.notification_encryption_key.get_secret_value())
        envelope = identity_mail.MailEnvelope.model_validate_json(
            cipher.decrypt(row.payload_ciphertext.encode())
        )
        other_envelope = envelope.model_copy(update={"id": uuid4()})
        row.payload_ciphertext = cipher.encrypt(
            other_envelope.model_dump_json().encode()
        ).decode()
    calls = []

    def send(*args):
        calls.append(args)
        if mode == "smtp_failure":
            raise smtplib.SMTPException(token)

    monkeypatch.setattr(identity_mail, "send", send)
    await db.flush()
    for attempt in range(3 if mode == "smtp_failure" else 1):
        assert await identity_mail.deliver_one(db, cfg)
        if mode == "smtp_failure" and attempt < 2:
            assert row.status == "pending" and row.payload_ciphertext
            assert row.retry_at > identity_mail.utcnow()
            row.retry_at = identity_mail.utcnow() - timedelta(seconds=1)
            await db.flush()
    expected = {"success": "sent", "cover": "discarded", "expired": "expired"}.get(
        mode, "failed"
    )
    assert row.status == expected
    assert row.payload_ciphertext is None
    assert len(calls) == {"success": 1, "smtp_failure": 3}.get(mode, 0)
    assert token not in caplog.text and "recipient@example.test" not in caplog.text
    await db.flush()
    assert not await identity_mail.deliver_one(db, cfg)


@pytest.mark.integration
async def test_outbox_transaction_rollback_and_missing_key(db):
    cfg = config()
    async with db.begin_nested() as transaction:
        await identity_mail.enqueue(
            db, cfg, "recipient@example.test", "verify", "secret", None
        )
        await db.flush()
        assert await db.scalar(select(MailDelivery)) is not None
        await transaction.rollback()
    assert await db.scalar(select(MailDelivery)) is None
    cfg.notification_encryption_key = SecretStr("")
    from aegis_api.conventions import APIError

    for token in ["secret", ""]:
        with pytest.raises(APIError) as exc:
            await identity_mail.enqueue(
                db, cfg, "recipient@example.test", "verify", token, None
            )
        assert exc.value.status == 503
    assert await db.scalar(select(MailDelivery)) is None


@pytest.mark.parametrize("transport", ["identity", "notification"])
async def test_smtp_requires_certificate_verification(monkeypatch, transport):
    cfg = config()
    contexts = []

    class SMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self, *, context):
            contexts.append(context)
            raise ssl.SSLCertVerificationError("synthetic certificate failure")

        def send_message(self, message):
            pytest.fail("Mail sent after TLS verification failure")

    monkeypatch.setattr(smtplib, "SMTP", SMTP)
    if transport == "identity":
        with pytest.raises(ssl.SSLCertVerificationError):
            identity_mail.send(cfg, "recipient@example.test", "reset", "secret")
    else:
        # Exercise the same production transport without a real SMTP connection.
        monkeypatch.setattr(
            notifications, "unseal", lambda *_: ("recipient@example.test", "")
        )
        await notification_tls_failure(cfg)
    assert len(contexts) == 1
    assert contexts[0].verify_mode == ssl.CERT_REQUIRED
    assert contexts[0].check_hostname


async def notification_tls_failure(cfg):
    payload = notifications.NotificationPayload(
        event="scan.completed",
        organization_id=uuid4(),
        resource_id=uuid4(),
        link="https://aegis.test/app/scans",
    )
    with pytest.raises(ssl.SSLCertVerificationError):
        await notifications.send(cfg, SimpleNamespace(kind="email"), payload, uuid4())


def test_production_cannot_disable_smtp_tls():
    values = config().model_dump() | {
        "profile": "prod",
        "smtp_starttls": False,
        "app_origin": "https://aegis.test",
        "cookie_secure": True,
    }
    with pytest.raises(ValidationError, match="Production SMTP"):
        Settings(**values)


@pytest.mark.integration
async def test_committed_outbox_survives_session_restart_and_single_worker_claim(
    migrated_database, monkeypatch
):
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    cfg = config()
    engine = create_async_engine(migrated_database, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    calls = []
    monkeypatch.setattr(identity_mail, "send", lambda *args: calls.append(args))
    identity = None
    try:
        async with sessions() as first, sessions() as second:
            await identity_mail.enqueue(
                first, cfg, "recipient@example.test", "verify", "secret", None
            )
            await first.flush()
            row = await first.scalar(
                select(MailDelivery).where(MailDelivery.status == "pending")
            )
            identity = row.id
            assert not await identity_mail.deliver_one(
                second, cfg
            )  # Uncommitted job is invisible.
            await second.rollback()
            await first.commit()
        async with sessions() as first, sessions() as second:
            await first.scalar(
                select(MailDelivery)
                .where(MailDelivery.id == identity)
                .with_for_update()
            )
            assert not await identity_mail.deliver_one(
                second, cfg
            )  # Skip another worker's claim.
            await second.rollback()
            await first.rollback()
            assert await identity_mail.deliver_one(second, cfg)
            await second.commit()
        async with sessions() as fresh:
            row = await fresh.get(MailDelivery, identity)
            assert row.status == "sent" and row.payload_ciphertext is None
            assert len(calls) == 1
    finally:
        if identity:
            async with sessions.begin() as cleanup:
                await cleanup.execute(
                    delete(MailDelivery).where(MailDelivery.id == identity)
                )
        await engine.dispose()


@pytest.mark.integration
async def test_disabled_smtp_still_erases_expired_payloads(db):
    cfg = config()
    await identity_mail.enqueue(
        db, cfg, "recipient@example.test", "verify", "secret", None
    )
    await db.flush()
    row = await db.scalar(select(MailDelivery))
    cfg.smtp_host = ""
    assert not await identity_mail.deliver_one(db, cfg)
    assert row.payload_ciphertext
    row.expires_at = identity_mail.utcnow() - timedelta(seconds=1)
    await db.flush()
    assert await identity_mail.deliver_one(db, cfg)
    assert row.status == "expired" and row.payload_ciphertext is None


@pytest.mark.integration
@pytest.mark.parametrize("change", ["foreign_org", "deactivated"])
async def test_invitation_mail_remains_tenant_bound(
    db, two_organizations, monkeypatch, change
):
    from aegis_api.db.enums import RecordState

    first, second = two_organizations
    cfg = config()
    await identity_mail.enqueue(
        db, cfg, "recipient@example.test", "invite", "secret", None, first[0].id
    )
    await db.flush()
    row = await db.scalar(select(MailDelivery))
    if change == "foreign_org":
        cipher = Fernet(cfg.notification_encryption_key.get_secret_value())
        envelope = identity_mail.MailEnvelope.model_validate_json(
            cipher.decrypt(row.payload_ciphertext.encode())
        )
        foreign = envelope.model_copy(update={"organization_id": second[0].id})
        row.payload_ciphertext = cipher.encrypt(
            foreign.model_dump_json().encode()
        ).decode()
    else:
        first[0].status = RecordState.DEACTIVATED
    await db.flush()
    monkeypatch.setattr(
        identity_mail, "send", lambda *args: pytest.fail("Unauthorized invitation mail")
    )
    assert await identity_mail.deliver_one(db, cfg)
    assert row.status == "failed" and row.payload_ciphertext is None
