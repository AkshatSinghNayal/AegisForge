"""Identity records are global; invitations and membership events are tenant scoped."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from aegis_api.db.enums import Role
from aegis_api.db.models import Base, TenantRecord, enum_type


class AccessCredential(Base):
    __tablename__ = "access_credentials"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    family_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdentityToken(Base):
    __tablename__ = "identity_tokens"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(24))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Invitation(TenantRecord):
    __tablename__ = "invitations"
    normalized_email: Mapped[str] = mapped_column(String(320))
    role: Mapped[Role] = mapped_column(enum_type(Role))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdentityAudit(Base):
    __tablename__ = "identity_audits"
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    action: Mapped[str] = mapped_column(String(100))
    request_id: Mapped[UUID] = mapped_column(Uuid)


class MailDelivery(Base):
    """No token persistence: delivery failures are observable without message bodies."""

    __tablename__ = "mail_deliveries"
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    purpose: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24))
