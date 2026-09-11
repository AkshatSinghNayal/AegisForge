# ruff: noqa: E501
"""Immutable project gates, activation history and reproducible evaluations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def base() -> list[sa.Column]:
    return [
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
    ]


def parent(column: str, table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", column],
        [f"{table}.organization_id", f"{table}.id"],
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.execute("ALTER TYPE policyoutcome ADD VALUE IF NOT EXISTS 'incomplete'")
    op.create_table(
        "gate_policies",
        *base(),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("published_by", sa.Uuid(), nullable=False),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "project_id", "version"),
        sa.UniqueConstraint("organization_id", "project_id", "id"),
        parent("project_id", "projects"),
        parent("published_by", "organization_members"),
        sa.CheckConstraint("version > 0", name="gate_version"),
    )
    op.create_table(
        "gate_activations",
        *base(),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("gate_policy_id", sa.Uuid()),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "project_id", "sequence"),
        parent("project_id", "projects"),
        parent("actor_id", "organization_members"),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id", "gate_policy_id"],
            [
                "gate_policies.organization_id",
                "gate_policies.project_id",
                "gate_policies.id",
            ],
            ondelete="RESTRICT",
        ),
    )
    for table in ("gate_policies", "gate_activations"):
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER {table}_{operation.lower()} BEFORE {operation} ON {table} FOR EACH ROW EXECUTE FUNCTION aegis_immutable_record()"
            )
    op.add_column("policy_evaluations", sa.Column("gate_policy_id", sa.Uuid()))
    op.create_foreign_key(
        None,
        "policy_evaluations",
        "gate_policies",
        ["organization_id", "gate_policy_id"],
        ["organization_id", "id"],
        ondelete="RESTRICT",
    )
    for name in ("input_snapshot", "result_snapshot"):
        op.add_column(
            "policy_evaluations",
            sa.Column(name, JSONB(), nullable=False, server_default="{}"),
        )
    for constraint in sa.inspect(op.get_bind()).get_unique_constraints(
        "policy_evaluations"
    ):
        if "input_digest" in constraint["column_names"]:
            op.drop_constraint(constraint["name"], "policy_evaluations", type_="unique")
    op.drop_constraint(
        "ck_policy_evaluations_pass_requires_complete", "policy_evaluations"
    )
    op.create_check_constraint(
        "pass_requires_complete",
        "policy_evaluations",
        "outcome != 'pass' OR (completeness = 'complete' AND scan_state IN ('evaluating_policy', 'generating_report', 'completed'))",
    )
    op.execute("""CREATE OR REPLACE FUNCTION aegis_validate_passing_evaluation() RETURNS trigger
    LANGUAGE plpgsql AS $$ DECLARE observed RECORD; BEGIN
    IF NEW.outcome = 'pass' THEN
      SELECT state, completeness, is_demo INTO observed FROM scans
      WHERE organization_id = NEW.organization_id AND id = NEW.scan_id FOR SHARE;
      IF NOT FOUND OR observed.state NOT IN ('evaluating_policy', 'generating_report', 'completed')
      OR observed.completeness != 'complete' OR observed.is_demo
      OR observed.state != NEW.scan_state OR observed.completeness != NEW.completeness THEN
        RAISE EXCEPTION 'passing evaluation contradicts scan' USING ERRCODE = '23514';
      END IF;
    END IF; RETURN NEW; END $$""")


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM gate_policies) OR EXISTS(SELECT 1 FROM policy_evaluations WHERE input_snapshot != '{}'::jsonb)"
        )
    ):
        raise RuntimeError(
            "Cannot discard retained policy history; restore a verified backup"
        )
    op.drop_constraint(
        op.f("fk_policy_evaluations_organization_id_gate_policy_id_gate_policies"),
        "policy_evaluations",
        type_="foreignkey",
    )
    for name in ("gate_policy_id", "input_snapshot", "result_snapshot"):
        op.drop_column("policy_evaluations", name)
    op.drop_table("gate_activations")
    op.drop_table("gate_policies")
    op.create_unique_constraint(
        None,
        "policy_evaluations",
        [
            "organization_id",
            "scan_id",
            "input_digest",
            "policy_id",
            "evaluation_version",
        ],
    )
    op.drop_constraint(
        "ck_policy_evaluations_pass_requires_complete", "policy_evaluations"
    )
    op.create_check_constraint(
        "pass_requires_complete",
        "policy_evaluations",
        "outcome != 'pass' OR (completeness = 'complete' AND enrichment_status = 'complete' AND scan_state IN ('evaluating_policy', 'generating_report', 'completed'))",
    )
    op.execute("""CREATE OR REPLACE FUNCTION aegis_validate_passing_evaluation()
    RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE observed RECORD; BEGIN
      IF NEW.outcome = 'pass' THEN
        SELECT state, completeness, enrichment_status INTO observed FROM scans
        WHERE organization_id = NEW.organization_id AND id = NEW.scan_id FOR SHARE;
        IF NOT FOUND OR observed.state NOT IN
          ('evaluating_policy', 'generating_report', 'completed')
          OR observed.completeness != 'complete'
          OR observed.enrichment_status != 'complete'
          OR observed.state != NEW.scan_state
          OR observed.completeness != NEW.completeness
          OR observed.enrichment_status != NEW.enrichment_status THEN
          RAISE EXCEPTION 'passing evaluation contradicts scan'
            USING ERRCODE = '23514';
        END IF;
      END IF; RETURN NEW; END $$""")
