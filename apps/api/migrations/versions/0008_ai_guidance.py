"""Retained advisory analysis versions and append-only reviewer feedback."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_analyses",
        sa.Column("sampling", JSONB(), nullable=False, server_default="{}"),
    )
    for constraint in sa.inspect(op.get_bind()).get_unique_constraints("ai_analyses"):
        if "input_digest" in constraint["column_names"]:
            op.drop_constraint(constraint["name"], "ai_analyses", type_="unique")
    op.create_table(
        "ai_feedback",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id",
            sa.Uuid(),
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
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("useful", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.UniqueConstraint("organization_id", "id"),
        sa.ForeignKeyConstraint(
            ["organization_id", "analysis_id"],
            ["ai_analyses.organization_id", "ai_analyses.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_id"],
            ["organization_members.organization_id", "organization_members.id"],
            ondelete="RESTRICT",
        ),
    )
    for operation in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER ai_feedback_{operation.lower()} "
            f"BEFORE {operation} ON ai_feedback "
            "FOR EACH ROW EXECUTE FUNCTION aegis_immutable_record()"
        )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM ai_feedback) OR "
            "EXISTS(SELECT 1 FROM ai_analyses WHERE sampling != '{}'::jsonb)"
        )
    ):
        raise RuntimeError(
            "Cannot discard retained AI versions; restore a verified backup"
        )
    op.drop_table("ai_feedback")
    op.drop_column("ai_analyses", "sampling")
    op.create_unique_constraint(
        None,
        "ai_analyses",
        [
            "organization_id",
            "occurrence_id",
            "input_digest",
            "provider",
            "model",
            "schema_version",
            "prompt_version",
        ],
    )
