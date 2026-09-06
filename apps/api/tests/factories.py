"""Synthetic records only; reserved .invalid URLs and opaque secret-store references."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from aegis_api.db.enums import Role, ScanMode, Severity
from aegis_api.db.models import (
    Finding,
    Organization,
    OrganizationMember,
    Project,
    Scan,
    ScanPolicy,
    Target,
    User,
)


async def tenant(
    session: AsyncSession,
) -> tuple[Organization, OrganizationMember, Target, ScanPolicy]:
    suffix = uuid4().hex
    user = User(
        normalized_email=f"fixture-{suffix}@example.invalid",
        display_name="Synthetic fixture",
        password_hash=None,
    )
    org = Organization(name="Synthetic test organization", slug=f"test-{suffix}")
    session.add_all([user, org])
    await session.flush()
    member = OrganizationMember(
        organization_id=org.id, user_id=user.id, role=Role.OWNER
    )
    session.add(member)
    await session.flush()
    project = Project(
        organization_id=org.id, name="Synthetic project", created_by_id=member.id
    )
    session.add(project)
    await session.flush()
    target = Target(
        organization_id=org.id,
        project_id=project.id,
        canonical_url="https://fixture.example.invalid",
        kind="web",
        scope_hosts=["fixture.example.invalid"],
        scope_paths=["/"],
    )
    policy = ScanPolicy(
        organization_id=org.id,
        name="Synthetic policy",
        version=1,
        mode=ScanMode.PASSIVE,
        fail_severity=Severity.HIGH,
        max_duration_seconds=300,
        max_requests=100,
        max_depth=2,
        require_enrichment=True,
        require_report=True,
        allow_waivers=False,
        required_coverage=["passive"],
        schema_version="test-v1",
        rules_snapshot={"schema_version": "test-v1"},
    )
    session.add_all([target, policy])
    await session.flush()
    return org, member, target, policy


def scan(
    org: Organization, member: OrganizationMember, target: Target, policy: ScanPolicy
) -> Scan:
    return Scan(
        organization_id=org.id,
        target_id=target.id,
        policy_id=policy.id,
        mode=ScanMode.PASSIVE,
        snapshot_schema_version="test-v1",
        config_snapshot={"schema_version": "test-v1"},
        authorization_snapshot={"schema_version": "test-v1", "synthetic": True},
        authorization_actor_id=member.id,
        authorized_until=datetime.now(UTC) + timedelta(hours=1),
        authorization_scope_digest="0" * 64,
        deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        is_demo=True,
    )


def finding(target: Target, *, timestamp: datetime | None = None) -> Finding:
    now = timestamp or datetime.now(UTC)
    return Finding(
        organization_id=target.organization_id,
        target_id=target.id,
        fingerprint=uuid4().hex,
        fingerprint_version="test-v1",
        title="Synthetic fixture finding",
        scanner_severity=Severity.LOW,
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
    )


async def evidence_graph(session: AsyncSession, context):
    """Factory graph covering every requested record without network side effects."""
    from aegis_api.db import models as m
    from aegis_api.db.enums import (
        Completeness,
        EnrichmentState,
        PolicyOutcome,
        ScanState,
    )

    org, member, target, policy = context
    now = datetime.now(UTC)
    expiry = now + timedelta(days=1)
    item = scan(*context)
    session.add(item)
    await session.flush()
    event = m.ScanEvent(
        organization_id=org.id,
        scan_id=item.id,
        sequence=1,
        stage=ScanState.DRAFT,
        message_code="synthetic_fixture",
    )
    artifact = m.RawScanArtifact(
        organization_id=org.id,
        scan_id=item.id,
        artifact_kind="synthetic",
        encryption_key_reference="test-vault://synthetic-key-reference",
        content_hash="0" * 64,
        scanner_version="synthetic-fixture",
        size_bytes=0,
        content_type="application/json",
        restricted_expires_at=expiry,
        redacted_expires_at=expiry,
    )
    canonical = finding(target)
    evaluation = m.PolicyEvaluation(
        organization_id=org.id,
        scan_id=item.id,
        policy_id=policy.id,
        input_digest="0" * 64,
        evaluation_version="test-v1",
        outcome=PolicyOutcome.FAIL,
        reason_codes=["synthetic_incomplete"],
        completeness=Completeness.NONE,
        enrichment_status=EnrichmentState.DISABLED,
        scan_state=ScanState.DRAFT,
    )
    session.add_all([event, artifact, canonical, evaluation])
    await session.flush()
    occurrence = m.FindingOccurrence(
        organization_id=org.id,
        target_id=target.id,
        finding_id=canonical.id,
        scan_id=item.id,
        artifact_id=artifact.id,
        scanner_rule_id="synthetic",
        observed_severity=Severity.LOW,
        occurrence_hash="0" * 64,
        redacted_evidence_pointer="synthetic:no-content",
        normalization_version="test-v1",
        coverage_ref="synthetic",
    )
    destination = m.NotificationDestination(
        organization_id=org.id,
        name="Synthetic disabled destination",
        project_id=target.project_id,
        kind="webhook",
        address_reference="test-vault://synthetic-destination",
    )
    session.add_all([occurrence, destination])
    await session.flush()
    others = [
        m.RefreshSession(
            user_id=member.user_id,
            token_hash=uuid4().hex * 2,
            family_id=uuid4(),
            expires_at=expiry,
            idle_expires_at=expiry,
        ),
        m.ProjectMember(
            organization_id=org.id, project_id=target.project_id, member_id=member.id
        ),
        m.TargetSecretReference(
            organization_id=org.id,
            target_id=target.id,
            secret_provider_ref="test-vault://synthetic-header-reference",
            header_name="X-Synthetic",
        ),
        m.AIAnalysis(
            organization_id=org.id,
            occurrence_id=occurrence.id,
            provider="disabled",
            model="none",
            schema_version="test-v1",
            prompt_version="test-v1",
            input_digest="0" * 64,
            status=EnrichmentState.DISABLED,
            output=None,
        ),
        m.Report(
            organization_id=org.id,
            scan_id=item.id,
            evaluation_id=evaluation.id,
            format="json",
            expires_at=expiry,
        ),
        m.NotificationDelivery(
            organization_id=org.id,
            destination_id=destination.id,
            event_id=event.id,
            template_version="test-v1",
        ),
        m.Integration(
            organization_id=org.id,
            provider="synthetic",
            external_installation_id=uuid4().hex,
            allowed_repositories=[],
            credential_reference="test-vault://synthetic-installation-reference",
        ),
        m.APIKey(
            organization_id=org.id,
            issued_by_id=member.id,
            project_id=target.project_id,
            permission_scopes=["scans:read"],
            prefix=uuid4().hex[:16],
            key_hash=uuid4().hex * 2,
            expires_at=expiry,
        ),
        m.AuditLog(
            organization_id=org.id,
            actor_id=member.id,
            action="synthetic_fixture",
            resource_type="target",
            resource_id=target.id,
            changed_fields=["status"],
            request_id=uuid4(),
        ),
    ]
    session.add_all(others)
    await session.flush()
    return [
        item,
        event,
        artifact,
        canonical,
        evaluation,
        occurrence,
        destination,
        *others,
    ]
