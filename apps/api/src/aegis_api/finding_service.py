"""Transactional normalization ingestion and deterministic scan comparisons."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aegis_api.auth import now
from aegis_api.db.enums import Completeness, FindingState, ScanState
from aegis_api.db.models import Finding, FindingOccurrence, FindingReview, Scan, Target
from aegis_api.normalization import FINGERPRINT, NORMALIZER, Observation, digest
from aegis_api.zap.contracts import ArtifactReceipt


def family(scan: Scan) -> str:
    # A policy ID identifies an immutable policy revision. Exact configuration
    # equality is conservative: any coverage change starts a separate baseline.
    return digest(
        [
            str(scan.policy_id),
            scan.mode.value,
            {
                k: v
                for k, v in scan.config_snapshot.items()
                if not k.startswith("gate_policy")
            },
            FINGERPRINT,
            NORMALIZER,
        ]
    )


def state_for(previous: FindingState, changed: bool) -> FindingState:
    if previous in {FindingState.ACCEPTED_RISK, FindingState.FALSE_POSITIVE}:
        return previous
    if previous == FindingState.RESOLVED:
        return FindingState.REOPENED
    return FindingState.CHANGED if changed else FindingState.RECURRING


def signature(value: dict[str, object]) -> str:
    return digest(
        {
            key: value.get(key)
            for key in ("severity", "confidence", "cwe", "wasc", "owasp")
        }
    )


def representative(observation: Observation) -> tuple[int, int, str]:
    return (
        ["informational", "low", "medium", "high", "critical"].index(
            observation.severity
        ),
        ["false_positive", "low", "medium", "high", "confirmed"].index(
            observation.confidence
        ),
        signature(observation.model_dump(mode="json")),
    )


async def ingest(db: AsyncSession, scan: Scan, receipt: ArtifactReceipt) -> None:
    if (receipt.organization_id, receipt.scan_id) != (scan.organization_id, scan.id):
        raise ValueError("Normalization scope mismatch")
    if len({o.index for o in receipt.observations}) != len(receipt.observations):
        raise ValueError("Duplicate observation index")
    if receipt.normalizer != NORMALIZER or scan.normalization is not None:
        return
    # Serialize ingestion for a target, including concurrent different scan jobs.
    await db.scalar(
        select(Target)
        .where(
            Target.organization_id == scan.organization_id, Target.id == scan.target_id
        )
        .with_for_update()
    )
    key = family(scan)
    baseline = await db.scalar(
        select(Scan)
        .where(
            Scan.organization_id == scan.organization_id,
            Scan.target_id == scan.target_id,
            Scan.id != scan.id,
            Scan.state == ScanState.COMPLETED,
            Scan.completeness == Completeness.COMPLETE,
            Scan.normalization["family"].astext == key,
            Scan.created_at < scan.created_at,
        )
        .order_by(Scan.finished_at.desc(), Scan.id.desc())
        .limit(1)
    )
    prior = list(
        (
            await db.scalars(
                select(Finding)
                .where(
                    Finding.organization_id == scan.organization_id,
                    Finding.target_id == scan.target_id,
                    Finding.comparison_family == key,
                )
                .with_for_update()
            )
        ).all()
    )
    baseline_data: dict[str, dict[str, object]] = {}
    if baseline is not None:
        rows = (
            await db.scalars(
                select(FindingOccurrence).where(
                    FindingOccurrence.organization_id == scan.organization_id,
                    FindingOccurrence.scan_id == baseline.id,
                )
            )
        ).all()
        for row in rows:
            old = baseline_data.get(str(row.finding_id))
            if old is None or representative(
                Observation.model_validate(row.normalized)
            ) > representative(Observation.model_validate(old)):
                baseline_data[str(row.finding_id)] = row.normalized
    newer_scan = await db.scalar(
        select(Scan.id)
        .where(
            Scan.organization_id == scan.organization_id,
            Scan.target_id == scan.target_id,
            Scan.created_at > scan.created_at,
            Scan.normalization["family"].astext == key,
        )
        .limit(1)
    )
    known = {f.fingerprint: f for f in prior}
    changes: dict[str, str] = {}
    seen: set[str] = set()
    at = now()
    for observation in sorted(receipt.observations, key=representative, reverse=True):
        data = observation.model_dump(mode="json")
        occurrence_id = uuid4()
        first_observation = observation.fingerprint not in seen
        item = known.get(observation.fingerprint)
        is_new = item is None
        if item is None:
            item = Finding(
                id=uuid4(),
                organization_id=scan.organization_id,
                target_id=scan.target_id,
                comparison_family=key,
                fingerprint=observation.fingerprint,
                fingerprint_version=FINGERPRINT,
                title=observation.title,
                cwe=observation.cwe,
                scanner_severity=observation.severity,
                scanner_confidence=observation.confidence,
                canonical_route=observation.route,
                normalized=data,
                state=FindingState.NEW,
                first_seen_at=at,
                last_seen_at=at,
                version=1,
            )
            db.add(item)
            known[item.fingerprint] = item
            previous = FindingState.NEW
            changes[str(item.id)] = "new"
        else:
            previous = item.state
            if first_observation:
                old = baseline_data.get(str(item.id))
                changed = old is not None and signature(old) != signature(data)
                derived = state_for(item.state, changed)
                changes[str(item.id)] = derived.value
                if newer_scan is None:
                    item.state = derived
                    item.version += 1
        if first_observation:
            db.add(
                FindingReview(
                    organization_id=scan.organization_id,
                    finding_id=item.id,
                    scan_id=scan.id,
                    action="observation",
                    previous_state=previous.value,
                    state=item.state.value,
                )
            )
        seen.add(item.fingerprint)
        if first_observation and (newer_scan is None or is_new):
            item.last_seen_at = at
            item.title, item.cwe = observation.title, observation.cwe
            item.scanner_severity, item.scanner_confidence = (
                observation.severity,
                observation.confidence,
            )
            item.normalized = {
                **data,
                "provenance": {
                    "artifact_id": str(receipt.id),
                    "occurrence_id": str(occurrence_id),
                    "scan_id": str(scan.id),
                },
            }
            if item.state != FindingState.RESOLVED:
                item.resolved_at = None
        db.add(
            FindingOccurrence(
                id=occurrence_id,
                organization_id=scan.organization_id,
                target_id=scan.target_id,
                finding_id=item.id,
                scan_id=scan.id,
                artifact_id=receipt.id,
                scanner_rule_id=observation.rule,
                observed_severity=observation.severity,
                occurrence_hash=digest([str(receipt.id), observation.index]),
                redacted_evidence_pointer=f"occurrence:{occurrence_id}#/normalized",
                normalization_version=NORMALIZER,
                coverage_ref=key,
                normalized=data,
            )
        )
    # Only the completed, complete scan path may perform negative inference.
    # No baseline => no disappearance claims. Newer ingestion prevents stale closure.
    can_resolve = (
        baseline is not None
        and newer_scan is None
        and scan.state == ScanState.COMPLETED
        and scan.completeness == Completeness.COMPLETE
    )
    if can_resolve and baseline is not None:
        baseline_ids = set((baseline.normalization or {}).get("observed", []))
        for item in prior:
            if (
                str(item.id) in baseline_ids
                and item.fingerprint not in seen
                and item.state
                not in {
                    FindingState.ACCEPTED_RISK,
                    FindingState.FALSE_POSITIVE,
                    FindingState.RESOLVED,
                }
            ):
                newer = await db.scalar(
                    select(FindingOccurrence.id)
                    .join(
                        Scan,
                        (Scan.id == FindingOccurrence.scan_id)
                        & (Scan.organization_id == FindingOccurrence.organization_id),
                    )
                    .where(
                        FindingOccurrence.organization_id == scan.organization_id,
                        FindingOccurrence.finding_id == item.id,
                        Scan.created_at > scan.created_at,
                    )
                    .limit(1)
                )
                if newer:
                    continue
                db.add(
                    FindingReview(
                        organization_id=scan.organization_id,
                        finding_id=item.id,
                        scan_id=scan.id,
                        action="verified_absent",
                        previous_state=item.state.value,
                        state="resolved",
                    )
                )
                item.state, item.resolved_at = FindingState.RESOLVED, at
                item.version += 1
                changes[str(item.id)] = "resolved"
    scan.normalization = {
        "version": NORMALIZER,
        "fingerprint_version": FINGERPRINT,
        "family": key,
        "baseline_scan_id": str(baseline.id) if baseline else None,
        "observed": [str(known[fp].id) for fp in sorted(seen)],
        "changes": changes,
    }
    await db.flush()
