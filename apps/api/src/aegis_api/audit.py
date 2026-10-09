"""Value-free audit summaries; never persist submitted changes or request headers."""

from contextvars import ContextVar
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapper

from aegis_api.db.models import AuditLog
from aegis_api.logging import correlation_id

source_ip: ContextVar[str | None] = ContextVar("audit_source_ip", default=None)

FIELDS = frozenset(
    {
        "disabled_policy_ids",
        "role",
        "status",
        "state",
        "version",
        "revoked_at",
        "policy",
        "output",
        "feedback",
        "note",
        "scans_enabled",
        "active_scans_enabled",
        "concurrency",
        "target_concurrency",
        "daily_quota",
        "report_retention_days",
        "raw_retention_days",
        "allow_networks",
        "deny_networks",
    }
)


def safe_fields(fields: list[str]) -> list[str]:
    return sorted(set(fields) & FIELDS)


@event.listens_for(AuditLog, "before_insert")
def sanitize(mapper: Mapper[AuditLog], connection: Connection, row: AuditLog) -> None:
    row.source_ip = source_ip.get()
    row.changed_fields = safe_fields(row.changed_fields or [])
    try:
        row.request_id = UUID(correlation_id.get())
    except ValueError:
        pass  # Background events keep their generated correlation identifier.
