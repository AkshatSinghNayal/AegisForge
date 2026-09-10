"""Versioned normalization, observations and append-only review history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE findingstate ADD VALUE IF NOT EXISTS 'reopened'")
    op.add_column("scans", sa.Column("normalization", JSONB(), nullable=True))
    for column in [
        sa.Column(
            "comparison_family", sa.String(64), nullable=False, server_default="legacy"
        ),
        sa.Column("normalized", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "scanner_confidence",
            sa.String(32),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "canonical_route", sa.String(2048), nullable=False, server_default=""
        ),
    ]:
        op.add_column("findings", column)
    # Resolve the PostgreSQL-truncated convention name without assuming its hash.
    for constraint in sa.inspect(op.get_bind()).get_unique_constraints("findings"):
        if constraint["column_names"] == [
            "organization_id",
            "target_id",
            "fingerprint_version",
            "fingerprint",
        ]:
            op.drop_constraint(constraint["name"], "findings", type_="unique")
    op.create_unique_constraint(
        None,
        "findings",
        [
            "organization_id",
            "target_id",
            "comparison_family",
            "fingerprint_version",
            "fingerprint",
        ],
    )
    op.add_column(
        "finding_occurrences",
        sa.Column("normalized", JSONB(), nullable=False, server_default="{}"),
    )
    op.create_table(
        "finding_reviews",
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
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("scan_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("previous_state", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("organization_id", "id"),
        sa.ForeignKeyConstraint(
            ["organization_id", "finding_id"],
            ["findings.organization_id", "findings.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_id"],
            ["organization_members.organization_id", "organization_members.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "scan_id"],
            ["scans.organization_id", "scans.id"],
            ondelete="RESTRICT",
        ),
    )
    for operation in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER finding_reviews_{operation.lower()} "
            f"BEFORE {operation} ON finding_reviews "
            "FOR EACH ROW EXECUTE FUNCTION aegis_immutable_record()"
        )


def downgrade() -> None:
    populated = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM finding_reviews) OR "
            "EXISTS(SELECT 1 FROM scans WHERE normalization IS NOT NULL) OR "
            "EXISTS(SELECT 1 FROM findings WHERE comparison_family != 'legacy')"
        )
    )
    if populated:
        raise RuntimeError(
            "Cannot discard normalized evidence; restore a verified backup"
        )
    op.drop_table("finding_reviews")
    op.drop_column("finding_occurrences", "normalized")
    for constraint in sa.inspect(op.get_bind()).get_unique_constraints("findings"):
        if "comparison_family" in constraint["column_names"]:
            op.drop_constraint(constraint["name"], "findings", type_="unique")
    op.create_unique_constraint(
        None,
        "findings",
        ["organization_id", "target_id", "fingerprint_version", "fingerprint"],
    )
    for column in (
        "comparison_family",
        "normalized",
        "scanner_confidence",
        "canonical_route",
    ):
        op.drop_column("findings", column)
    op.drop_column("scans", "normalization")
    # PostgreSQL enum additions are retained on non-destructive downgrades.
