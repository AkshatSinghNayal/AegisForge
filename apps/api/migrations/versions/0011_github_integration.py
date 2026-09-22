"""Tenant-scoped GitHub mappings and durable replay receipts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def base() -> list[sa.Column]:
    return [
        sa.Column(
            "id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "organization_id",
            UUID(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def fk(column: str, table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", column],
        [f"{table}.organization_id", f"{table}.id"],
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "github_mappings",
        *base(),
        *[
            sa.Column(c, UUID(), nullable=False)
            for c in [
                "integration_id",
                "creator_id",
                "project_id",
                "target_id",
                "policy_id",
                "gate_policy_id",
            ]
        ],
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("repository", sa.String(200), nullable=False),
        sa.Column("branch", sa.String(120), nullable=False),
        sa.Column("environment", sa.String(64), nullable=False),
        sa.Column("events", sa.ARRAY(sa.String(32)), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "integration_id"),
        fk("integration_id", "integrations"),
        fk("creator_id", "organization_members"),
        fk("project_id", "projects"),
        fk("target_id", "targets"),
        fk("policy_id", "scan_policies"),
        fk("gate_policy_id", "gate_policies"),
    )
    op.create_table(
        "github_deliveries",
        *base(),
        sa.Column("mapping_id", UUID(), nullable=False),
        sa.Column("delivery_id", UUID(), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("scan_id", UUID()),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "mapping_id", "delivery_id"),
        sa.UniqueConstraint("organization_id", "mapping_id", "payload_digest", "event"),
        fk("mapping_id", "github_mappings"),
        fk("scan_id", "scans"),
    )


def downgrade() -> None:
    op.drop_table("github_deliveries")
    op.drop_table("github_mappings")
