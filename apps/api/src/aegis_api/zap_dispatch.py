"""API-side envelope creation/persistence only: no scanner or secret decryption."""

from datetime import timedelta
from uuid import UUID

from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aegis_api.auth import now
from aegis_api.configuration_schemas import PolicyInput
from aegis_api.db.enums import Completeness, ScanState
from aegis_api.db.models import (
    RawScanArtifact,
    Scan,
    ScanEvent,
    Target,
    TargetSecretReference,
)
from aegis_api.scan_lifecycle import PATH, allowed, transition
from aegis_api.settings import Settings
from aegis_api.zap.contracts import ArtifactReceipt, Credential, Execution

STAGES = [
    ScanState.PREPARING_SCANNER,
    ScanState.SPIDERING,
    ScanState.PASSIVE_SCANNING,
    ScanState.ACTIVE_SCANNING,
    ScanState.COLLECTING_RESULTS,
]


async def envelope(db: AsyncSession, scan: Scan, config: Settings) -> SecretStr:
    target = await db.scalar(
        select(Target).where(
            Target.organization_id == scan.organization_id,
            Target.id == scan.target_id,
        )
    )
    if not target or not scan.job_id:
        raise ValueError("Execution unavailable")
    ids = [UUID(v) for v in scan.config_snapshot["secret_reference_ids"]]
    refs = list(
        (
            await db.scalars(
                select(TargetSecretReference).where(
                    TargetSecretReference.organization_id == scan.organization_id,
                    TargetSecretReference.target_id == scan.target_id,
                    TargetSecretReference.id.in_(ids),
                    TargetSecretReference.revoked_at.is_(None),
                )
            )
        ).all()
    )
    if len(refs) != len(ids) or any(not r.ciphertext for r in refs):
        raise ValueError("Execution unavailable")
    policy = PolicyInput.model_validate(scan.config_snapshot["policy"])
    # The more restrictive target budgets always win over the policy ceilings.
    policy.rate_limit = min(policy.rate_limit, target.configuration["rate_limit"])
    policy.max_duration_seconds = min(
        policy.max_duration_seconds, target.configuration["timeout_seconds"]
    )
    payload = Execution(
        organization_id=scan.organization_id,
        scan_id=scan.id,
        job_id=scan.job_id,
        fence=scan.fence,
        target_version=scan.config_snapshot["target_version"],
        policy_version=scan.config_snapshot["policy_version"],
        target_url=target.canonical_url,
        kind=target.kind,
        policy=policy,
        includes=target.scope_paths,
        excludes=target.configuration["exclusion_patterns"],
        methods=target.configuration["allowed_methods"],
        deadline=scan.deadline_at,
        authorized_until=scan.authorized_until,
        authorization_digest=scan.authorization_scope_digest,
        active_confirmation_digest=scan.active_confirmation_digest,
        credentials=[
            Credential(
                id=r.id,
                header_name=r.header_name,
                ciphertext=SecretStr(str(r.ciphertext)),
            )
            for r in refs
        ],
        spec=target.sanitized_spec,
    )
    data = payload.model_dump(mode="json")
    for entry, reference in zip(data["credentials"], refs, strict=True):
        entry["ciphertext"] = reference.ciphertext
    import json

    return SecretStr(
        Fernet(config.zap_dispatch_key.get_secret_value())
        .encrypt(json.dumps(data).encode())
        .decode()
    )


async def progress(db: AsyncSession, scan: Scan, stages: list[str]) -> None:
    if len(stages) > len(STAGES) or stages != [
        s.value for s in STAGES if s.value in stages
    ]:
        raise ValueError("Invalid scanner progress")
    existing = set(
        (
            await db.scalars(
                select(ScanEvent.stage).where(
                    ScanEvent.organization_id == scan.organization_id,
                    ScanEvent.scan_id == scan.id,
                    ScanEvent.message_code == "scanner_progress",
                )
            )
        ).all()
    )
    for value in stages:
        stage = ScanState(value)
        if stage not in existing:
            if not allowed(scan.state, stage, scan.mode):
                raise ValueError("Invalid scanner stage transition")
            # One real job spans discovery/collection. Progress advances the UI
            # state while retaining the same job and fence, never dispatching again.
            scan.state = stage
            scan.version += 1
            db.add(
                ScanEvent(
                    organization_id=scan.organization_id,
                    scan_id=scan.id,
                    sequence=scan.next_sequence,
                    stage=stage,
                    message_code="scanner_progress",
                    attempt=1,
                )
            )
            scan.next_sequence += 1


async def collected(db: AsyncSession, scan: Scan, receipt: ArtifactReceipt) -> None:
    if receipt.organization_id != scan.organization_id or receipt.scan_id != scan.id:
        raise ValueError("Artifact scope mismatch")
    prefix = f"{scan.organization_id}/{scan.id}/{receipt.id}"
    if (
        receipt.restricted_object_key != f"{prefix}.fernet"
        or receipt.redacted_object_key != f"{prefix}.json"
    ):
        raise ValueError("Artifact key mismatch")
    db.add(
        RawScanArtifact(
            **receipt.model_dump(exclude={"normalizer", "observations"}),
            artifact_kind="zap-raw-v1",
            content_type="application/json",
            restricted_expires_at=now() + timedelta(days=7),
            redacted_expires_at=now() + timedelta(days=90),
        )
    )
    # Complete evidence does not imply AI, policy or report availability.
    while scan.state != ScanState.COLLECTING_RESULTS:
        destination = PATH[PATH.index(scan.state) + 1]
        if scan.state == ScanState.PASSIVE_SCANNING and scan.mode.value != "active":
            destination = ScanState.COLLECTING_RESULTS
        transition(db, scan, destination, "stage_finished", now())
    if receipt.normalizer:
        transition(db, scan, ScanState.NORMALIZING, "stage_started", now())
    scan.completeness = (
        Completeness.COMPLETE if receipt.normalizer else Completeness.PARTIAL
    )
    transition(
        db,
        scan,
        ScanState.COMPLETED,
        "evidence_normalized" if receipt.normalizer else "evidence_collected",
        now(),
        collected=True,
    )

    from aegis_api.finding_service import ingest

    await db.flush()
    await ingest(db, scan, receipt)
    from aegis_api.policy_service import evaluate_bound

    await evaluate_bound(db, scan)
