"""Organization safety controls; audit records remain immutable."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column("result", sa.String(16), nullable=False, server_default="success"),
    )
    op.add_column("audit_logs", sa.Column("source_ip", sa.String(45), nullable=True))
    op.add_column(
        "organizations",
        sa.Column("administration", JSONB(), nullable=False, server_default="{}"),
    )

    op.create_table(
        "artifact_purges",
        sa.Column(
            "id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "organization_id",
            UUID(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("artifact_id", UUID(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
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
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "artifact_id", "kind"),
        sa.ForeignKeyConstraint(
            ["organization_id", "artifact_id"],
            ["raw_scan_artifacts.organization_id", "raw_scan_artifacts.id"],
            ondelete="RESTRICT",
        ),
    )
    op.execute(
        "CREATE TRIGGER audit_logs_truncate BEFORE TRUNCATE ON audit_logs "
        "FOR EACH STATEMENT EXECUTE FUNCTION aegis_immutable_record()"
    )
    op.execute(
        "CREATE TRIGGER artifact_purges_truncate BEFORE TRUNCATE ON artifact_purges "
        "FOR EACH STATEMENT EXECUTE FUNCTION aegis_immutable_record()"
    )
    for operation in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER artifact_purges_{operation.lower()} "
            f"BEFORE {operation} ON artifact_purges "
            "FOR EACH ROW EXECUTE FUNCTION aegis_immutable_record()"
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_logs_truncate ON audit_logs")
    op.drop_column("audit_logs", "source_ip")
    op.drop_column("audit_logs", "result")
    op.drop_table("artifact_purges")
    op.drop_column("organizations", "administration")
