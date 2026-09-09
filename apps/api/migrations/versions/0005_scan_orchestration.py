"""Durable scan dispatch checkpoints and one-use active grants."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in [
        sa.Column("initiator_id", sa.Uuid()),
        sa.Column("trigger_metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("job_id", sa.Uuid()),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("stage_attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("next_sequence", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("mock_manifest", JSONB()),
    ]:
        op.add_column("scans", column)
    op.execute(
        "UPDATE scans SET next_sequence = COALESCE((SELECT max(sequence) + 1 "
        "FROM scan_events WHERE scan_id = scans.id "
        "AND organization_id = scans.organization_id), 1)"
    )
    op.create_foreign_key(
        "fk_scans_organization_id_initiator_id_organization_members",
        "scans",
        "organization_members",
        ["organization_id", "initiator_id"],
        ["organization_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "scan_confirmations",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("organization_id", "id"),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_id"],
            ["organization_members.organization_id", "organization_members.id"],
            ondelete="RESTRICT",
        ),
    )


def downgrade() -> None:
    op.drop_table("scan_confirmations")
    op.drop_constraint(
        "fk_scans_organization_id_initiator_id_organization_members", "scans"
    )
    for name in [
        "initiator_id",
        "trigger_metadata",
        "job_id",
        "dispatched_at",
        "stage_attempt",
        "next_sequence",
        "mock_manifest",
    ]:
        op.drop_column("scans", name)
