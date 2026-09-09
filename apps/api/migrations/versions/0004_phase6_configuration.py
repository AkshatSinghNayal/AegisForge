"""Project configuration, target consent and encrypted local secret references."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, columns in {
        "projects": [
            sa.Column("slug", sa.String(120)),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "default_branch", sa.String(120), nullable=False, server_default="main"
            ),
            sa.Column(
                "environment",
                sa.String(64),
                nullable=False,
                server_default="development",
            ),
            sa.Column("owner_id", sa.Uuid()),
        ],
        "targets": [
            sa.Column(
                "display_name", sa.String(120), nullable=False, server_default="Target"
            ),
            sa.Column(
                "environment",
                sa.String(64),
                nullable=False,
                server_default="development",
            ),
            sa.Column("configuration", JSONB(), nullable=False, server_default="{}"),
            sa.Column("policy_id", sa.Uuid()),
            sa.Column("consent_at", sa.DateTime(timezone=True)),
            sa.Column("sanitized_spec", JSONB()),
        ],
        "target_secret_references": [
            sa.Column(
                "auth_type", sa.String(32), nullable=False, server_default="api_key"
            ),
            sa.Column("ciphertext", sa.Text()),
        ],
    }.items():
        for column in columns:
            op.add_column(table, column)
    op.execute("UPDATE projects SET slug = id::text, owner_id = created_by_id")
    op.create_unique_constraint(
        "uq_projects_organization_id_slug", "projects", ["organization_id", "slug"]
    )
    for table, column, parent in [
        ("projects", "owner_id", "organization_members"),
        ("targets", "policy_id", "scan_policies"),
    ]:
        op.create_foreign_key(
            f"fk_{table}_organization_id_{column}_{parent}",
            table,
            parent,
            ["organization_id", column],
            ["organization_id", "id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    op.drop_constraint("fk_targets_organization_id_policy_id_scan_policies", "targets")
    op.drop_constraint(
        "fk_projects_organization_id_owner_id_organization_members", "projects"
    )
    op.drop_constraint("uq_projects_organization_id_slug", "projects")
    for table, columns in {
        "projects": [
            "slug",
            "description",
            "default_branch",
            "environment",
            "owner_id",
        ],
        "targets": [
            "display_name",
            "environment",
            "configuration",
            "policy_id",
            "consent_at",
            "sanitized_spec",
        ],
        "target_secret_references": ["auth_type", "ciphertext"],
    }.items():
        for column in columns:
            op.drop_column(table, column)
