# Planned API contract

## Conventions

All resource routes below are prefixed `/api/v1`. This is a design contract, not implemented OpenAPI. Phase 1 establishes the typed client strategy; feature phases add executable Pydantic/OpenAPI schemas with generated TypeScript types. Health probes `/health/live` and `/health/ready` are outside the versioned business API and expose only safe status; detailed operational metrics require operator authentication.

UUID IDs and UTC ISO-8601 timestamps. Reject unknown request fields and oversized inputs. Validate external data before persistence. Writes require CSRF and Origin validation for cookie sessions. Return 401 for no valid identity, 403 for insufficient role on a known authorized resource, and 404 for cross-tenant/unassigned resource IDs. Error details must not reveal another tenant's existence.

Default list response: `{ "data": [], "page": { "next_cursor": null, "has_more": false }, "request_id": "uuid" }`. Opaque cursor binds tenant, filters and stable `(created_at,id)` ordering; default limit 25, maximum 100. Filtering/sorting fields are allowlisted. Individual response: `{ "data": {}, "request_id": "uuid" }`; deletes/revocations return 204 without body. Create 201, asynchronous command 202, reads/updates 200 unless stated otherwise.

Require `Idempotency-Key` for scan start/retry, report requests, invitation issuance, confirmation consumption, explicit sends and integration event commands. The server binds key to tenant+actor+method+route and canonical request digest for 24 hours: matching retries return the same resource/status; a different payload returns 409. No secret-bearing response is cached. Durable event IDs/job constraints continue preventing duplicate work after the key expires. PATCH/DELETE mutable resources require `If-Match` version; missing precondition 428, stale version 412.

Error body (also on asynchronous resource failure, using safe stored error fields):

```json
{
  "error": {
    "code": "target_authorization_expired",
    "message": "Renew target authorization before starting a scan.",
    "details": [{ "field": "target_id", "code": "authorization_expired" }],
    "request_id": "uuid",
    "retryable": false
  }
}
```

Other statuses: 400 malformed, 409 state/idempotency conflict, 410 expired artifact, 413 size limit, 415 media type, 422 validation, 429 throttled with Retry-After, 503 unavailable. No traceback, credential or unredacted target payload in errors.

## Authorization notation

`Self`: authenticated user on own identity/session. `Member`: current organization member. `Read`: viewer/developer assigned to project, or owner/admin. `Write`: assigned developer, or owner/admin. `Admin`: organization owner/admin. `Owner`: organization owner only. `Key`: active scoped API key with matching org/project/permission and expiry; it is not an unrestricted role. No tenant ID in a JWT/key bypasses server authorization. Each `/organizations/{orgId}` child route binds that tenant; shorter resource routes resolve organization_id from server-side resource and authenticated context. `Webhook`: verified integration signature and binding.

## Identity and organizations

| Method | Path | Auth | Request -> response |
| --- | --- | --- | --- |
| POST | /auth/register | Public, rate limited | Email/password/name -> User summary, verification requirements; no client-supplied admin role |
| POST | /auth/email-verification-requests | Self, rate limited | Request one-use email verification -> uniform 202 response |
| POST | /auth/verify-email | One-use verification token | Token -> verified identity, 204; no role elevation |
| POST | /auth/sign-in | Public, rate limited | Credentials -> profile and HttpOnly access/refresh cookies; never tokens in JSON |
| POST | /auth/refresh | Refresh cookie + CSRF | Rotate token transactionally -> new cookies; reuse revokes family |
| POST | /auth/sign-out | Self + CSRF | Revoke current session family -> 204 and cleared cookies |
| POST | /auth/forgot-password | Public, rate limited | Email -> uniform 202 response; bounded recovery token via configured channel |
| POST | /auth/reset-password | One-use reset token | Token/new password -> 204, invalidate sessions |
| GET, PATCH | /me | Self | Read/update safe profile fields -> profile/version |
| GET | /me/sessions | Self | Cursor -> safe session metadata, no hashes |
| DELETE | /me/sessions/{sessionId} | Self | Revoke own session family -> 204 |
| GET, POST | /organizations | Self | List memberships / create name -> organization plus owner membership |
| GET, PATCH | /organizations/{orgId} | Member / Admin | Read safe org settings / update name-retention settings -> versioned organization |
| DELETE | /organizations/{orgId} | Owner | Confirm organization deletion -> 202 purge request, immediate access revocation |
| POST | /organizations/{orgId}/ownership-transfer | Owner | Existing active member ID -> atomic role transfer; last-owner invariant |
| GET | /organizations/{orgId}/members | Admin | Cursor -> users/roles/status |
| PATCH, DELETE | /organizations/{orgId}/members/{userId} | Admin, Owner for owner changes | Role/status or remove -> versioned membership/204; no last-owner removal |
| POST | /organizations/{orgId}/invitations | Admin | Email/role/project IDs -> invitation metadata; idempotent |
| GET, DELETE | /organizations/{orgId}/invitations/{invitationId} | Admin | Inspect/revoke -> metadata/204 |
| POST | /invitations/accept | Self, matching verified identity | One-use token -> membership; no arbitrary email reassignment |

## Projects, targets and policies

| Method | Path | Auth | Request -> response |
| --- | --- | --- | --- |
| GET, POST | /organizations/{orgId}/projects | Member / Admin or developer | Assigned-project list / name+repository -> project with creator membership |
| GET, PATCH, DELETE | /projects/{projectId} | Read / Write / Admin | Resource fields -> versioned project / 204 with bounded purge |
| GET, PUT, DELETE | /projects/{projectId}/members/{userId} | Admin | Read/assign/remove existing org member -> assignment/204 |
| GET, POST | /projects/{projectId}/targets | Read / Write | List / URL, kind, scope, policy -> target; creation alone does not authorize scans |
| GET, PATCH, DELETE | /targets/{targetId} | Read / Write / Write | Safe config -> target/version; changes invalidate prior grants |
| POST | /targets/{targetId}/openapi-imports | Write | Bounded multipart spec or HTTPS URL -> 202 validated import status/reference; no uncontrolled external refs |
| GET | /targets/{targetId}/openapi-imports/{importId} | Read | Import progress -> safe validation errors and stored spec reference |
| POST | /targets/{targetId}/authorization-challenges | Write | Requested verified scope -> challenge instructions/expiry |
| POST | /targets/{targetId}/authorization-verifications | Write, Admin for documentary approval | Challenge result or approved evidence reference -> authorization metadata/status/expiry |
| DELETE | /targets/{targetId}/authorization | Write | Revoke authorization and stop pending/running authorization-dependent work -> 204 |
| PUT, DELETE | /targets/{targetId}/secrets/{name} | Write | Secret through protected input -> secret reference only / revoke 204; never echo plaintext |
| POST | /targets/{targetId}/scan-confirmations | Write | Mode, frozen config/policy versions, optional bounded schedule scope/run count, and explicit acknowledgment -> confirmation ID/expiry/scope digest; no scan is started |
| GET, POST | /organizations/{orgId}/scan-policies | Member / Admin | List / policy rules and limits -> immutable version |
| GET | /scan-policies/{policyId} | Member | Versioned policy and deterministic rules |
| POST | /scan-policies/{policyId}/versions | Admin | Revised rules and change reason -> new version; old stays immutable |
| GET, POST | /targets/{targetId}/schedules | Read / Write | List / recurrence/timezone/policy and bounded grant if active -> schedule; confirmation mandatory for active grant |
| PATCH, DELETE | /schedules/{scheduleId} | Write | Enable/disable/change with refreshed active grant -> version / 204 |

## Scans, findings and analysis

| Method | Path | Auth | Request -> response |
| --- | --- | --- | --- |
| GET | /organizations/{orgId}/scans | Member, Key scans:read | Filter target/project/state/time, cursor -> authorized scans |
| POST | /scans | Write, Key scans:write | Target ID and policy version -> draft scan; authorization metadata must be current |
| GET | /scans/{scanId} | Read, Key scans:read | State, completeness, stage/component status, coverage, latest evaluation reference and safe failure reason |
| POST | /scans/{scanId}/start | Write, Key scans:write | Confirmation ID or valid schedule grant for active -> 202 queued scan; idempotent, immutable snapshot |
| POST | /scans/{scanId}/cancel | Write, Key scans:write | Reason -> terminal cancellation status, async runner cleanup; terminal conflict 409 |
| POST | /scans/{scanId}/retry | Write, Key scans:write | New policy/config references -> new draft with retry_of; new active confirmation needed on start |
| GET | /scans/{scanId}/events | Read, Key scans:read | `after_sequence`, limit -> ordered persistent events; polling baseline, no assumed WebSocket dependency |
| GET | /scans/{scanId}/artifacts | Read | Redacted artifact metadata, provenance, expiry; no restricted raw URLs |
| GET | /artifacts/{artifactId}/download | Read | Authorized redacted stream or short-lived scoped URL; 410 when expired |
| GET | /organizations/{orgId}/findings | Member, Key findings:read | Project/target/severity/lifecycle/CWE filters + cursor -> authorized findings |
| GET | /findings/{findingId} | Read, Key findings:read | Scanner evidence summary, lifecycle, occurrences, generated-analysis references |
| PATCH | /findings/{findingId}/disposition | Write (Admin for accepted risk/false positive) | Lifecycle/justification/expiry/version -> audited disposition; cannot manually assert verified resolution |
| GET | /findings/{findingId}/occurrences | Read | Cursor -> per-scan observations and safe evidence refs |
| GET | /occurrences/{occurrenceId}/analyses | Read | Cursor -> validated generated advice, status, model/provenance/confidence |
| POST | /occurrences/{occurrenceId}/analyses | Write | Provider selection permitted by policy -> 202 analysis attempt; redacted evidence only, idempotent |
| GET | /scans/{scanId}/policy-evaluations | Read, Key gates:read | Immutable evaluation history with reason codes and policy/input versions |
| POST | /scans/{scanId}/policy-evaluations | Admin, Key gates:evaluate | Allowed policy version -> new deterministic evaluation, never AI-authored decision; idempotent |
| GET | /scans/{scanId}/gate | Read, Key gates:read | Outcome, pending flag, reason codes, evaluation reference if durable; pending/incomplete/unavailable is fail and cannot be treated as pass |

## Reports, analytics, integrations and administration

| Method | Path | Auth | Request -> response |
| --- | --- | --- | --- |
| GET | /organizations/{orgId}/reports | Member | Cursor/project/format/status -> permitted report metadata |
| POST | /scans/{scanId}/reports | Write, Key reports:write | PDF/JSON, evaluation reference -> 202 report; idempotent, redacted content only |
| GET | /reports/{reportId} | Read, Key reports:read | Generation status/hash/expiry and safe error |
| GET | /reports/{reportId}/download | Read, Key reports:read | Authorized private download, no arbitrary filename or object key; 410 expired |
| GET | /organizations/{orgId}/analytics | Member | Authorized projects, bounded date interval/granularity -> severity/status/CWE/trends/coverage/recurrence/MTTR with denominators |
| GET, POST | /organizations/{orgId}/integrations | Admin | Safe list / provider/install request -> configuration state, no secret returned |
| GET, PATCH, DELETE | /integrations/{integrationId} | Admin | Safe metadata / scopes/config / disconnect -> version/204 |
| POST | /integrations/github/callback | Self + verified integration state | Provider callback state/code -> bound installation; reject replay/mismatch |
| POST | /webhooks/github | Webhook | Signed bounded raw event -> 202 receipt; verified binding and delivery-ID dedup before jobs |
| GET, POST | /organizations/{orgId}/api-keys | Admin | List metadata / scopes+projects+expiry -> one-time key secret at creation only; no idempotent secret replay |
| DELETE | /api-keys/{keyId} | Admin | Revoke -> 204 |
| GET, POST | /organizations/{orgId}/notification-destinations | Admin | List / kind+scopes+secret input -> safe destination metadata |
| PATCH, DELETE | /notification-destinations/{destinationId} | Admin | Settings/disable/revoke -> version/204 |
| POST | /notification-destinations/{destinationId}/test | Admin, explicit action | Minimized test template -> 202 delivery; idempotent, real send requires operator/user authorization |
| GET | /organizations/{orgId}/notification-deliveries | Admin | Status/destination/cursor -> sanitized delivery history |
| POST | /notification-deliveries/{deliveryId}/retry | Admin | Explicit retry -> 202 attempt, idempotent |
| GET | /organizations/{orgId}/audit-log | Admin | Actor/resource/time/cursor -> safe append-only audit events |
| GET | /organizations/{orgId}/system-status | Admin | Safe integration/queue/health summary; no tenant-external infrastructure secrets |

Team and `/admin/users` screens use membership endpoints; `/admin/policies` uses policy versions; `/admin/system` uses organization-safe system status. No hidden superuser CRUD endpoints. Profile security uses session revocation and password recovery. Organization switching changes client context but grants no authority by itself.

GitHub Actions builds and serves a reachable authorized test target, creates/starts a scan, polls events/gate and returns the deterministic result. Active CI runs use previously explicitly confirmed bounded grants; an API key alone is not an active confirmation. Required GitHub checks and deployment policy must be configured by the repository owner.

Initial CI adapter exit contract: pass=0, warn=2, fail=1. Only pass is a successful required check; warn remains a distinct non-success result with its reason codes. Transport failure, polling deadline and unavailable evaluation exit 1. This fail-closed default can be changed only through an explicit versioned policy/adapter decision, never by AI output.

## Phase 4 implementation boundary

The route tables above remain planned. Phase 4 implements persistence and reusable conventions only; current executable routes are health plus development/test `/api/v1/docs` and `/api/v1/openapi.json`. See [current OpenAPI](generated/openapi.json), [convention schemas](generated/conventions.schema.json) and [persistence contract](architecture/PERSISTENCE.md).

Current error objects contain exactly code, message, details, request_id inside error; the proposed retryable field above is deferred. Details are empty unless explicitly allowlisted; validation inputs and locations are not echoed. Readiness 503 retains its original safe health response. Findings filters use `target_id`, `severity`, `state`, `cwe`; event filters require `scan_id`. Ordering is `order=created_at|-created_at`, with UUID tie-breaker. Cursor binding includes limit and filters. Missing version preconditions are 428, stale CAS is 412. These primitives expose no unauthenticated domain routes. Policy replacement is a new immutable version, never an in-place PATCH.

Phase 4 strict review adds revision 0002 to reject passing snapshots that contradict the referenced scan, an internal command savepoint and refreshed locked idempotency receipts. If-Match values must fit PostgreSQL INTEGER (1–2147483647). Current OpenAPI explicitly declares the established readiness 503 Health response. No new domain route is exposed.
