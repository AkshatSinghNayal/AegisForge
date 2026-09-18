# Reporting, notifications and public API

Phase 13 adds durable report generation, notification delivery, organization API keys and an API-key-only interface. Apply Alembic migration `0010` before starting the API. The Reports, Integrations and API Keys workspace pages expose the new commands. No later phase is included.

## Reports

`POST /api/v1/reports?organization_id=...` accepts `scan_id` and `format` (`pdf` or `json`) and returns 202 with a new report ID/version. Owner/admin/developer access and project membership are checked. Each request freezes an allowlisted snapshot; regeneration always inserts a new version. Database triggers reject changes to its snapshot, scan/evaluation references, format, generator version, retention deadline and completed artifact integrity metadata.

Snapshots include organization/project/target/scan IDs, scan policy ID/version, gate policy/evaluation references and input digest, scanner versions, captured scan state and completeness, timestamps, severity counts, occurrence/finding/artifact IDs, advisory AI analysis references, policy outcome, limitations and a redaction notice. Counts are distinct findings per observed severity. Names, URLs, headers, cookies, bodies, arbitrary scanner evidence and AI prose are withheld. Evidence IDs can be opened through the authorized findings workspace. Reports from unsuccessful, incomplete or demo scans never display a passing result. JSON follows the generated `ReportSnapshot` schema in `docs/generated/conventions.schema.json`.

The API-side durable job loop claims pending rows with `FOR UPDATE SKIP LOCKED`. PDF/JSON rendering and storage I/O run off the event loop. Success records SHA-256, generator/redaction versions, content type, private object key and expiry. Failure is retained with a fixed safe code; request a new version to retry generation. The latest report updates the scan's report status without changing its policy evaluation. Restart rolls back an unfinished database claim. A fresh random object key per attempt prevents overwrites after process crashes.

Fresh `make setup` creates the report signing and notification encryption keys in a mode-0600 ignored `.env`; existing `.env` files are preserved and need the two new keys added explicitly. Development uses a private local filesystem volume. Set `AEGIS_REPORT_SIGNING_KEY` to a persistent random value of at least 32 characters. Production selects `AEGIS_REPORT_STORAGE=s3`, a private `AEGIS_REPORT_BUCKET`, `AEGIS_REPORT_KMS_KEY_ID`, region and an AWS workload identity with narrowly scoped GetObject/PutObject/DeleteObject and KMS permissions. Writes use SSE-KMS and `If-None-Match: *`; no public ACL is used. Configure bucket lifecycle to remove crash-orphaned objects and noncurrent versions. Do not place AWS access keys in source files.

After authorization, `POST /api/v1/reports/{id}/download?organization_id=...` returns a signed URL with a 60-second default lifetime (maximum 300 seconds), capped by report expiry. Local URLs are tenant/report/expiry-bound HMAC capabilities and verify the stored checksum when redeemed; S3 uses SigV4 presigning. Possession of an issued URL grants access until it expires, even if the issuing session is subsequently revoked. Never log or share these URLs. Report expiry prevents new downloads immediately; the job loop removes expired objects and marks records expired. Database metadata and immutable snapshots remain retained for audit. For versioned S3 buckets, physical deletion of historical versions is governed by bucket lifecycle.

## Notifications

Create destinations using `POST /api/v1/notifications/destinations?organization_id=...` or Integrations. Owner/admin only; optional `project_id` restricts events. Address and adapter credentials are encrypted together, bound to organization/destination IDs, using the persistent `AEGIS_NOTIFICATION_ENCRYPTION_KEY` Fernet key. Public response models never expose them. New destinations receive future events; exception warnings also cover currently active exceptions within seven days of expiry.

| Adapter           | Address                                                             | Secret                                               |
| ----------------- | ------------------------------------------------------------------- | ---------------------------------------------------- |
| Email             | Recipient email                                                     | None; configure existing SMTP settings               |
| Slack             | `https://hooks.slack.com/services/...` incoming webhook             | None; webhook URL itself is encrypted                |
| Generic webhook   | Public HTTPS URL, port 443                                          | At least 32 characters, shared with receiver         |
| GitHub PR comment | `https://api.github.com/repos/OWNER/REPO/issues/PR_NUMBER/comments` | Token with access to that repository and PR comments |

GitHub delivery checks that the issue represents a pull request before commenting. HTTP destinations reject URL credentials, fragments, private/reserved IPs and private DNS results (including mixed public/private answers). The connector uses the validated DNS results directly on each connection, with TLS verification, no environment proxy and no redirect following. Provider responses and exception strings are never retained in delivery records or logs. SMTP host configuration is operator-controlled.

Subscriptions: `scan.completed`, `scan.failed` (also cancelled/timed-out), `policy.failed`, `finding.high` (new high/critical findings), `report.ready`, `exception.expiring`. Payloads contain a fixed event name, organization/resource IDs, a link and redaction notice. They omit findings text and target URLs. Polling uses unique destination/event keys for durable deduplication and processes up to 100 new rows per event category per destination per pass. No event category silently stops at the first page.

Delivery is **at least once**: a process crash after provider acceptance and before database commit can duplicate a message. Receivers should deduplicate `X-Aegis-Delivery`; GitHub comments carry a delivery marker and email carries a Message-ID. Failed attempts retry after 30, 60, 120 and 240 seconds, then enter `dead_letter` after five attempts. Delivery records preserve attempts, state, next attempt and safe failure code. Admin manual retry permits another attempt without resetting lifetime attempts. Disabling a destination prevents subsequent delivery.

Generic webhook headers:

- `X-Aegis-Timestamp`: Unix seconds.
- `X-Aegis-Signature`: `sha256=` followed by HMAC-SHA256 of `timestamp + "." + exact_request_body_bytes` using the shared secret.
- `X-Aegis-Delivery`: stable delivery UUID across retries.

The receiver should use constant-time signature comparison, reject timestamps outside a five-minute tolerance and deduplicate delivery IDs. Every retry gets a fresh timestamp/signature.

## API keys versus browser sessions

Session management remains under `/api/v1`; use a short-lived session access bearer credential, rotating refresh cookie and CSRF header/origin for writes. API keys do not authenticate these session endpoints. Issue/list/revoke keys through API Keys or `/api/v1/api-keys?organization_id=...`, using an owner/admin session. Name, prefix, scopes, creator, last use, expiry and revocation are retained. A 256-bit random full secret is returned **once**, then only SHA-256 is stored. A dismissed secret cannot be retrieved. Revoked/expired keys and keys whose creator loses active admin membership stop authenticating.

Machine endpoints are under `/api/public/v1`; send `Authorization: Bearer agf_...`. They accept API keys only, derive organization from the key and do not use cookies or require CSRF. Supplying an organization ID does not change their tenant. Default quota is 120 authenticated attempts per key per minute in shared Redis; Redis failure denies access. Successful authentication, scope denial and rate-limit rejection are audited; last use is updated even when a downstream operation fails. Legacy project-bound metadata keys are not accepted as organization credentials.

| Scope                | Endpoints                                                                 |
| -------------------- | ------------------------------------------------------------------------- |
| `scans:read`         | GET projects, targets, scans, scan status, scan events and policy results |
| `scans:create`       | POST scan confirmations and scans                                         |
| `findings:read`      | GET findings                                                              |
| `reports:read`       | GET report list/detail; POST signed download link                         |
| `integrations:write` | POST notification destinations                                            |

Collections support offset/page or event sequence pagination. `/scans/{id}/events?after=N` returns up to 100 typed events; repeat using the last sequence. This differs from browser-session SSE. Each request rechecks key validity. Findings use page/page_size; reports use offset. API key/destination management lists return all records, while delivery history is paginated.

Scan creation requires `Idempotency-Key`. Repeating the same body/key returns the original scan; a changed body conflicts. The namespace includes the credential ID, preserving isolation between automation clients. Current target ownership, authorization, project membership and captured configuration checks are reused from the session service. Active scans require an explicit `active_acknowledgement` and a short-lived, one-use confirmation from `/scans/confirmations`, bound to the target/configuration/policy versions. Keys cannot bypass this step.

```sh
curl "$AEGIS_ORIGIN/api/public/v1/projects" \
  -H "Authorization: Bearer $AEGIS_API_KEY"

curl "$AEGIS_ORIGIN/api/public/v1/scans" \
  -H "Authorization: Bearer $AEGIS_API_KEY" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: build-123-passive' \
  --data '{"target_id":"20000000-0000-4000-8000-000000000001","target_version":1,"policy_id":"30000000-0000-4000-8000-000000000001","policy_version":1,"trigger":{"source":"ci","branch":"main"}}'
```

Replace example UUIDs with authorized retained configuration. Use the generated OpenAPI contract for typed inputs, examples and error envelopes. Development serves `/api/v1/docs` and `/api/v1/openapi.json`; production disables interactive docs by default, so distribute `docs/generated/openapi.json`. Common failures are 401 invalid/expired/revoked key, 403 scope/role denial, 404 inaccessible resource, 409 changed configuration/idempotency conflict, 422 invalid input and 429 quota exhaustion. Errors retain the shared request correlation ID and omit submitted credentials.

## Verification boundaries

Automated tests use actual PostgreSQL/Redis and controlled adapter transports. No real email, Slack message, GitHub comment or generic webhook was sent, and no production AWS bucket was accessed. Configuring credentials does not by itself certify external delivery. Validate with an explicitly authorized destination before enabling production subscriptions. Throughput and provider availability remain operational concerns; report rendering is local in the API process and fan-out still iterates active destinations. See `PHASE13_TEST_REPORT.md` for actual commands/results and failures corrected during implementation.
