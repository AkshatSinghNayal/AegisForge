-- Run as migration owner using psql -v runtime_role=aegis_runtime -f this-file.
-- The runtime role MUST NOT own tables, be superuser, or inherit a table-owner role.
-- Migrations use a separate identity; audit records retain immutable DB triggers.
BEGIN;
REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON audit_logs FROM PUBLIC;
REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON audit_logs FROM :"runtime_role";
GRANT SELECT, INSERT ON audit_logs TO :"runtime_role";
REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON artifact_purges FROM PUBLIC;
REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON artifact_purges FROM :"runtime_role";
GRANT SELECT, INSERT ON artifact_purges TO :"runtime_role";
COMMIT;
