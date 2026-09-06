"""Reject passing evaluation snapshots that contradict their persisted scan.

Keep revision 0001 unchanged for databases that have already applied it.
This is an insertion consistency guard, not a policy engine or live gate reader.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE FUNCTION aegis_validate_passing_evaluation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE observed RECORD;
    BEGIN
      IF NEW.outcome = 'pass' THEN
        SELECT state, completeness, enrichment_status INTO observed
          FROM scans
          WHERE organization_id = NEW.organization_id AND id = NEW.scan_id
          FOR SHARE;
        IF NOT FOUND THEN
          RAISE EXCEPTION 'scan unavailable for passing evaluation'
            USING ERRCODE = '23514';
        END IF;
        IF observed.state NOT IN
             ('evaluating_policy', 'generating_report', 'completed')
           OR observed.completeness != 'complete'
           OR observed.enrichment_status != 'complete'
           OR observed.state != NEW.scan_state
           OR observed.completeness != NEW.completeness
           OR observed.enrichment_status != NEW.enrichment_status THEN
          RAISE EXCEPTION 'passing evaluation contradicts scan'
            USING ERRCODE = '23514';
        END IF;
      END IF;
      RETURN NEW;
    END $$""")
    op.execute("""CREATE TRIGGER policy_evaluations_scan_guard
      BEFORE INSERT ON policy_evaluations FOR EACH ROW
      EXECUTE FUNCTION aegis_validate_passing_evaluation()""")


def downgrade() -> None:
    op.execute("DROP TRIGGER policy_evaluations_scan_guard ON policy_evaluations")
    op.execute("DROP FUNCTION aegis_validate_passing_evaluation()")
