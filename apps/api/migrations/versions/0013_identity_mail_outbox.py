"""Encrypted identity mail outbox removes SMTP from public auth response timing."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mail_deliveries", sa.Column("organization_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_mail_deliveries_organization_id_organizations"),
        "mail_deliveries",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "mail_deliveries", sa.Column("payload_ciphertext", sa.Text(), nullable=True)
    )
    op.add_column(
        "mail_deliveries",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "mail_deliveries",
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "mail_deliveries",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_mail_deliveries_retry_at", "mail_deliveries", ["retry_at"])


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_mail_deliveries_organization_id_organizations"),
        "mail_deliveries",
        type_="foreignkey",
    )
    op.drop_column("mail_deliveries", "organization_id")
    op.drop_index("ix_mail_deliveries_retry_at", table_name="mail_deliveries")
    for column in ("attempts", "retry_at", "expires_at", "payload_ciphertext"):
        op.drop_column("mail_deliveries", column)
