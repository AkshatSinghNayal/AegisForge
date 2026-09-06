"""phase4_foundation"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def enum_column(*values: str, name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    postgresql.ENUM(
        *["unknown", "complete", "partial", "none"], name="completeness"
    ).create(op.get_bind(), checkfirst=False)
    postgresql.ENUM(
        *["pending", "complete", "degraded", "disabled", "mock"], name="enrichmentstate"
    ).create(op.get_bind(), checkfirst=False)
    postgresql.ENUM(
        *["new", "recurring", "changed", "resolved", "accepted_risk", "false_positive"],
        name="findingstate",
    ).create(op.get_bind(), checkfirst=False)
    postgresql.ENUM(
        *["pending", "sending", "sent", "failed", "dead_letter"],
        name="notificationstate",
    ).create(op.get_bind(), checkfirst=False)
    postgresql.ENUM(*["pass", "warn", "fail"], name="policyoutcome").create(
        op.get_bind(), checkfirst=False
    )
    postgresql.ENUM(*["active", "deactivated"], name="recordstate").create(
        op.get_bind(), checkfirst=False
    )
    postgresql.ENUM(
        *["pending", "generating", "complete", "failed", "expired"], name="reportstate"
    ).create(op.get_bind(), checkfirst=False)
    postgresql.ENUM(*["owner", "admin", "developer", "viewer"], name="role").create(
        op.get_bind(), checkfirst=False
    )
    postgresql.ENUM(*["baseline", "passive", "active"], name="scanmode").create(
        op.get_bind(), checkfirst=False
    )
    postgresql.ENUM(
        *[
            "draft",
            "queued",
            "validating_target",
            "preparing_scanner",
            "spidering",
            "passive_scanning",
            "active_scanning",
            "collecting_results",
            "normalizing",
            "enriching",
            "evaluating_policy",
            "generating_report",
            "completed",
            "failed",
            "cancelled",
            "timed_out",
        ],
        name="scanstate",
    ).create(op.get_bind(), checkfirst=False)
    postgresql.ENUM(
        *["informational", "low", "medium", "high", "critical"], name="severity"
    ).create(op.get_bind(), checkfirst=False)
    op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column(
            "status",
            enum_column("active", "deactivated", name="recordstate"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("slug", name=op.f("uq_organizations_slug")),
    )
    op.create_table(
        "users",
        sa.Column("normalized_email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column(
            "status",
            enum_column("active", "deactivated", name="recordstate"),
            nullable=False,
        ),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "normalized_email = lower(normalized_email)",
            name=op.f("ck_users_normalized_email"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("normalized_email", name=op.f("uq_users_normalized_email")),
    )
    op.create_table(
        "idempotency_records",
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=200), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "response_status IN (200, 201, 202, 204)",
            name=op.f("ck_idempotency_records_success_status"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_idempotency_records_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_records")),
        sa.UniqueConstraint(
            "organization_id",
            "actor_id",
            "operation",
            "key_hash",
            name=op.f(
                "uq_idempotency_records_organization_id_actor_id_operation_key_hash"
            ),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            name=op.f("uq_idempotency_records_organization_id_id"),
        ),
    )
    op.create_index(
        "ix_idempotency_expiry",
        "idempotency_records",
        ["organization_id", "expires_at"],
        unique=False,
    )
    op.create_table(
        "integrations",
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("external_installation_id", sa.String(length=120), nullable=False),
        sa.Column(
            "allowed_repositories", sa.ARRAY(sa.String(length=300)), nullable=False
        ),
        sa.Column("credential_reference", sa.String(length=500), nullable=False),
        sa.Column(
            "status",
            enum_column("active", "deactivated", name="recordstate"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_integrations_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integrations")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_integrations_organization_id_id")
        ),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "external_installation_id",
            name=op.f(
                "uq_integrations_organization_id_provider_external_installation_id"
            ),
        ),
        sa.UniqueConstraint(
            "provider",
            "external_installation_id",
            name=op.f("uq_integrations_provider_external_installation_id"),
        ),
    )
    op.create_table(
        "organization_members",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            enum_column("owner", "admin", "developer", "viewer", name="role"),
            nullable=False,
        ),
        sa.Column(
            "status",
            enum_column("active", "deactivated", name="recordstate"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_members_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_organization_members_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_members")),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            name=op.f("uq_organization_members_organization_id_id"),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            name=op.f("uq_organization_members_organization_id_user_id"),
        ),
    )
    op.create_index(
        "ix_members_role_status",
        "organization_members",
        ["organization_id", "role", "status"],
        unique=False,
    )
    op.create_table(
        "refresh_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("replaced_by_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "idle_expires_at <= expires_at",
            name=op.f("ck_refresh_sessions_session_expiry"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "family_id", "replaced_by_id"],
            [
                "refresh_sessions.user_id",
                "refresh_sessions.family_id",
                "refresh_sessions.id",
            ],
            name=op.f(
                "fk_refresh_sessions_user_id_family_id_replaced_by_id_refresh_sessions"
            ),
            ondelete="NO ACTION",
            initially="DEFERRED",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_sessions_token_hash")),
        sa.UniqueConstraint(
            "user_id",
            "family_id",
            "id",
            name=op.f("uq_refresh_sessions_user_id_family_id_id"),
        ),
    )
    op.create_index(
        op.f("ix_refresh_sessions_family_id"),
        "refresh_sessions",
        ["family_id"],
        unique=False,
    )
    op.create_index(
        "ix_sessions_user_revoked",
        "refresh_sessions",
        ["user_id", "revoked_at"],
        unique=False,
    )
    op.create_table(
        "scan_policies",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "mode",
            enum_column("baseline", "passive", "active", name="scanmode"),
            nullable=False,
        ),
        sa.Column(
            "fail_severity",
            enum_column(
                "informational", "low", "medium", "high", "critical", name="severity"
            ),
            nullable=False,
        ),
        sa.Column("max_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("max_requests", sa.Integer(), nullable=False),
        sa.Column("max_depth", sa.Integer(), nullable=False),
        sa.Column("require_enrichment", sa.Boolean(), nullable=False),
        sa.Column("require_report", sa.Boolean(), nullable=False),
        sa.Column("allow_waivers", sa.Boolean(), nullable=False),
        sa.Column("required_coverage", sa.ARRAY(sa.String(length=64)), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column(
            "rules_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version > 0 AND max_duration_seconds > 0 AND max_reques"
            "ts > 0 AND max_depth >= 0",
            name=op.f("ck_scan_policies_policy_limits"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_scan_policies_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_policies")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_scan_policies_organization_id_id")
        ),
        sa.UniqueConstraint(
            "organization_id",
            "name",
            "version",
            name=op.f("uq_scan_policies_organization_id_name_version"),
        ),
    )
    op.create_table(
        "audit_logs",
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("changed_fields", sa.ARRAY(sa.String(length=100)), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_id"],
            ["organization_members.organization_id", "organization_members.id"],
            name=op.f("fk_audit_logs_organization_id_actor_id_organization_members"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_audit_logs_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_audit_logs_organization_id_id")
        ),
    )
    op.create_index(
        "ix_audit_actor",
        "audit_logs",
        ["organization_id", "actor_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_audit_timeline",
        "audit_logs",
        ["organization_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "projects",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("repository_ref", sa.String(length=500), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            enum_column("active", "deactivated", name="recordstate"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by_id"],
            ["organization_members.organization_id", "organization_members.id"],
            name=op.f("fk_projects_organization_id_created_by_id_organization_members"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_projects_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_projects_organization_id_id")
        ),
        sa.UniqueConstraint(
            "organization_id", "name", name=op.f("uq_projects_organization_id_name")
        ),
    )
    op.create_index(
        "ix_projects_status", "projects", ["organization_id", "status"], unique=False
    )
    op.create_table(
        "api_keys",
        sa.Column("issued_by_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("permission_scopes", sa.ARRAY(sa.String(length=64)), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "issued_by_id"],
            ["organization_members.organization_id", "organization_members.id"],
            name=op.f("fk_api_keys_organization_id_issued_by_id_organization_members"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name=op.f("fk_api_keys_organization_id_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_api_keys_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_api_keys_key_hash")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_api_keys_organization_id_id")
        ),
        sa.UniqueConstraint(
            "organization_id", "prefix", name=op.f("uq_api_keys_organization_id_prefix")
        ),
    )
    op.create_table(
        "notification_destinations",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("address_reference", sa.String(length=500), nullable=False),
        sa.Column("secret_reference", sa.String(length=500), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name=op.f(
                "fk_notification_destinations_organization_id_project_id_projects"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_notification_destinations_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_destinations")),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            name=op.f("uq_notification_destinations_organization_id_id"),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "name",
            name=op.f("uq_notification_destinations_organization_id_name"),
        ),
    )
    op.create_index(
        "ix_destinations_enabled",
        "notification_destinations",
        ["organization_id", "kind", "enabled"],
        unique=False,
    )
    op.create_table(
        "project_members",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            enum_column("active", "deactivated", name="recordstate"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "member_id"],
            ["organization_members.organization_id", "organization_members.id"],
            name=op.f(
                "fk_project_members_organization_id_member_id_organization_members"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name=op.f("fk_project_members_organization_id_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_project_members_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_members")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_project_members_organization_id_id")
        ),
        sa.UniqueConstraint(
            "organization_id",
            "project_id",
            "member_id",
            name=op.f("uq_project_members_organization_id_project_id_member_id"),
        ),
    )
    op.create_table(
        "targets",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_url", sa.String(length=2048), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("scope_hosts", sa.ARRAY(sa.String(length=253)), nullable=False),
        sa.Column("scope_paths", sa.ARRAY(sa.String(length=2048)), nullable=False),
        sa.Column("spec_object_ref", sa.String(length=500), nullable=True),
        sa.Column("authorization_method", sa.String(length=64), nullable=True),
        sa.Column("authorization_actor_id", sa.Uuid(), nullable=True),
        sa.Column("authorization_evidence_ref", sa.String(length=500), nullable=True),
        sa.Column("authorized_scope_digest", sa.String(length=64), nullable=True),
        sa.Column("authorized_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            enum_column("active", "deactivated", name="recordstate"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "authorization_actor_id"],
            ["organization_members.organization_id", "organization_members.id"],
            name=op.f(
                "fk_targets_organization_id_authorization_actor_id_organization_members"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name=op.f("fk_targets_organization_id_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_targets_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_targets")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_targets_organization_id_id")
        ),
        sa.UniqueConstraint(
            "organization_id",
            "project_id",
            "canonical_url",
            name=op.f("uq_targets_organization_id_project_id_canonical_url"),
        ),
    )
    op.create_index(
        "ix_targets_url", "targets", ["organization_id", "canonical_url"], unique=False
    )
    op.create_table(
        "findings",
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("fingerprint_version", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("cwe", sa.Integer(), nullable=True),
        sa.Column(
            "scanner_severity",
            enum_column(
                "informational", "low", "medium", "high", "critical", name="severity"
            ),
            nullable=False,
        ),
        sa.Column(
            "state",
            enum_column(
                "new",
                "recurring",
                "changed",
                "resolved",
                "accepted_risk",
                "false_positive",
                name="findingstate",
            ),
            nullable=False,
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "last_seen_at >= first_seen_at", name=op.f("ck_findings_finding_timeline")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "target_id"],
            ["targets.organization_id", "targets.id"],
            name=op.f("fk_findings_organization_id_target_id_targets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_findings_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_findings")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_findings_organization_id_id")
        ),
        sa.UniqueConstraint(
            "organization_id",
            "target_id",
            "fingerprint_version",
            "fingerprint",
            name=op.f(
                "uq_findings_organization_id_target_id_fingerprint_version_fingerprint"
            ),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "target_id",
            "id",
            name=op.f("uq_findings_organization_id_target_id_id"),
        ),
    )
    op.create_index(
        "ix_findings_cwe", "findings", ["organization_id", "cwe"], unique=False
    )
    op.create_index(
        "ix_findings_filters",
        "findings",
        ["organization_id", "state", "scanner_severity", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "scans",
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("retry_of_scan_id", sa.Uuid(), nullable=True),
        sa.Column(
            "mode",
            enum_column("baseline", "passive", "active", name="scanmode"),
            nullable=False,
        ),
        sa.Column(
            "state",
            enum_column(
                "draft",
                "queued",
                "validating_target",
                "preparing_scanner",
                "spidering",
                "passive_scanning",
                "active_scanning",
                "collecting_results",
                "normalizing",
                "enriching",
                "evaluating_policy",
                "generating_report",
                "completed",
                "failed",
                "cancelled",
                "timed_out",
                name="scanstate",
            ),
            nullable=False,
        ),
        sa.Column(
            "completeness",
            enum_column("unknown", "complete", "partial", "none", name="completeness"),
            nullable=False,
        ),
        sa.Column(
            "enrichment_status",
            enum_column(
                "pending",
                "complete",
                "degraded",
                "disabled",
                "mock",
                name="enrichmentstate",
            ),
            nullable=False,
        ),
        sa.Column(
            "report_status",
            enum_column(
                "pending",
                "generating",
                "complete",
                "failed",
                "expired",
                name="reportstate",
            ),
            nullable=False,
        ),
        sa.Column("snapshot_schema_version", sa.String(length=32), nullable=False),
        sa.Column(
            "config_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "authorization_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("authorization_actor_id", sa.Uuid(), nullable=False),
        sa.Column("authorized_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorization_scope_digest", sa.String(length=64), nullable=False),
        sa.Column("active_confirmation_digest", sa.String(length=64), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancellation_requested_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("fence", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "mode != 'active' OR active_confirmation_digest IS NOT NULL",
            name=op.f("ck_scans_active_confirmation"),
        ),
        sa.CheckConstraint(
            "state NOT IN ('failed', 'cancelled', 'timed_out') OR co"
            "mpleteness IN ('partial', 'none')",
            name=op.f("ck_scans_terminal_incomplete"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "authorization_actor_id"],
            ["organization_members.organization_id", "organization_members.id"],
            name=op.f(
                "fk_scans_organization_id_authorization_actor_id_organization_members"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "policy_id"],
            ["scan_policies.organization_id", "scan_policies.id"],
            name=op.f("fk_scans_organization_id_policy_id_scan_policies"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "retry_of_scan_id"],
            ["scans.organization_id", "scans.id"],
            name=op.f("fk_scans_organization_id_retry_of_scan_id_scans"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "target_id"],
            ["targets.organization_id", "targets.id"],
            name=op.f("fk_scans_organization_id_target_id_targets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_scans_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scans")),
        sa.UniqueConstraint(
            "organization_id",
            "active_confirmation_digest",
            name=op.f("uq_scans_organization_id_active_confirmation_digest"),
        ),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_scans_organization_id_id")
        ),
        sa.UniqueConstraint(
            "organization_id",
            "target_id",
            "id",
            name=op.f("uq_scans_organization_id_target_id_id"),
        ),
    )
    op.create_index(
        "ix_scans_history",
        "scans",
        ["organization_id", "target_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_scans_state",
        "scans",
        ["organization_id", "state", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "target_secret_references",
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("secret_provider_ref", sa.String(length=500), nullable=False),
        sa.Column("header_name", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "target_id"],
            ["targets.organization_id", "targets.id"],
            name=op.f("fk_target_secret_references_organization_id_target_id_targets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_target_secret_references_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_target_secret_references")),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            name=op.f("uq_target_secret_references_organization_id_id"),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "target_id",
            "header_name",
            "version",
            name=op.f(
                "uq_target_secret_references_organization_id_target_id_h"
                "eader_name_version"
            ),
        ),
    )
    op.create_table(
        "policy_evaluations",
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("input_digest", sa.String(length=64), nullable=False),
        sa.Column("evaluation_version", sa.String(length=32), nullable=False),
        sa.Column(
            "outcome",
            enum_column("pass", "warn", "fail", name="policyoutcome"),
            nullable=False,
        ),
        sa.Column("reason_codes", sa.ARRAY(sa.String(length=100)), nullable=False),
        sa.Column(
            "completeness",
            enum_column("unknown", "complete", "partial", "none", name="completeness"),
            nullable=False,
        ),
        sa.Column(
            "enrichment_status",
            enum_column(
                "pending",
                "complete",
                "degraded",
                "disabled",
                "mock",
                name="enrichmentstate",
            ),
            nullable=False,
        ),
        sa.Column(
            "scan_state",
            enum_column(
                "draft",
                "queued",
                "validating_target",
                "preparing_scanner",
                "spidering",
                "passive_scanning",
                "active_scanning",
                "collecting_results",
                "normalizing",
                "enriching",
                "evaluating_policy",
                "generating_report",
                "completed",
                "failed",
                "cancelled",
                "timed_out",
                name="scanstate",
            ),
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome != 'pass' OR (completeness = 'complete' AND enr"
            "ichment_status = 'complete' AND scan_state IN ('evaluat"
            "ing_policy', 'generating_report', 'completed'))",
            name=op.f("ck_policy_evaluations_pass_requires_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "policy_id"],
            ["scan_policies.organization_id", "scan_policies.id"],
            name=op.f("fk_policy_evaluations_organization_id_policy_id_scan_policies"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "scan_id"],
            ["scans.organization_id", "scans.id"],
            name=op.f("fk_policy_evaluations_organization_id_scan_id_scans"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_policy_evaluations_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policy_evaluations")),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            name=op.f("uq_policy_evaluations_organization_id_id"),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "scan_id",
            "id",
            name=op.f("uq_policy_evaluations_organization_id_scan_id_id"),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "scan_id",
            "input_digest",
            "policy_id",
            "evaluation_version",
            name=op.f(
                "uq_policy_evaluations_organization_id_scan_id_input_dig"
                "est_policy_id_evaluation_version"
            ),
        ),
    )
    op.create_index(
        "ix_evaluations_history",
        "policy_evaluations",
        ["organization_id", "scan_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "raw_scan_artifacts",
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_kind", sa.String(length=64), nullable=False),
        sa.Column("restricted_object_key", sa.String(length=500), nullable=True),
        sa.Column("encryption_key_reference", sa.String(length=500), nullable=False),
        sa.Column("redacted_object_key", sa.String(length=500), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("redacted_hash", sa.String(length=64), nullable=True),
        sa.Column("scanner_version", sa.String(length=64), nullable=False),
        sa.Column("redaction_version", sa.String(length=32), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("restricted_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redacted_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "size_bytes >= 0", name=op.f("ck_raw_scan_artifacts_artifact_size")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "scan_id"],
            ["scans.organization_id", "scans.id"],
            name=op.f("fk_raw_scan_artifacts_organization_id_scan_id_scans"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_raw_scan_artifacts_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_scan_artifacts")),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            name=op.f("uq_raw_scan_artifacts_organization_id_id"),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "scan_id",
            "artifact_kind",
            "content_hash",
            name=op.f(
                "uq_raw_scan_artifacts_organization_id_scan_id_artifact_"
                "kind_content_hash"
            ),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "scan_id",
            "id",
            name=op.f("uq_raw_scan_artifacts_organization_id_scan_id_id"),
        ),
    )
    op.create_table(
        "scan_events",
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "stage",
            enum_column(
                "draft",
                "queued",
                "validating_target",
                "preparing_scanner",
                "spidering",
                "passive_scanning",
                "active_scanning",
                "collecting_results",
                "normalizing",
                "enriching",
                "evaluating_policy",
                "generating_report",
                "completed",
                "failed",
                "cancelled",
                "timed_out",
                name="scanstate",
            ),
            nullable=False,
        ),
        sa.Column("message_code", sa.String(length=100), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sequence > 0 AND attempt > 0", name=op.f("ck_scan_events_event_sequence")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "scan_id"],
            ["scans.organization_id", "scans.id"],
            name=op.f("fk_scan_events_organization_id_scan_id_scans"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_scan_events_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_events")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_scan_events_organization_id_id")
        ),
        sa.UniqueConstraint(
            "organization_id",
            "scan_id",
            "sequence",
            name=op.f("uq_scan_events_organization_id_scan_id_sequence"),
        ),
    )
    op.create_index(
        "ix_events_cursor",
        "scan_events",
        ["organization_id", "scan_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "finding_occurrences",
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("scanner_rule_id", sa.String(length=64), nullable=False),
        sa.Column(
            "observed_severity",
            enum_column(
                "informational", "low", "medium", "high", "critical", name="severity"
            ),
            nullable=False,
        ),
        sa.Column("occurrence_hash", sa.String(length=64), nullable=False),
        sa.Column("redacted_evidence_pointer", sa.String(length=500), nullable=False),
        sa.Column("normalization_version", sa.String(length=32), nullable=False),
        sa.Column("coverage_ref", sa.String(length=100), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "scan_id", "artifact_id"],
            [
                "raw_scan_artifacts.organization_id",
                "raw_scan_artifacts.scan_id",
                "raw_scan_artifacts.id",
            ],
            name=op.f(
                "fk_finding_occurrences_organization_id_scan_id_artifact"
                "_id_raw_scan_artifacts"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "target_id", "finding_id"],
            ["findings.organization_id", "findings.target_id", "findings.id"],
            name=op.f(
                "fk_finding_occurrences_organization_id_target_id_finding_id_findings"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "target_id", "scan_id"],
            ["scans.organization_id", "scans.target_id", "scans.id"],
            name=op.f("fk_finding_occurrences_organization_id_target_id_scan_id_scans"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_finding_occurrences_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_finding_occurrences")),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            name=op.f("uq_finding_occurrences_organization_id_id"),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "scan_id",
            "occurrence_hash",
            name=op.f("uq_finding_occurrences_organization_id_scan_id_occurrence_hash"),
        ),
    )
    op.create_index(
        "ix_occurrence_timeline",
        "finding_occurrences",
        ["organization_id", "finding_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "notification_deliveries",
        sa.Column("destination_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("template_version", sa.String(length=32), nullable=False),
        sa.Column(
            "state",
            enum_column(
                "pending",
                "sending",
                "sent",
                "failed",
                "dead_letter",
                name="notificationstate",
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "destination_id"],
            [
                "notification_destinations.organization_id",
                "notification_destinations.id",
            ],
            name=op.f(
                "fk_notification_deliveries_organization_id_destination_"
                "id_notification_destinations"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "event_id"],
            ["scan_events.organization_id", "scan_events.id"],
            name=op.f(
                "fk_notification_deliveries_organization_id_event_id_scan_events"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_notification_deliveries_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_deliveries")),
        sa.UniqueConstraint(
            "organization_id",
            "destination_id",
            "event_id",
            "template_version",
            name=op.f(
                "uq_notification_deliveries_organization_id_destination_"
                "id_event_id_template_version"
            ),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            name=op.f("uq_notification_deliveries_organization_id_id"),
        ),
    )
    op.create_index(
        "ix_delivery_retry",
        "notification_deliveries",
        ["organization_id", "state", "next_attempt_at"],
        unique=False,
    )
    op.create_table(
        "reports",
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_id", sa.Uuid(), nullable=False),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column("object_key", sa.String(length=500), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("redaction_version", sa.String(length=32), nullable=True),
        sa.Column(
            "state",
            enum_column(
                "pending",
                "generating",
                "complete",
                "failed",
                "expired",
                name="reportstate",
            ),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "format IN ('pdf', 'json')", name=op.f("ck_reports_report_format")
        ),
        sa.CheckConstraint(
            "state != 'complete' OR (object_key IS NOT NULL AND cont"
            "ent_hash IS NOT NULL AND redaction_version IS NOT NULL)",
            name=op.f("ck_reports_report_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "scan_id", "evaluation_id"],
            [
                "policy_evaluations.organization_id",
                "policy_evaluations.scan_id",
                "policy_evaluations.id",
            ],
            name=op.f(
                "fk_reports_organization_id_scan_id_evaluation_id_policy_evaluations"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "scan_id"],
            ["scans.organization_id", "scans.id"],
            name=op.f("fk_reports_organization_id_scan_id_scans"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_reports_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_reports_organization_id_id")
        ),
    )
    op.create_index(
        "ix_reports_state",
        "reports",
        ["organization_id", "state", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "ai_analyses",
        sa.Column("occurrence_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("input_digest", sa.String(length=64), nullable=False),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            enum_column(
                "pending",
                "complete",
                "degraded",
                "disabled",
                "mock",
                name="enrichmentstate",
            ),
            nullable=False,
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("advisory", sa.Boolean(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("advisory", name=op.f("ck_ai_analyses_advisory_only")),
        sa.ForeignKeyConstraint(
            ["organization_id", "occurrence_id"],
            ["finding_occurrences.organization_id", "finding_occurrences.id"],
            name=op.f(
                "fk_ai_analyses_organization_id_occurrence_id_finding_occurrences"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_ai_analyses_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_analyses")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_ai_analyses_organization_id_id")
        ),
        sa.UniqueConstraint(
            "organization_id",
            "occurrence_id",
            "input_digest",
            "provider",
            "model",
            "schema_version",
            "prompt_version",
            name=op.f(
                "uq_ai_analyses_organization_id_occurrence_id_input_dige"
                "st_provider_model_schema_version_prompt_version"
            ),
        ),
    )
    op.create_index(
        "ix_scans_org_history", "scans", ["organization_id", "created_at", "id"]
    )
    op.create_index(
        "ix_findings_timeline", "findings", ["organization_id", "created_at", "id"]
    )
    op.create_index(
        "ix_findings_target",
        "findings",
        ["organization_id", "target_id", "created_at", "id"],
    )
    op.execute("""CREATE FUNCTION aegis_touch_updated_at() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF NEW.id != OLD.id OR (to_jsonb(NEW)->'organization_id')
        IS DISTINCT FROM (to_jsonb(OLD)->'organization_id') THEN
        RAISE EXCEPTION 'immutable identity' USING ERRCODE = '23514';
      END IF;
      NEW.created_at := OLD.created_at;
      NEW.updated_at := clock_timestamp();
      RETURN NEW;
    END $$""")
    op.execute("""CREATE FUNCTION aegis_immutable_record() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      RAISE EXCEPTION 'immutable record' USING ERRCODE = '23514';
    END $$""")
    # Frozen identifiers: do not import live application metadata in migrations.
    immutable_tables = (
        "scan_policies",
        "scan_events",
        "finding_occurrences",
        "ai_analyses",
        "policy_evaluations",
        "audit_logs",
    )
    for table in (
        "organizations",
        "users",
        "organization_members",
        "refresh_sessions",
        "projects",
        "project_members",
        "targets",
        "target_secret_references",
        "scan_policies",
        "scans",
        "scan_events",
        "raw_scan_artifacts",
        "findings",
        "finding_occurrences",
        "ai_analyses",
        "policy_evaluations",
        "reports",
        "notification_destinations",
        "notification_deliveries",
        "integrations",
        "api_keys",
        "audit_logs",
        "idempotency_records",
    ):
        function = (
            "aegis_immutable_record"
            if table in immutable_tables
            else "aegis_touch_updated_at"
        )
        op.execute(
            f"CREATE TRIGGER {table}_update BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        )


def downgrade() -> None:
    op.drop_index("ix_findings_target", table_name="findings")
    op.drop_index("ix_findings_timeline", table_name="findings")
    op.drop_index("ix_scans_org_history", table_name="scans")
    # Reverse dependency order; retained history blocks ordinary parent deletion.
    op.drop_table("ai_analyses")
    op.drop_index("ix_reports_state", table_name="reports")
    op.drop_table("reports")
    op.drop_index("ix_delivery_retry", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
    op.drop_index("ix_occurrence_timeline", table_name="finding_occurrences")
    op.drop_table("finding_occurrences")
    op.drop_index("ix_events_cursor", table_name="scan_events")
    op.drop_table("scan_events")
    op.drop_table("raw_scan_artifacts")
    op.drop_index("ix_evaluations_history", table_name="policy_evaluations")
    op.drop_table("policy_evaluations")
    op.drop_table("target_secret_references")
    op.drop_index("ix_scans_state", table_name="scans")
    op.drop_index("ix_scans_history", table_name="scans")
    op.drop_table("scans")
    op.drop_index("ix_findings_filters", table_name="findings")
    op.drop_index("ix_findings_cwe", table_name="findings")
    op.drop_table("findings")
    op.drop_index("ix_targets_url", table_name="targets")
    op.drop_table("targets")
    op.drop_table("project_members")
    op.drop_index("ix_destinations_enabled", table_name="notification_destinations")
    op.drop_table("notification_destinations")
    op.drop_table("api_keys")
    op.drop_index("ix_projects_status", table_name="projects")
    op.drop_table("projects")
    op.drop_index("ix_audit_timeline", table_name="audit_logs")
    op.drop_index("ix_audit_actor", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("scan_policies")
    op.drop_index("ix_sessions_user_revoked", table_name="refresh_sessions")
    op.drop_index(op.f("ix_refresh_sessions_family_id"), table_name="refresh_sessions")
    op.drop_table("refresh_sessions")
    op.drop_index("ix_members_role_status", table_name="organization_members")
    op.drop_table("organization_members")
    op.drop_table("integrations")
    op.drop_index("ix_idempotency_expiry", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_table("users")
    op.drop_table("organizations")
    op.execute("DROP FUNCTION aegis_touch_updated_at()")
    op.execute("DROP FUNCTION aegis_immutable_record()")
    postgresql.ENUM(name="completeness").drop(op.get_bind(), checkfirst=False)
    postgresql.ENUM(name="enrichmentstate").drop(op.get_bind(), checkfirst=False)
    postgresql.ENUM(name="findingstate").drop(op.get_bind(), checkfirst=False)
    postgresql.ENUM(name="notificationstate").drop(op.get_bind(), checkfirst=False)
    postgresql.ENUM(name="policyoutcome").drop(op.get_bind(), checkfirst=False)
    postgresql.ENUM(name="recordstate").drop(op.get_bind(), checkfirst=False)
    postgresql.ENUM(name="reportstate").drop(op.get_bind(), checkfirst=False)
    postgresql.ENUM(name="role").drop(op.get_bind(), checkfirst=False)
    postgresql.ENUM(name="scanmode").drop(op.get_bind(), checkfirst=False)
    postgresql.ENUM(name="scanstate").drop(op.get_bind(), checkfirst=False)
    postgresql.ENUM(name="severity").drop(op.get_bind(), checkfirst=False)
