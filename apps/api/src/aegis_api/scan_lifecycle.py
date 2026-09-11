"""Closed state graph and append-only, code-only events. Call under a scan row lock."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from aegis_api.conventions import APIError
from aegis_api.db.enums import Completeness, ScanMode, ScanState
from aegis_api.db.models import Scan, ScanEvent

TERMINAL = {
    ScanState.COMPLETED,
    ScanState.FAILED,
    ScanState.CANCELLED,
    ScanState.TIMED_OUT,
}
PATH = list(ScanState)[:13]
EDGES = {a: {b} for a, b in zip(PATH, PATH[1:], strict=False)}
EDGES[ScanState.PASSIVE_SCANNING].add(ScanState.COLLECTING_RESULTS)
CODES = frozenset(
    {
        "queued",
        "stage_started",
        "stage_finished",
        "safe_retry",
        "cancelled",
        "deadline_expired",
        "worker_lost",
        "scanner_unavailable",
        "authorization_expired",
        "configuration_changed",
        "secret_revoked",
        "provider_failed",
        "invalid_fixture",
        "demo_completed",
        "dispatch_retry",
        "scanner_progress",
        "evidence_collected",
        "evidence_normalized",
    }
)
SAFE_RETRY = {
    ScanState.VALIDATING_TARGET,
    ScanState.PREPARING_SCANNER,
    ScanState.COLLECTING_RESULTS,
    ScanState.NORMALIZING,
    ScanState.ENRICHING,
    ScanState.EVALUATING_POLICY,
    ScanState.GENERATING_REPORT,
}


def allowed(
    source: ScanState,
    destination: ScanState,
    mode: ScanMode,
    *,
    collected: bool = False,
) -> bool:
    if (
        collected
        and source in {ScanState.COLLECTING_RESULTS, ScanState.NORMALIZING}
        and destination == ScanState.COMPLETED
    ):
        return True
    if source in TERMINAL:
        return False
    if destination in TERMINAL - {ScanState.COMPLETED}:
        return True
    if source == ScanState.PASSIVE_SCANNING:
        return destination == (
            ScanState.ACTIVE_SCANNING
            if mode == ScanMode.ACTIVE
            else ScanState.COLLECTING_RESULTS
        )
    return destination in EDGES.get(source, set())


def event(db: AsyncSession, scan: Scan, code: str) -> None:
    if code not in CODES:
        raise ValueError("Unknown safe event code")
    db.add(
        ScanEvent(
            organization_id=scan.organization_id,
            scan_id=scan.id,
            sequence=scan.next_sequence,
            stage=scan.state,
            message_code=code,
            attempt=scan.stage_attempt,
        )
    )
    scan.next_sequence += 1


def transition(
    db: AsyncSession,
    scan: Scan,
    destination: ScanState,
    code: str,
    at: datetime,
    *,
    fence: int | None = None,
    collected: bool = False,
) -> None:
    if code not in CODES:
        raise ValueError("Unknown safe event code")
    if fence is not None and scan.fence != fence:
        raise APIError(409, "stale_worker", "Worker lease is no longer current.")
    if not allowed(
        scan.state, destination, scan.mode, collected=collected and not scan.is_demo
    ):
        raise APIError(
            409, "illegal_transition", "Scan state cannot make this transition."
        )
    if destination not in TERMINAL - {ScanState.COMPLETED} and scan.deadline_at <= at:
        destination, code = ScanState.TIMED_OUT, "deadline_expired"
    scan.state = destination
    scan.version += 1
    scan.fence += 1
    scan.job_id, scan.dispatched_at = None, None
    if destination == ScanState.VALIDATING_TARGET:
        scan.started_at = at
    if destination in TERMINAL:
        scan.finished_at = at
        if destination != ScanState.COMPLETED:
            scan.completeness = Completeness.NONE
            scan.failure_code = code
    event(db, scan, code)
    scan.stage_attempt = 1
    if destination in TERMINAL and (destination != ScanState.COMPLETED or scan.is_demo):
        from aegis_api.policy_service import record_incomplete

        record_incomplete(db, scan, at)
