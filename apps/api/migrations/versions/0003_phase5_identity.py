"""Phase 5 identity lifecycle and organization invitations."""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN email_verified_at TIMESTAMPTZ")
    op.execute("""
CREATE TABLE access_credentials (
	user_id UUID NOT NULL,
	family_id UUID NOT NULL,
	token_hash VARCHAR(64) NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_access_credentials PRIMARY KEY (id),
	CONSTRAINT fk_access_credentials_user_id_users
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
	CONSTRAINT uq_access_credentials_token_hash UNIQUE (token_hash)
)

""")
    op.execute(
        "CREATE INDEX ix_access_credentials_family_id ON access_credentials (family_id)"
    )
    op.execute(
        "CREATE TRIGGER access_credentials_touch "
        "BEFORE UPDATE ON access_credentials "
        "FOR EACH ROW EXECUTE FUNCTION aegis_touch_updated_at()"
    )
    op.execute("""
CREATE TABLE identity_tokens (
	user_id UUID NOT NULL,
	purpose VARCHAR(24) NOT NULL,
	token_hash VARCHAR(64) NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	used_at TIMESTAMP WITH TIME ZONE,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_identity_tokens PRIMARY KEY (id),
	CONSTRAINT fk_identity_tokens_user_id_users
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
	CONSTRAINT uq_identity_tokens_token_hash UNIQUE (token_hash)
)

""")
    op.execute(
        "CREATE TRIGGER identity_tokens_touch "
        "BEFORE UPDATE ON identity_tokens "
        "FOR EACH ROW EXECUTE FUNCTION aegis_touch_updated_at()"
    )
    op.execute("""
CREATE TABLE invitations (
	normalized_email VARCHAR(320) NOT NULL,
	role role NOT NULL,
	token_hash VARCHAR(64) NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	used_at TIMESTAMP WITH TIME ZONE,
	organization_id UUID NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_invitations PRIMARY KEY (id),
	CONSTRAINT uq_invitations_organization_id_id UNIQUE (organization_id, id),
	CONSTRAINT uq_invitations_token_hash UNIQUE (token_hash),
	CONSTRAINT fk_invitations_organization_id_organizations
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE RESTRICT
)

""")
    op.execute(
        "CREATE TRIGGER invitations_touch "
        "BEFORE UPDATE ON invitations "
        "FOR EACH ROW EXECUTE FUNCTION aegis_touch_updated_at()"
    )
    op.execute("""
CREATE TABLE identity_audits (
	user_id UUID,
	action VARCHAR(100) NOT NULL,
	request_id UUID NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_identity_audits PRIMARY KEY (id),
	CONSTRAINT fk_identity_audits_user_id_users
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)

""")
    op.execute(
        "CREATE TRIGGER identity_audits_touch "
        "BEFORE UPDATE ON identity_audits "
        "FOR EACH ROW EXECUTE FUNCTION aegis_immutable_record()"
    )
    op.execute("""
CREATE TABLE mail_deliveries (
	user_id UUID,
	purpose VARCHAR(24) NOT NULL,
	status VARCHAR(24) NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_mail_deliveries PRIMARY KEY (id),
	CONSTRAINT fk_mail_deliveries_user_id_users
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)

""")
    op.execute(
        "CREATE TRIGGER mail_deliveries_touch "
        "BEFORE UPDATE ON mail_deliveries "
        "FOR EACH ROW EXECUTE FUNCTION aegis_touch_updated_at()"
    )


def downgrade() -> None:
    op.drop_table("mail_deliveries")
    op.drop_table("identity_audits")
    op.drop_table("invitations")
    op.drop_table("identity_tokens")
    op.drop_table("access_credentials")
    op.drop_column("users", "email_verified_at")
