"""Freeze raw scanner artifact provenance once collected."""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TRIGGER raw_scan_artifacts_update ON raw_scan_artifacts")
    op.execute(
        "CREATE TRIGGER raw_scan_artifacts_update BEFORE UPDATE ON raw_scan_artifacts "
        "FOR EACH ROW EXECUTE FUNCTION aegis_immutable_record()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER raw_scan_artifacts_update ON raw_scan_artifacts")
    op.execute(
        "CREATE TRIGGER raw_scan_artifacts_update BEFORE UPDATE ON raw_scan_artifacts "
        "FOR EACH ROW EXECUTE FUNCTION aegis_touch_updated_at()"
    )
