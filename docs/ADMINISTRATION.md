# Administration and audit controls — Phase 15

Organization owners and administrators use `/app/admin`, `/app/team`, `/app/settings`, `/app/policies`, `/app/integrations` and `/app/audit-log`. `/admin/users`, `/admin/policies` and `/admin/system` redirect into the authenticated workspace. These roles never grant cross-organization access. The server resolves current membership and serializes administration and scan admission on the organization row.

## Access and safe operations

Owners/admins can inspect members, manage permitted member roles, activate/deactivate members, publish/deactivate immutable scan-policy versions, change tenant controls, review jobs and deliveries, retry eligible reports/deliveries, and filter/export audit records. Only owners rename/deactivate organizations or transfer ownership. Admins cannot administer owners or other admins. Session revocation is owner-only because authentication sessions are global: it explicitly signs the member out of all organizations. Owners manage their own sessions through existing session security controls.

All writes require CSRF and current server-resolved membership. Policy revision creation remains immutable and publishes the revision; deactivation blocks submission and subsequent authorization checks without editing historical policies or evidence. Existing gate-policy publication remains separate. API keys do not gain administrative access.

A failed scan remains failed. The review UI directs an administrator to create a fresh authorized scan; active scans require a new one-use confirmation. Failed reports may be retried only before expiration using their retained redacted snapshot. Delivery retries reuse the existing outbox record and retain lifetime attempt counts; delivery remains at-least-once and recipients should deduplicate. Integration setup, connection checks, delivery outcomes and dead letters remain available in Integrations. No retry sends a message from the administration request itself.

## Safety controls

`AEGIS_EMERGENCY_STOP=true` blocks new submissions across organizations and undispatched work. `AEGIS_ACTIVE_SCANS_ENABLED=false` additionally blocks active submissions. These are operator-owned environment controls: recreate **every API/coordinator process** after changing them, using the same `aegisforge` Compose project. Organization administrators cannot override either switch. They do not cancel already dispatched scanner jobs; use scan cancellation and the existing worker lease/egress controls for in-flight work.

Tenant settings can disable all new scans or active scans and restrict concurrent scans, concurrent scans for one target, and the rolling 24-hour quota. Global configured ceilings still apply. All nonterminal scans reserve concurrency, including queued work. The organization lock covers quota counting and scan insertion across manual, API-key and webhook paths. Failed scans count toward daily quotas. Idempotent replays do not create additional work.

Tenant allow/deny lists accept canonical IPv4/IPv6 CIDRs. Deny takes precedence; an empty allow list adds no restriction. Rules are carried in the encrypted execution envelope and applied to **all freshly resolved addresses** before worker traffic. Existing independent operator origin allowlists, forbidden IP classes, private-target rules and gateway isolation remain mandatory. Changes apply to subsequently prepared execution envelopes, not already running jobs.

System status returns fixed state labels, never connection strings, credentials, exception text, container details or provider responses. API/database readiness is established by the authenticated query; Redis and worker responses have bounded probes. Scanner/AI show `disabled` or `configured_unverified`, and local report storage shows directory presence, not verified write/read availability. No paid AI call or scan is issued for a health check. These labels must not be interpreted as end-to-end availability guarantees.

## Audit contract

Records include tenant, actor membership (or system), server-generated request ID, timestamp, action, resource type/ID, result and field-name-only change summary. Successful administration reads/writes and non-admin access denials are recorded. Existing identity audit records remain separate; unauthorized requests lacking a valid tenant membership cannot be attributed to an organization. Failed transactions are rolled back and are not represented as successful writes.

Audit insertion filters change summaries through a closed allowlist; values, passwords, keys, tokens, cookies, headers, free-form changes and evidence bodies are never stored. Existing audit producers inherit the real HTTP correlation ID. `AEGIS_AUDIT_SOURCE_IP_ENABLED=false` is the default. Enable direct peer-IP recording only after establishing an applicable lawful basis and retention/access policy; do not enable untrusted forwarded-header processing. Historical events have no peer-IP metadata.

Administrators can filter by exact action, actor, resource and time range through `GET /api/v1/admin/audit`; pagination is capped at 1,000 records per request. The UI filters actions and exports the **displayed page** as JSON (100 records), with normal API authorization and an audited read. No unauthenticated export links are generated.

Database triggers reject UPDATE, DELETE and TRUNCATE of audit records and artifact deletion receipts. Production must use a runtime database role separate from the migration/table owner. Apply `infra/database/audit-permissions.sql` with `psql -v runtime_role=<runtime-role> -f ...`; the runtime role must not own tables, be superuser, or inherit an owner role. The development Compose database identity is a migration owner and is not a hardened production identity. Privileges and triggers cannot constrain a malicious database superuser.

Optional hash chaining is defense in depth, not enabled here: serialize each tenant's append sequence, hash a canonical event together with its predecessor, and periodically anchor signed chain heads outside the database. Without an external trusted anchor, an owner can rewrite an entire chain; a chain does not replace permissions, off-host audit export, monitoring or backups.

## Retention and maintenance

Tenant retention settings affect newly created report/artifact expiry timestamps; existing expirations are not silently shortened. Reports use the smaller tenant/operator duration. Raw restricted evidence retains the existing seven-day ceiling; redacted artifacts retain the existing 90-day ceiling, both subject to the tenant raw-artifact retention setting. Report expiry already runs in the API-side reporting coordinator.

Run `python -m aegis_api.maintenance` periodically from a trusted maintenance environment with database access, report-store access and the existing scanner artifact volume mounted at `AEGIS_ZAP_ARTIFACT_ROOT`. This is a bounded operator command, not a scanner-worker task: do not grant the isolated scanner worker database access. The command does not install a scheduler or alter deployment topology. Invoke it from the deployment's scheduler and monitor its exit status; storage failures fail visibly and are safe to rerun.

Each raw deletion requires an expired object, a terminal scan and no existing deletion receipt. Restricted/redacted objects expire independently. Only recorded tenant/scan-prefixed paths inside the configured root may be deleted; traversal and symlinks are rejected. Deletion is idempotent across a crash between unlink and commit. Immutable provenance, hashes, occurrences, findings, policy results and audit records remain; a separate immutable receipt records which object kind was removed. Missing content is never interpreted as clean evidence.

Credential cleanup deletes expired access credentials and fully expired refresh families while preserving live refresh chains for replay detection. Expired API keys are marked revoked and retain attribution metadata/hashes; they cannot authenticate. The command never removes live credentials or tenant history. Report expiry deletes the object and retains its metadata/snapshot; failure to delete does not mark it expired successfully.

No production roles, scheduler, external integrations, cloud resources or live scans are provisioned by this phase. See `PHASE15_TEST_REPORT.md` for executed checks and limits.
