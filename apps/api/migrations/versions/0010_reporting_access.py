# ruff: noqa: E501
"""Report snapshots, durable notifications and organization API keys."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("reports", "evaluation_id", nullable=True)
    op.add_column(
        "reports", sa.Column("snapshot", JSONB(), nullable=False, server_default="{}")
    )
    op.add_column(
        "reports",
        sa.Column(
            "generator_version",
            sa.String(32),
            nullable=False,
            server_default="report-v1",
        ),
    )
    op.add_column("reports", sa.Column("content_type", sa.String(100)))
    op.add_column(
        "reports",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.execute("""WITH versions AS (SELECT id, row_number() OVER
        (PARTITION BY organization_id, scan_id ORDER BY created_at, id) AS version
        FROM reports) UPDATE reports SET version = versions.version
        FROM versions WHERE reports.id = versions.id""")
    op.create_unique_constraint(
        "uq_report_version", "reports", ["organization_id", "scan_id", "version"]
    )
    op.alter_column("api_keys", "project_id", nullable=True)
    op.add_column(
        "api_keys",
        sa.Column("name", sa.String(120), nullable=False, server_default="Legacy key"),
    )
    op.add_column("api_keys", sa.Column("last_used_at", sa.DateTime(timezone=True)))
    op.add_column(
        "notification_destinations",
        sa.Column(
            "subscriptions",
            sa.ARRAY(sa.String(64)),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "notification_destinations", sa.Column("configuration_ciphertext", sa.Text())
    )
    op.alter_column("notification_deliveries", "event_id", nullable=True)
    op.add_column("notification_deliveries", sa.Column("event_key", sa.String(200)))
    op.add_column(
        "notification_deliveries",
        sa.Column("payload", JSONB(), nullable=False, server_default="{}"),
    )
    op.create_unique_constraint(
        "uq_delivery_event_key",
        "notification_deliveries",
        ["organization_id", "destination_id", "event_key"],
    )
    op.execute("""CREATE FUNCTION aegis_report_snapshot_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.snapshot IS DISTINCT FROM OLD.snapshot OR NEW.scan_id != OLD.scan_id
        OR NEW.evaluation_id IS DISTINCT FROM OLD.evaluation_id OR NEW.format != OLD.format
        OR NEW.version != OLD.version OR NEW.generator_version != OLD.generator_version
        OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
        OR NEW.organization_id != OLD.organization_id
        OR (OLD.state IN ('complete', 'expired') AND NEW.state NOT IN ('complete', 'expired'))
        OR (OLD.content_hash IS NOT NULL AND (NEW.object_key IS DISTINCT FROM OLD.object_key
          OR NEW.content_hash IS DISTINCT FROM OLD.content_hash OR NEW.content_type IS DISTINCT FROM OLD.content_type
          OR NEW.redaction_version IS DISTINCT FROM OLD.redaction_version))
      THEN RAISE EXCEPTION 'immutable report snapshot' USING ERRCODE = '23514'; END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER reports_snapshot_guard BEFORE UPDATE ON reports FOR EACH ROW EXECUTE FUNCTION aegis_report_snapshot_guard()"
    )


def downgrade() -> None:
    op.drop_constraint("uq_report_version", "reports", type_="unique")
    op.execute("DROP TRIGGER reports_snapshot_guard ON reports")
    op.execute("DROP FUNCTION aegis_report_snapshot_guard()")
    op.drop_constraint(
        "uq_delivery_event_key",
        "notification_deliveries",
        type_="unique",
    )
    for table, columns in {
        "reports": ["snapshot", "generator_version", "content_type", "version"],
        "api_keys": ["name", "last_used_at"],
        "notification_destinations": ["subscriptions", "configuration_ciphertext"],
        "notification_deliveries": ["event_key", "payload"],
    }.items():
        for column in columns:
            op.drop_column(table, column)
    # Fail transactionally if Phase 13 null-linked records still exist; never
    # silently delete retained reports, deliveries or organization keys.
    op.alter_column("reports", "evaluation_id", nullable=False)
    op.alter_column("api_keys", "project_id", nullable=False)
    op.alter_column("notification_deliveries", "event_id", nullable=False)
