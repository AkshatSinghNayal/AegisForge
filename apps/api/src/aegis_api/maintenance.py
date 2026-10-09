"""Operator-run bounded retention batch; preserve evidence rows and audit history."""

import asyncio
import os
import stat
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from aegis_api.auth import now
from aegis_api.auth_models import AccessCredential
from aegis_api.db.models import APIKey, AuditLog, RawScanArtifact, RefreshSession, Scan
from aegis_api.scan_lifecycle import TERMINAL
from aegis_api.settings import Settings, get_settings


def remove_artifact(root: Path, organization: str, scan: str, key: str) -> None:
    # Descriptor-relative deletion prevents a concurrent directory/symlink swap
    # from redirecting cleanup. Missing storage/directories fail closed; only an
    # already absent leaf is a successful idempotent retry.
    parts = Path(key).parts
    if len(parts) != 3 or parts[:2] != (organization, scan) or ".." in parts:
        raise ValueError("Invalid artifact scope")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptors: list[int] = []
    try:
        directory = os.open(root, flags)
        descriptors.append(directory)
        for part in parts[:-1]:
            directory = os.open(part, flags, dir_fd=directory)
            descriptors.append(directory)
        try:
            metadata = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("Invalid artifact object")
            os.unlink(parts[-1], dir_fd=directory)
        except FileNotFoundError:
            pass
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


async def cleanup_credentials(db: AsyncSession) -> None:
    # Retain key attribution but remove usable hashes from service admission by
    # marking expired credentials revoked. Session chains are global identities;
    # delete only fully expired refresh families; live chains retain replay history.
    await db.execute(
        delete(AccessCredential).where(AccessCredential.expires_at <= now())
    )
    expired_families = (
        select(RefreshSession.family_id)
        .group_by(RefreshSession.family_id)
        .having(func.max(RefreshSession.expires_at) <= now())
    )
    await db.execute(
        delete(RefreshSession).where(RefreshSession.family_id.in_(expired_families))
    )
    await db.execute(
        update(APIKey)
        .where(APIKey.expires_at <= now(), APIKey.revoked_at.is_(None))
        .values(revoked_at=now())
    )


async def expire_artifact(db: AsyncSession, config: Settings) -> bool:
    from aegis_api.db.models import ArtifactPurge

    for kind in ("restricted", "redacted"):
        expiry = (
            RawScanArtifact.restricted_expires_at
            if kind == "restricted"
            else RawScanArtifact.redacted_expires_at
        )
        row = await db.scalar(
            select(RawScanArtifact)
            .join(
                Scan,
                (Scan.organization_id == RawScanArtifact.organization_id)
                & (Scan.id == RawScanArtifact.scan_id),
            )
            .where(
                Scan.state.in_(TERMINAL),
                expiry <= now(),
                ~exists().where(
                    ArtifactPurge.organization_id == RawScanArtifact.organization_id,
                    ArtifactPurge.artifact_id == RawScanArtifact.id,
                    ArtifactPurge.kind == kind,
                ),
            )
            .order_by(RawScanArtifact.created_at)
            .with_for_update(of=RawScanArtifact, skip_locked=True)
            .limit(1)
        )
        if row is None:
            continue
        key = (
            row.restricted_object_key
            if kind == "restricted"
            else row.redacted_object_key
        )
        if key:
            await asyncio.to_thread(
                remove_artifact,
                Path(config.zap_artifact_root),
                str(row.organization_id),
                str(row.scan_id),
                key,
            )
        db.add(
            ArtifactPurge(
                organization_id=row.organization_id, artifact_id=row.id, kind=kind
            )
        )
        db.add(
            AuditLog(
                organization_id=row.organization_id,
                actor_id=None,
                action="artifact." + kind + ".purged",
                resource_type="raw_scan_artifact",
                resource_id=row.id,
                changed_fields=[],
                request_id=uuid4(),
            )
        )
        return True
    return False


async def run() -> None:
    from aegis_api.db.session import database
    from aegis_api.report_jobs import expire_one

    config = get_settings()
    engine, sessions = database(config)
    try:
        async with sessions.begin() as db:
            await cleanup_credentials(db)
        for _ in range(100):
            async with sessions.begin() as db:
                await expire_one(db, config)
            async with sessions.begin() as db:
                if not await expire_artifact(db, config):
                    break
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
