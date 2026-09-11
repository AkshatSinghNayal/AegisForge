"""Tenant-scoped policy input capture. Advisory analyses are never queried."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aegis_api.auth import now
from aegis_api.db.enums import FindingState
from aegis_api.db.models import (
    Finding,
    FindingOccurrence,
    GateActivation,
    GatePolicy,
    PolicyEvaluation,
    Scan,
    Target,
)
from aegis_api.normalization import NORMALIZER, Observation, digest
from aegis_api.policy_engine import ENGINE, Fact, Inputs, Policy, evaluate


async def active_policy(
    db: AsyncSession, organization_id: UUID, project_id: UUID
) -> GatePolicy | None:
    activation = await db.scalar(
        select(GateActivation)
        .where(
            GateActivation.organization_id == organization_id,
            GateActivation.project_id == project_id,
        )
        .order_by(GateActivation.sequence.desc())
        .limit(1)
    )
    if activation is None or activation.gate_policy_id is None:
        return None
    policy = await db.scalar(
        select(GatePolicy).where(
            GatePolicy.organization_id == organization_id,
            GatePolicy.project_id == project_id,
            GatePolicy.id == activation.gate_policy_id,
        )
    )

    return policy if isinstance(policy, GatePolicy) else None


async def capture(db: AsyncSession, scan: Scan) -> Inputs:
    target = await db.scalar(
        select(Target).where(
            Target.organization_id == scan.organization_id, Target.id == scan.target_id
        )
    )
    assert target
    normalization = scan.normalization or {}
    baseline = normalization.get("baseline_scan_id")
    baseline_ids: set[UUID] = set()
    if baseline:
        baseline_ids = set(
            (
                await db.scalars(
                    select(FindingOccurrence.finding_id).where(
                        FindingOccurrence.organization_id == scan.organization_id,
                        FindingOccurrence.target_id == scan.target_id,
                        FindingOccurrence.scan_id == UUID(baseline),
                    )
                )
            ).all()
        )
    rows = (
        await db.execute(
            select(FindingOccurrence, Finding)
            .join(
                Finding,
                (Finding.organization_id == FindingOccurrence.organization_id)
                & (Finding.id == FindingOccurrence.finding_id),
            )
            .where(
                FindingOccurrence.organization_id == scan.organization_id,
                FindingOccurrence.scan_id == scan.id,
            )
            .order_by(FindingOccurrence.id)
        )
    ).all()
    facts = []
    for occurrence, finding in rows:
        observation = Observation.model_validate(occurrence.normalized)
        status = FindingState(
            normalization.get("changes", {}).get(str(finding.id), "new")
        )
        # Current reviewer dispositions override lifecycle on re-evaluation.
        if finding.state in {FindingState.ACCEPTED_RISK, FindingState.FALSE_POSITIVE}:
            status = finding.state
        elif status in {FindingState.ACCEPTED_RISK, FindingState.FALSE_POSITIVE}:
            # A withdrawn disposition must not survive in an old normalization map.
            status = (
                FindingState.NEW
                if finding.id not in baseline_ids
                else FindingState.RECURRING
            )
        facts.append(
            Fact(
                finding_id=finding.id,
                occurrence_id=occurrence.id,
                severity=observation.severity,
                confidence=observation.confidence,
                status=status,
                cwe=observation.cwe,
                owasp=observation.owasp,
                route=observation.route,
                is_new=finding.id not in baseline_ids,
            )
        )
    return Inputs(
        scan_id=scan.id,
        state=scan.state,
        completeness=scan.completeness,
        normalized=(
            normalization.get("version") == NORMALIZER
            and set(normalization.get("observed", []))
            == {str(f.finding_id) for f in facts}
        ),
        is_demo=scan.is_demo,
        environment=scan.config_snapshot.get("environment"),
        baseline_scan_id=baseline,
        evaluated_at=now(),
        findings=facts,
    )


async def persist_evaluation(
    db: AsyncSession, scan: Scan, gate: GatePolicy
) -> PolicyEvaluation:
    policy = Policy.model_validate(gate.snapshot)
    inputs = await capture(db, scan)
    result = evaluate(policy, inputs)
    snapshot = {
        "policy_id": str(gate.id),
        "policy_version": gate.version,
        "policy": policy.model_dump(mode="json"),
        "inputs": inputs.model_dump(mode="json"),
    }
    row = PolicyEvaluation(
        organization_id=scan.organization_id,
        scan_id=scan.id,
        policy_id=scan.policy_id,
        gate_policy_id=gate.id,
        created_at=inputs.evaluated_at,
        input_digest=digest(snapshot),
        evaluation_version=ENGINE,
        outcome=result.outcome,
        reason_codes=[m.rule_id for m in result.matches],
        completeness=scan.completeness,
        enrichment_status=scan.enrichment_status,
        scan_state=scan.state,
        input_snapshot=snapshot,
        result_snapshot=result.model_dump(mode="json"),
    )
    db.add(row)
    await db.flush()
    return row


async def evaluate_bound(db: AsyncSession, scan: Scan) -> None:
    identity = (scan.config_snapshot or {}).get("gate_policy_id")
    if identity:
        gate = await db.scalar(
            select(GatePolicy).where(
                GatePolicy.organization_id == scan.organization_id,
                GatePolicy.id == UUID(identity),
            )
        )
        if gate:
            await persist_evaluation(db, scan, gate)


def record_incomplete(db: AsyncSession, scan: Scan, at: "datetime") -> None:
    identity = (scan.config_snapshot or {}).get("gate_policy_id")
    if not identity:
        return
    policy = Policy.model_validate(scan.config_snapshot["gate_policy"])
    inputs = Inputs(
        scan_id=scan.id,
        state=scan.state,
        completeness=scan.completeness,
        normalized=False,
        is_demo=scan.is_demo,
        environment=scan.config_snapshot.get("environment", ""),
        baseline_scan_id=None,
        evaluated_at=at,
        findings=[],
    )
    result = evaluate(policy, inputs)
    snapshot = {
        "policy_id": identity,
        "policy_version": scan.config_snapshot["gate_policy_version"],
        "policy": policy.model_dump(mode="json"),
        "inputs": inputs.model_dump(mode="json"),
    }
    db.add(
        PolicyEvaluation(
            organization_id=scan.organization_id,
            scan_id=scan.id,
            policy_id=scan.policy_id,
            gate_policy_id=UUID(identity),
            created_at=inputs.evaluated_at,
            input_digest=digest(snapshot),
            evaluation_version=ENGINE,
            outcome=result.outcome,
            reason_codes=["system_completeness"],
            completeness=scan.completeness,
            enrichment_status=scan.enrichment_status,
            scan_state=scan.state,
            input_snapshot=snapshot,
            result_snapshot=result.model_dump(mode="json"),
        )
    )
