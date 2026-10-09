"""Validated tenant controls. Organization locking serializes admission and changes."""

from ipaddress import ip_network
from uuid import UUID

from pydantic import Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from aegis_api.auth import Payload
from aegis_api.conventions import APIError
from aegis_api.db.enums import ScanMode
from aegis_api.db.models import Organization
from aegis_api.settings import Settings


class Controls(Payload):
    disabled_policy_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    scans_enabled: bool = True
    active_scans_enabled: bool = True
    concurrency: int = Field(default=3, ge=1, le=100)
    target_concurrency: int = Field(default=3, ge=1, le=100)
    daily_quota: int = Field(default=100, ge=1, le=10000)
    report_retention_days: int = Field(default=30, ge=1, le=365)
    raw_retention_days: int = Field(default=30, ge=1, le=365)
    allow_networks: list[str] = Field(default_factory=list, max_length=100)
    deny_networks: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("allow_networks", "deny_networks")
    @classmethod
    def networks(cls, values: list[str]) -> list[str]:
        return sorted({str(ip_network(v, strict=True)) for v in values})


async def controls(db: AsyncSession, organization_id: UUID) -> Controls:
    org = await db.get(Organization, organization_id)
    if org is None:
        raise APIError(404, "not_found", "Organization not found.")
    return Controls.model_validate(org.administration or {})


def check_enabled(policy: Controls, config: Settings, mode: ScanMode) -> None:
    if config.emergency_stop or not policy.scans_enabled:
        raise APIError(409, "scans_disabled", "New scans are disabled.")
    if mode == ScanMode.ACTIVE and (
        not config.active_scans_enabled or not policy.active_scans_enabled
    ):
        raise APIError(409, "active_scans_disabled", "Active scans are disabled.")
