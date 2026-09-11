"""Persistence records; never public response schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from aegis_api.db.enums import (
    Completeness,
    EnrichmentState,
    FindingState,
    NotificationState,
    PolicyOutcome,
    RecordState,
    ReportState,
    Role,
    ScanMode,
    ScanState,
    Severity,
)


def enum_type(kind: type[Any]) -> Enum:
    return Enum(
        kind,
        name=kind.__name__.lower(),
        values_callable=lambda e: [v.value for v in e],
        validate_strings=True,
    )


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TenantRecord(Base):
    __abstract__ = True
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )

    @declared_attr.directive
    def __table_args__(cls) -> tuple[UniqueConstraint]:
        return (UniqueConstraint("organization_id", "id"),)


def scoped(*constraints: Any) -> tuple[Any, ...]:
    return (UniqueConstraint("organization_id", "id"), *constraints)


def parent(
    column: str, table: str, *, delete: str = "RESTRICT"
) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["organization_id", column],
        [f"{table}.organization_id", f"{table}.id"],
        ondelete=delete,
    )


class User(Base):
    __tablename__ = "users"
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    normalized_email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[RecordState] = mapped_column(
        enum_type(RecordState), default=RecordState.ACTIVE
    )
    __table_args__ = (
        CheckConstraint(
            "normalized_email = lower(normalized_email)", name="normalized_email"
        ),
    )


class Organization(Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    status: Mapped[RecordState] = mapped_column(
        enum_type(RecordState), default=RecordState.ACTIVE
    )
    version: Mapped[int] = mapped_column(default=1)


class OrganizationMember(TenantRecord):
    __tablename__ = "organization_members"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    role: Mapped[Role] = mapped_column(enum_type(Role))
    status: Mapped[RecordState] = mapped_column(
        enum_type(RecordState), default=RecordState.ACTIVE
    )
    version: Mapped[int] = mapped_column(default=1)
    __table_args__ = scoped(
        UniqueConstraint("organization_id", "user_id"),
        Index("ix_members_role_status", "organization_id", "role", "status"),
    )


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    replaced_by_id: Mapped[UUID | None] = mapped_column(Uuid)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("user_id", "family_id", "id"),
        ForeignKeyConstraint(
            ["user_id", "family_id", "replaced_by_id"],
            [
                "refresh_sessions.user_id",
                "refresh_sessions.family_id",
                "refresh_sessions.id",
            ],
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("idle_expires_at <= expires_at", name="session_expiry"),
        Index("ix_sessions_user_revoked", "user_id", "revoked_at"),
    )


class Project(TenantRecord):
    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    default_branch: Mapped[str] = mapped_column(
        String(120), default="main", server_default="main"
    )
    environment: Mapped[str] = mapped_column(
        String(64), default="development", server_default="development"
    )
    owner_id: Mapped[UUID | None] = mapped_column(Uuid)
    repository_ref: Mapped[str | None] = mapped_column(String(500))
    created_by_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[RecordState] = mapped_column(
        enum_type(RecordState), default=RecordState.ACTIVE
    )
    version: Mapped[int] = mapped_column(default=1)
    __table_args__ = scoped(
        UniqueConstraint("organization_id", "name"),
        UniqueConstraint("organization_id", "slug"),
        parent("owner_id", "organization_members"),
        parent("created_by_id", "organization_members"),
        Index("ix_projects_status", "organization_id", "status"),
    )


class ProjectMember(TenantRecord):
    __tablename__ = "project_members"
    project_id: Mapped[UUID] = mapped_column(Uuid)
    member_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[RecordState] = mapped_column(
        enum_type(RecordState), default=RecordState.ACTIVE
    )
    __table_args__ = scoped(
        parent("project_id", "projects", delete="CASCADE"),
        parent("member_id", "organization_members", delete="CASCADE"),
        UniqueConstraint("organization_id", "project_id", "member_id"),
    )


class Target(TenantRecord):
    __tablename__ = "targets"
    project_id: Mapped[UUID] = mapped_column(Uuid)
    display_name: Mapped[str] = mapped_column(
        String(120), default="Target", server_default="Target"
    )
    environment: Mapped[str] = mapped_column(
        String(64), default="development", server_default="development"
    )
    configuration: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    policy_id: Mapped[UUID | None] = mapped_column(Uuid)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sanitized_spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    canonical_url: Mapped[str] = mapped_column(String(2048))
    kind: Mapped[str] = mapped_column(String(32))
    scope_hosts: Mapped[list[str]] = mapped_column(ARRAY(String(253)))
    scope_paths: Mapped[list[str]] = mapped_column(ARRAY(String(2048)))
    spec_object_ref: Mapped[str | None] = mapped_column(String(500))
    authorization_method: Mapped[str | None] = mapped_column(String(64))
    authorization_actor_id: Mapped[UUID | None] = mapped_column(Uuid)
    authorization_evidence_ref: Mapped[str | None] = mapped_column(String(500))
    authorized_scope_digest: Mapped[str | None] = mapped_column(String(64))
    authorized_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[RecordState] = mapped_column(
        enum_type(RecordState), default=RecordState.ACTIVE
    )
    version: Mapped[int] = mapped_column(default=1)
    __table_args__ = scoped(
        parent("project_id", "projects"),
        parent("authorization_actor_id", "organization_members"),
        parent("policy_id", "scan_policies"),
        UniqueConstraint("organization_id", "project_id", "canonical_url"),
        Index("ix_targets_url", "organization_id", "canonical_url"),
    )


class TargetSecretReference(TenantRecord):
    __tablename__ = "target_secret_references"
    target_id: Mapped[UUID] = mapped_column(Uuid)
    auth_type: Mapped[str] = mapped_column(
        String(32), default="api_key", server_default="api_key"
    )
    ciphertext: Mapped[str | None] = mapped_column(Text)
    secret_provider_ref: Mapped[str] = mapped_column(String(500))
    header_name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(default=1)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = scoped(
        parent("target_id", "targets"),
        UniqueConstraint("organization_id", "target_id", "header_name", "version"),
    )


class GatePolicy(TenantRecord):
    __tablename__ = "gate_policies"
    project_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    published_by: Mapped[UUID] = mapped_column(Uuid)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    __table_args__ = scoped(
        parent("project_id", "projects"),
        parent("published_by", "organization_members"),
        UniqueConstraint("organization_id", "project_id", "version"),
        UniqueConstraint("organization_id", "project_id", "id"),
        CheckConstraint("version > 0", name="gate_version"),
    )


class GateActivation(TenantRecord):
    __tablename__ = "gate_activations"
    project_id: Mapped[UUID] = mapped_column(Uuid)
    gate_policy_id: Mapped[UUID | None] = mapped_column(Uuid)
    actor_id: Mapped[UUID] = mapped_column(Uuid)
    sequence: Mapped[int] = mapped_column(Integer)
    __table_args__ = scoped(
        parent("project_id", "projects"),
        parent("actor_id", "organization_members"),
        ForeignKeyConstraint(
            ["organization_id", "project_id", "gate_policy_id"],
            [
                "gate_policies.organization_id",
                "gate_policies.project_id",
                "gate_policies.id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("organization_id", "project_id", "sequence"),
    )


class ScanPolicy(TenantRecord):
    __tablename__ = "scan_policies"
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer)
    mode: Mapped[ScanMode] = mapped_column(enum_type(ScanMode))
    fail_severity: Mapped[Severity] = mapped_column(enum_type(Severity))
    max_duration_seconds: Mapped[int] = mapped_column(Integer)
    max_requests: Mapped[int] = mapped_column(Integer)
    max_depth: Mapped[int] = mapped_column(Integer)
    require_enrichment: Mapped[bool] = mapped_column(Boolean)
    require_report: Mapped[bool] = mapped_column(Boolean)
    allow_waivers: Mapped[bool] = mapped_column(Boolean)
    required_coverage: Mapped[list[str]] = mapped_column(ARRAY(String(64)))
    schema_version: Mapped[str] = mapped_column(String(32))
    rules_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    __table_args__ = scoped(
        UniqueConstraint("organization_id", "name", "version"),
        CheckConstraint(
            "version > 0 AND max_duration_seconds > 0 AND max_requests > 0 AND "
            "max_depth >= 0",
            name="policy_limits",
        ),
    )


class Scan(TenantRecord):
    __tablename__ = "scans"
    target_id: Mapped[UUID] = mapped_column(Uuid)
    policy_id: Mapped[UUID] = mapped_column(Uuid)
    initiator_id: Mapped[UUID | None] = mapped_column(Uuid)
    trigger_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    job_id: Mapped[UUID | None] = mapped_column(Uuid)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stage_attempt: Mapped[int] = mapped_column(default=1, server_default="1")
    next_sequence: Mapped[int] = mapped_column(
        BigInteger, default=1, server_default="1"
    )
    normalization: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    mock_manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    retry_of_scan_id: Mapped[UUID | None] = mapped_column(Uuid)
    mode: Mapped[ScanMode] = mapped_column(enum_type(ScanMode))
    state: Mapped[ScanState] = mapped_column(
        enum_type(ScanState), default=ScanState.DRAFT
    )
    completeness: Mapped[Completeness] = mapped_column(
        enum_type(Completeness), default=Completeness.UNKNOWN
    )
    enrichment_status: Mapped[EnrichmentState] = mapped_column(
        enum_type(EnrichmentState), default=EnrichmentState.PENDING
    )
    report_status: Mapped[ReportState] = mapped_column(
        enum_type(ReportState), default=ReportState.PENDING
    )
    snapshot_schema_version: Mapped[str] = mapped_column(String(32))
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    authorization_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    authorization_actor_id: Mapped[UUID] = mapped_column(Uuid)
    authorized_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    authorization_scope_digest: Mapped[str] = mapped_column(String(64))
    active_confirmation_digest: Mapped[str | None] = mapped_column(String(64))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    failure_code: Mapped[str | None] = mapped_column(String(100))
    fence: Mapped[int] = mapped_column(BigInteger, default=0)
    version: Mapped[int] = mapped_column(default=1)
    is_demo: Mapped[bool] = mapped_column(default=False)
    __table_args__ = scoped(
        parent("target_id", "targets"),
        parent("policy_id", "scan_policies"),
        parent("retry_of_scan_id", "scans"),
        parent("initiator_id", "organization_members"),
        parent("authorization_actor_id", "organization_members"),
        UniqueConstraint("organization_id", "target_id", "id"),
        UniqueConstraint("organization_id", "active_confirmation_digest"),
        CheckConstraint(
            "mode != 'active' OR active_confirmation_digest IS NOT NULL",
            name="active_confirmation",
        ),
        CheckConstraint(
            "state NOT IN ('failed', 'cancelled', 'timed_out') OR completeness "
            "IN ('partial', 'none')",
            name="terminal_incomplete",
        ),
        Index("ix_scans_history", "organization_id", "target_id", "created_at", "id"),
        Index("ix_scans_state", "organization_id", "state", "created_at", "id"),
        Index("ix_scans_org_history", "organization_id", "created_at", "id"),
    )


class ScanEvent(TenantRecord):
    __tablename__ = "scan_events"
    scan_id: Mapped[UUID] = mapped_column(Uuid)
    sequence: Mapped[int] = mapped_column(BigInteger)
    stage: Mapped[ScanState] = mapped_column(enum_type(ScanState))
    message_code: Mapped[str] = mapped_column(String(100))
    attempt: Mapped[int] = mapped_column(default=1)
    __table_args__ = scoped(
        parent("scan_id", "scans"),
        UniqueConstraint("organization_id", "scan_id", "sequence"),
        CheckConstraint("sequence > 0 AND attempt > 0", name="event_sequence"),
        Index("ix_events_cursor", "organization_id", "scan_id", "created_at", "id"),
    )


class RawScanArtifact(TenantRecord):
    __tablename__ = "raw_scan_artifacts"
    scan_id: Mapped[UUID] = mapped_column(Uuid)
    artifact_kind: Mapped[str] = mapped_column(String(64))
    restricted_object_key: Mapped[str | None] = mapped_column(String(500))
    encryption_key_reference: Mapped[str] = mapped_column(String(500))
    redacted_object_key: Mapped[str | None] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(64))
    redacted_hash: Mapped[str | None] = mapped_column(String(64))
    scanner_version: Mapped[str] = mapped_column(String(64))
    redaction_version: Mapped[str | None] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str] = mapped_column(String(100))
    restricted_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    redacted_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = scoped(
        parent("scan_id", "scans"),
        UniqueConstraint("organization_id", "scan_id", "id"),
        UniqueConstraint("organization_id", "scan_id", "artifact_kind", "content_hash"),
        CheckConstraint("size_bytes >= 0", name="artifact_size"),
    )


class Finding(TenantRecord):
    __tablename__ = "findings"
    target_id: Mapped[UUID] = mapped_column(Uuid)
    comparison_family: Mapped[str] = mapped_column(
        String(64), default="legacy", server_default="legacy"
    )
    normalized: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    scanner_confidence: Mapped[str] = mapped_column(
        String(32), default="unknown", server_default="unknown"
    )
    canonical_route: Mapped[str] = mapped_column(
        String(2048), default="", server_default=""
    )
    fingerprint: Mapped[str] = mapped_column(String(64))
    fingerprint_version: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(300))
    cwe: Mapped[int | None] = mapped_column(Integer)
    scanner_severity: Mapped[Severity] = mapped_column(enum_type(Severity))
    state: Mapped[FindingState] = mapped_column(
        enum_type(FindingState), default=FindingState.NEW
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(default=1)
    __table_args__ = scoped(
        parent("target_id", "targets"),
        UniqueConstraint("organization_id", "target_id", "id"),
        UniqueConstraint(
            "organization_id",
            "target_id",
            "comparison_family",
            "fingerprint_version",
            "fingerprint",
        ),
        Index(
            "ix_findings_filters",
            "organization_id",
            "state",
            "scanner_severity",
            "created_at",
            "id",
        ),
        Index("ix_findings_cwe", "organization_id", "cwe"),
        Index("ix_findings_timeline", "organization_id", "created_at", "id"),
        Index("ix_findings_target", "organization_id", "target_id", "created_at", "id"),
        CheckConstraint("last_seen_at >= first_seen_at", name="finding_timeline"),
    )


class FindingOccurrence(TenantRecord):
    __tablename__ = "finding_occurrences"
    target_id: Mapped[UUID] = mapped_column(Uuid)
    finding_id: Mapped[UUID] = mapped_column(Uuid)
    scan_id: Mapped[UUID] = mapped_column(Uuid)
    artifact_id: Mapped[UUID] = mapped_column(Uuid)
    scanner_rule_id: Mapped[str] = mapped_column(String(64))
    observed_severity: Mapped[Severity] = mapped_column(enum_type(Severity))
    occurrence_hash: Mapped[str] = mapped_column(String(64))
    redacted_evidence_pointer: Mapped[str] = mapped_column(String(500))
    normalization_version: Mapped[str] = mapped_column(String(32))
    normalized: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    coverage_ref: Mapped[str] = mapped_column(String(100))
    __table_args__ = scoped(
        ForeignKeyConstraint(
            ["organization_id", "target_id", "finding_id"],
            ["findings.organization_id", "findings.target_id", "findings.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "target_id", "scan_id"],
            ["scans.organization_id", "scans.target_id", "scans.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "scan_id", "artifact_id"],
            [
                "raw_scan_artifacts.organization_id",
                "raw_scan_artifacts.scan_id",
                "raw_scan_artifacts.id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("organization_id", "scan_id", "occurrence_hash"),
        Index(
            "ix_occurrence_timeline",
            "organization_id",
            "finding_id",
            "created_at",
            "id",
        ),
    )


class AIAnalysis(TenantRecord):
    __tablename__ = "ai_analyses"
    occurrence_id: Mapped[UUID] = mapped_column(Uuid)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(100))
    schema_version: Mapped[str] = mapped_column(String(32))
    prompt_version: Mapped[str] = mapped_column(String(32))
    sampling: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    input_digest: Mapped[str] = mapped_column(String(64))
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[EnrichmentState] = mapped_column(enum_type(EnrichmentState))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    advisory: Mapped[bool] = mapped_column(default=True)
    __table_args__ = scoped(
        parent("occurrence_id", "finding_occurrences"),
        CheckConstraint("advisory", name="advisory_only"),
    )


class AIFeedback(TenantRecord):
    __tablename__ = "ai_feedback"
    analysis_id: Mapped[UUID] = mapped_column(Uuid)
    actor_id: Mapped[UUID] = mapped_column(Uuid)
    useful: Mapped[bool] = mapped_column()
    note: Mapped[str] = mapped_column(Text)
    __table_args__ = scoped(
        parent("analysis_id", "ai_analyses"),
        parent("actor_id", "organization_members"),
    )


class PolicyEvaluation(TenantRecord):
    gate_policy_id: Mapped[UUID | None] = mapped_column(Uuid)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    result_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    __tablename__ = "policy_evaluations"
    scan_id: Mapped[UUID] = mapped_column(Uuid)
    policy_id: Mapped[UUID] = mapped_column(Uuid)
    input_digest: Mapped[str] = mapped_column(String(64))
    evaluation_version: Mapped[str] = mapped_column(String(32))
    outcome: Mapped[PolicyOutcome] = mapped_column(enum_type(PolicyOutcome))
    reason_codes: Mapped[list[str]] = mapped_column(ARRAY(String(100)))
    completeness: Mapped[Completeness] = mapped_column(enum_type(Completeness))
    enrichment_status: Mapped[EnrichmentState] = mapped_column(
        enum_type(EnrichmentState)
    )
    scan_state: Mapped[ScanState] = mapped_column(enum_type(ScanState))
    __table_args__ = scoped(
        parent("scan_id", "scans"),
        parent("gate_policy_id", "gate_policies"),
        parent("policy_id", "scan_policies"),
        UniqueConstraint("organization_id", "scan_id", "id"),
        CheckConstraint(
            "outcome != 'pass' OR (completeness = 'complete' AND "
            "scan_state IN "
            "('evaluating_policy', 'generating_report', 'completed'))",
            name="pass_requires_complete",
        ),
        Index(
            "ix_evaluations_history", "organization_id", "scan_id", "created_at", "id"
        ),
    )


class Report(TenantRecord):
    __tablename__ = "reports"
    scan_id: Mapped[UUID] = mapped_column(Uuid)
    evaluation_id: Mapped[UUID] = mapped_column(Uuid)
    format: Mapped[str] = mapped_column(String(8))
    object_key: Mapped[str | None] = mapped_column(String(500))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    redaction_version: Mapped[str | None] = mapped_column(String(32))
    state: Mapped[ReportState] = mapped_column(
        enum_type(ReportState), default=ReportState.PENDING
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = scoped(
        parent("scan_id", "scans"),
        ForeignKeyConstraint(
            ["organization_id", "scan_id", "evaluation_id"],
            [
                "policy_evaluations.organization_id",
                "policy_evaluations.scan_id",
                "policy_evaluations.id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("format IN ('pdf', 'json')", name="report_format"),
        CheckConstraint(
            "state != 'complete' OR (object_key IS NOT NULL AND content_hash IS "
            "NOT NULL AND redaction_version IS NOT NULL)",
            name="report_complete",
        ),
        Index("ix_reports_state", "organization_id", "state", "created_at", "id"),
    )


class NotificationDestination(TenantRecord):
    __tablename__ = "notification_destinations"
    name: Mapped[str] = mapped_column(String(120))
    project_id: Mapped[UUID | None] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(32))
    address_reference: Mapped[str] = mapped_column(String(500))
    secret_reference: Mapped[str | None] = mapped_column(String(500))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int] = mapped_column(default=1)
    __table_args__ = scoped(
        parent("project_id", "projects"),
        UniqueConstraint("organization_id", "name"),
        Index("ix_destinations_enabled", "organization_id", "kind", "enabled"),
    )


class NotificationDelivery(TenantRecord):
    __tablename__ = "notification_deliveries"
    destination_id: Mapped[UUID] = mapped_column(Uuid)
    event_id: Mapped[UUID] = mapped_column(Uuid)
    template_version: Mapped[str] = mapped_column(String(32))
    state: Mapped[NotificationState] = mapped_column(
        enum_type(NotificationState), default=NotificationState.PENDING
    )
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = scoped(
        parent("destination_id", "notification_destinations"),
        parent("event_id", "scan_events"),
        UniqueConstraint(
            "organization_id", "destination_id", "event_id", "template_version"
        ),
        Index("ix_delivery_retry", "organization_id", "state", "next_attempt_at"),
    )


class Integration(TenantRecord):
    __tablename__ = "integrations"
    provider: Mapped[str] = mapped_column(String(64))
    external_installation_id: Mapped[str] = mapped_column(String(120))
    allowed_repositories: Mapped[list[str]] = mapped_column(ARRAY(String(300)))
    credential_reference: Mapped[str] = mapped_column(String(500))
    status: Mapped[RecordState] = mapped_column(
        enum_type(RecordState), default=RecordState.DEACTIVATED
    )
    version: Mapped[int] = mapped_column(default=1)
    __table_args__ = scoped(
        UniqueConstraint("organization_id", "provider", "external_installation_id"),
        UniqueConstraint("provider", "external_installation_id"),
    )


class APIKey(TenantRecord):
    __tablename__ = "api_keys"
    issued_by_id: Mapped[UUID] = mapped_column(Uuid)
    project_id: Mapped[UUID] = mapped_column(Uuid)
    permission_scopes: Mapped[list[str]] = mapped_column(ARRAY(String(64)))
    prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = scoped(
        parent("issued_by_id", "organization_members"),
        parent("project_id", "projects"),
        UniqueConstraint("organization_id", "prefix"),
    )


class AuditLog(TenantRecord):
    __tablename__ = "audit_logs"
    actor_id: Mapped[UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[UUID] = mapped_column(Uuid)
    changed_fields: Mapped[list[str]] = mapped_column(ARRAY(String(100)))
    request_id: Mapped[UUID] = mapped_column(Uuid)
    __table_args__ = scoped(
        parent("actor_id", "organization_members"),
        Index("ix_audit_timeline", "organization_id", "created_at", "id"),
        Index("ix_audit_actor", "organization_id", "actor_id", "created_at", "id"),
    )


class IdempotencyRecord(TenantRecord):
    __tablename__ = "idempotency_records"
    actor_id: Mapped[UUID] = mapped_column(Uuid)
    operation: Mapped[str] = mapped_column(String(200))
    key_hash: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[UUID] = mapped_column(Uuid)
    response_status: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = scoped(
        UniqueConstraint("organization_id", "actor_id", "operation", "key_hash"),
        Index("ix_idempotency_expiry", "organization_id", "expires_at"),
        CheckConstraint(
            "response_status IN (200, 201, 202, 204)", name="success_status"
        ),
    )


class ScanConfirmation(TenantRecord):
    __tablename__ = "scan_confirmations"
    actor_id: Mapped[UUID] = mapped_column(Uuid)
    request_digest: Mapped[str] = mapped_column(String(64))
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = scoped(parent("actor_id", "organization_members"))


class FindingReview(TenantRecord):
    __tablename__ = "finding_reviews"
    finding_id: Mapped[UUID] = mapped_column(Uuid)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid)
    scan_id: Mapped[UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(32))
    previous_state: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    __table_args__ = scoped(
        parent("finding_id", "findings"),
        parent("actor_id", "organization_members"),
        parent("scan_id", "scans"),
    )
