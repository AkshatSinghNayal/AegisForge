# Data model and retention

## Ownership and constraints

PostgreSQL is authoritative. UUID primary keys and UTC `created_at`/`updated_at` apply to every entity. All tenant-owned records carry non-null `organization_id` with indexed tenant access paths; Organization uses its own `id` as the tenant root. Global identity entities explicitly listed below are the only exceptions. Ownership never follows client-supplied claims without membership checks.

Tenant children use composite foreign keys `(organization_id, parent_id)` referencing unique `(organization_id, id)` keys. Project-bound access additionally checks ProjectMember (owners/admins have organization-wide access). Row-level security is defense in depth with transaction-local tenant context; service jobs set authenticated tenant context and may not bypass business authorization. Add version columns to mutable resources and CAS on edits; immutable versions/events/results are append-only. Secret values are excluded from ordinary serialized models.

## Retention policy

Initial product defaults below are design choices, configurable downward by an organization unless security/audit minimums apply. They are not legal retention claims. Organization deletion deactivates access immediately and purges active-system tenant content within 30 days; retained audit entries are minimized/pseudonymized. Raw evidence expires after 7 days, redacted artifacts after 90 days, findings/scans/analysis/evaluations after 365 days, report bytes after 90 days. Audit records last 365 days. Backups expire within 35 days after active deletion; restore reapplies deletion tombstones before serving data. Object-store lifecycle is a second safeguard, not a replacement for database-coordinated purge.

Open findings are retained while their project is active; their expired evidence references display `expired`, never fabricate content. On deletion/expiry, remove bytes and sensitive payloads first, preserve only the minimal identifier/digest/provenance tombstone required by still-retained records. Reports snapshot redacted content and can outlive an individual source artifact for their own bounded TTL. No unbounded legal-hold feature in the MVP.

## Entity catalog

All rows have the common UUID/timestamp fields above. `org` means the organization owns the data, not the user who last edited it. Retention is measured from completion/creation unless another trigger is given.

| Entity | Owner | Important fields and relationships | Indexes / uniqueness | Retention |
| --- | --- | --- | --- | --- |
| User | Individual global identity | normalized_email, password_hash, status, profile; linked memberships | Unique normalized_email | While active; erase/anonymize 30 days after account deletion, audit references pseudonymized |
| Organization | Tenant root, controlled by owners | name, slug, status, retention_config, version | Unique slug | While active; deletion purge within 30 days |
| OrganizationMember | org | user_id, role, status, version; references User | Unique org/user; org/role/status | While membership active; revoked membership minimized for 365-day audit then purge |
| RefreshSession | Individual user, global authentication boundary | user_id, token_hash, family_id, replaced_by, expires_at, idle_expires_at, revoked_at, last_used_at | Unique token_hash; user/revoked; family | Secret hash expires with session; reuse-detection tombstones 30 days beyond family absolute expiry |
| Project | org | name, repository_ref, created_by, status, version | Unique org/name; org/status | While active; 30 days after project deletion, subject to bounded audit retention |
| ProjectMember | org | project_id, user_id, access inherited from organization role | Unique org/project/user; tenant FKs | While assigned; revoke immediately, purge within 30 days |
| Target | org, project | project_id, canonical_url, kind, scope, spec_artifact_ref, authorization_method, authorization_actor, authorization_evidence_ref, authorized_scope, authorized_until, verified_at, config_version | org/project; org/canonical_url; unique org/project/canonical_url | While active; purge 30 days after deletion; scan snapshots follow scan TTL |
| TargetSecretReference | org, target | target_id, secret_provider_ref, header_name, version, revoked_at; no secret value | org/target; unique org/target/header_name/version | Revoke immediately on removal; destroy secret within 30 days, retain non-secret audit |
| TargetImport | org, target | target_id, status, source_url_redacted, encrypted_spec_key, digest, schema_version, safe_errors, expires_at | org/target/created_at; org/status | Spec while current target config uses it; superseded imports 30 days; failed imports 7 days |
| TargetAuthorization | org, target and approving actor | target_id, method, challenge_digest, evidence_object_ref, scope_digest, version, approved_by, verified_at, expires_at, revoked_at | org/target/version; org/expires_at | Challenge expires 30 minutes; encrypted documentary evidence until grant expiry plus 30 days; minimal grant audit 365 days |
| FindingDisposition | org, finding | finding_id, lifecycle, justification_redacted, actor_id, expires_at, version | org/finding/version; org/expires_at | 365 days, purge with deleted project; expired exceptions no longer affect gates |
| ScanPolicy | org | name, mode, immutable version, thresholds, limits, required_coverage, required_enrichment, report_requirement, waiver_rules | Unique org/name/version | While referenced by retained scan/evaluation; obsolete unreferenced versions purge after 365 days |
| Scan | org, project/target | target_id, policy_id/version, frozen config, authorization snapshot, retry_of_scan_id, state, completeness, component statuses, deadlines, fence, version, demo flag | org/target/created_at/id; org/state; unique org/id | 365 days after terminal; draft maximum 24 hours then terminal TTL |
| ScanEvent | org, scan | scan_id, sequence, stage, safe message_code, attempt, timestamp | Unique org/scan/sequence | Same 365-day lifetime as scan; no bodies/secrets in event text |
| RawScanArtifact | org, scan | scan_id, restricted_object_key, redacted_object_key, hashes, scanner_version, redaction_version, size, content_type, expires_at, status | org/scan; unique org/scan/artifact_kind/content_hash | Restricted bytes 7 days; redacted bytes 90 days; minimal provenance up to scan's 365-day TTL |
| Finding | org, project/target | target_id, fingerprint, fingerprint_version, title, CWE, scanner_severity, lifecycle, first/last_seen, resolved_at, triage_version | Unique org/target/fingerprint_version/fingerprint; org/lifecycle/severity | Open while project active; resolved 365 days; project deletion purge within 30 days |
| FindingOccurrence | org, finding/scan | finding_id, scan_id, scanner_rule_id, observed_severity, safe evidence refs, occurrence_hash, coverage_ref | Unique org/scan/occurrence_hash; org/finding/created_at | 365 days; evidence refs become expired after artifact TTL |
| AIAnalysis | org, occurrence | occurrence_id, provider/model/schema/prompt versions, input_digest, evidence_refs, output JSON, confidence, status, generated_at | org/occurrence; unique org/occurrence/input_digest/provider/model/schema_version/prompt_version | 365 days or earlier occurrence purge; inputs only redacted |
| PolicyEvaluation | org, scan | scan_id, policy_version, input_digest, deterministic outcome/reason_codes, completeness, enrichment_status, evaluation_version | org/scan/created_at; unique org/scan/input_digest/policy_version | Immutable 365 days; changed inputs create a new record |
| Report | org, scan | scan_id, evaluation_id, format, object_key, hash, redaction_version, generation_status, expires_at | org/scan; org/status/created_at | Bytes 90 days; metadata 365 days; expired download returns 410 |
| NotificationDestination | org | kind, safe config, secret_reference, scope/project_ids, verified_at, enabled, version | org/kind/enabled | While active; secret revoked immediately, purge 30 days after removal |
| NotificationDelivery | org | destination_id, event_id, template_version, status, attempts, next_attempt, sanitized failure code | Unique org/destination/event/template; org/status/next_attempt | 90 days; no full notification body or credentials in diagnostics |
| Integration | org | provider, external_installation_id, allowed_repositories, credential_reference, status, version | Unique provider/external_installation_id; org/provider | While active; immediate revocation and purge within 30 days of disconnect |
| APIKey | org, issuing user/service identity | project_scopes, permission_scopes, prefix, key_hash, expires_at, revoked_at | Unique key_hash; org/prefix | Hash until expiry/revocation; non-secret metadata 365 days |
| AuditLog | org | actor_ref, action, resource_type/id, safe changed-field names, request_id, event_time | org/event_time/id; org/actor/event_time | Append-only 365 days; minimize personal data upon deletion |
| Invitation | org | normalized_email, role, project_ids, token_hash, expires_at, consumed_at | Unique token_hash; org/email/pending | Pending expires 7 days; purge 30 days after consumption/expiry |
| EmailVerificationToken | Individual global identity | user_id, email_digest, token_hash, expires_at, consumed_at | Unique token_hash; user/expires_at | Expires 24 hours; purge within 24 hours after use/expiry |
| PasswordResetToken | Individual global identity | user_id, token_hash, expires_at, consumed_at | Unique token_hash; user/expires_at | Expires 30 minutes; purge within 24 hours, security event retained separately |
| ScanConfirmation | org, target and confirming actor | target/config/policy versions, scope_digest, authorization_version, mode, expires_at, consumed_at | org/target; unique one-use nonce_hash | Expires 15 minutes; minimal confirmation audit retained 365 days |
| ScanSchedule | org, project/target | target_id, policy_version, timezone, recurrence, next_run, grant_scope_digest, grant_expires_at, max_runs, confirmed_by, enabled, version | org/next_run/enabled; org/target | While active; history 365 days; active grant expires within 30 days |
| OutboxEvent | org | aggregate_id/version, event_type, safe payload refs, published_at, attempts | Unique org/aggregate/version/event_type; published/created_at | Acknowledged events 7 days; failed events up to 30 days with alert |
| IdempotencyRecord | org (or global user for auth-only cases) | actor_id, route, key_hash, request_digest, resource_ref, expires_at | Unique scope/actor/route/key_hash | 24 hours; never cache raw secrets or response credential bodies |
| WebhookReceipt | org through verified integration | integration_id, provider_delivery_id, signed_body_digest, received_at, status | Unique integration/provider_delivery_id | 30 days; signature verified before tenant binding; no raw body retained |
| SecurityEvent | Service-owned global auth boundary | safe action/outcome, user_ref if known, request_id, coarse rate-limit metadata | event_time; user_ref/event_time | 90 days; no passwords, tokens or full IP/user-agent payloads |
| DeletionTombstone | Service-owned purge ledger | opaque org/resource IDs, deletion_time, purge_after; no content | resource_ref; deletion_time | 35 days after active purge to cover backup horizon, then delete |

Auxiliary entities after AuditLog are necessary to implement invitations, reset flows, confirmation, scheduling, reliable jobs and retention safely. They extend the prompt pack's core list explicitly.

## Findings and analytics semantics

A fingerprint uses normalized target-relative endpoint, method, parameter/location, ZAP rule/CWE and a versioned normalization algorithm, never a secret-bearing URL/query/body. Repeated observations within a scan deduplicate by occurrence_hash; different scans retain occurrences. ZAP alert identifiers are not globally unique finding IDs.

`new`, `recurring`, `changed`, `resolved`, `accepted_risk`, `false_positive` are the visible lifecycle values. Recurring means reappearance after resolution; changed means materially changed scanner severity/evidence under the same fingerprint. Accepted risk/false positive require actor, justification and expiry in audited triage data; they never delete evidence. Exclusions affect gates only when a versioned policy explicitly permits them. Complete comparable scans alone infer resolution. MTTR measures first_seen to verified resolved_at; unresolved findings are not assigned zero duration. Coverage and denominators accompany every chart.

## Persistence and deletion behavior

Transactions atomically create scan/events/outbox; constraints prevent cross-tenant relationships. Policy/config snapshots are immutable and redacted. Raw evidence access requires a separately audited administrative permission and authorized safe retrieval tooling; ordinary UI/download endpoints expose only redacted artifacts. Backups use encryption and least privilege; deletion jobs reconcile database references, S3/filesystem objects and secret-store entries with retryable progress.

## Phase 4 executable foundation

The requested 22 core entities plus IdempotencyRecord now have SQLAlchemy models and revision 0001. Other catalog entities remain future designs. [Generated schema](../generated/database-schema.md) is the exact column/constraint/index inventory; [persistence architecture](PERSISTENCE.md) records implementation choices and scope limits. In particular, project assignments use organization-member IDs, project ownership of scans/findings derives through targets, API keys have one project scope, and destinations have one optional project scope. No runtime RLS, authentication, grants/ownership verification, encryption adapter, retention jobs or execution is claimed by the schema foundation.
