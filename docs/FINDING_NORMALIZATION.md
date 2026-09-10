# Evidence-preserving finding normalization (Phase 9)

Phase 9 adds automatic normalization for newly collected ZAP artifacts, authenticated finding queries, review history and `/app/findings`. It does not run AI, evaluate policy, generate reports, or backfill historical encrypted artifacts. An existing artifact remains immutable; a later normalizer must produce another derivative, never modify the original.

## Data flow and trust

The isolated scanner worker validates ZAP alert/message responses, exports the exact raw JSON to write-once encrypted storage, and creates the existing conservative redacted artifact. It then runs the pure `zap-normalizer-v1` transformation, using worker-only credential values and configured redaction patterns. Only a validated `Observation` collection travels in the job receipt. The API has no artifact decryption key or filesystem access. Artifact IDs, organization/scan bindings, hashes and object-key prefixes retain the Phase 8 checks.

Normalization failure leaves the original durable and returns an unnormalized receipt. Collection remains partial and cannot establish resolution or a passing gate. Successful, complete scanner collection with normalized observations has complete evidence coverage; enrichment and reports remain pending and policy evaluation remains unavailable. The existing effective gate stays fail closed. Mock scans do not fabricate findings.

`FindingOccurrence` is inserted for **each alert index**, including duplicate observations that identify one canonical finding. Its occurrence hash is SHA-256 of the artifact UUID and alert index. The scan's normalization metadata makes ingestion idempotent. Occurrences and review events have database-enforced append-only behavior. The current `Finding` points to its representative occurrence/artifact/scan in `normalized.provenance`; every observation field has raw JSON pointers in `normalized.sources`. Missing optional scanner fields retain their expected source pointer and a null/empty value rather than an invented classification. Raw artifacts and occurrence rows retain tenant-safe composite foreign keys.

## Fingerprint specification

`zap-fingerprint-v1` is lowercase hexadecimal SHA-256 over UTF-8 JSON for the array:

```text
["zap-fingerprint-v1", rule, route, method, parameter, location]
```

Serialization uses `ensure_ascii=True`, compact separators `(',', ':')`, and sorted object keys (the fingerprint payload itself is an array).

- **Rule:** decimal ZAP plugin ID, leading zeroes removed.
- **Route:** URL path, default `/`; percent-encoded unreserved ASCII characters decode, other escapes use uppercase hex. Case, numeric IDs, encoded slashes and trailing slashes remain distinct. No speculative route templating merges endpoints. Target identity provides the host boundary.
- **Method:** uppercase HTTP method.
- **Parameter:** header parameter names trim surrounding whitespace and lowercase. Query/body parameter case and whitespace remain significant, so distinct application parameter names do not merge.
- **Location:** explicit query/header/body/cookie when supplied, otherwise query if the named parameter occurs in the URL query, otherwise unknown. Unknown is not silently classified as a body parameter.

Query values, fragments, scanner alert/message IDs, titles, payloads, evidence strings, HTTP bodies, timestamps, severity and confidence are excluded. Redaction occurs **after** identity calculation so distinct secret-bearing identifiers do not collapse to a shared `[REDACTED]` fingerprint. Such values are never returned in cleartext. Fingerprint version and normalizer version are independent, persisted values; changing either requires a new compatibility family and an explicit migration/backfill plan.

## Evidence and masking

Severity and scanner confidence are separate fields. ZAP's `False Positive` confidence is a scanner confidence value, not an automatic reviewer false-positive disposition. CWE, WASC and OWASP tags are retained only when supplied; no AI/category inference occurs. HTTPS references omit credential-bearing URLs, query strings and fragments, and pass through secret masking.

Request/response excerpts are bounded to 8,192 characters each. Request routes omit query values. Only allowlisted HTTP header names are displayed, with **all values masked**; request/response bodies and free-form attack/evidence strings are withheld. Full originals remain encrypted in restricted storage. Unknown header names are replaced with `[Header]`. Known credential strings (including encoded forms) and configured secret patterns are masked in ordinary metadata. Redaction metadata records the algorithm, omissions and bounds. HTML is rendered as text, never executed.

The detail view offers side-by-side request/response excerpts, an occurrence selector, immutable artifact/occurrence IDs, and field-level source pointers. It exposes no restricted object keys or download capability. AI Guidance displays actual analysis status, and Policy displays stored scan evaluations when present; neither invents analysis or a passing gate.

## Comparison and lifecycle

Comparison-family SHA-256 covers policy ID, scan mode, exact frozen configuration snapshot, fingerprint version and normalizer version. Thus target configuration versions, policy revisions and selected credential references must match. This deliberately conservative compatibility rule may start a fresh family after a harmless configuration revision; it never uses incompatible coverage to close findings. The last earlier-created, completed, complete, normalized scan in that family is the baseline, ordered by completion time and scan ID. Partial scans never become baselines.

For duplicate observations, the representative is the highest severity, then highest scanner confidence, then deterministic classification signature. All observations remain independently available. `changed` compares severity, confidence, CWE, WASC and OWASP classifications against that baseline, ignoring volatile evidence. Changes are saved on each scan; subsequent reviews cannot rewrite old comparison results.

- **New:** first observation for that target/family/fingerprint.
- **Recurring:** observed again with the same baseline classifications.
- **Changed:** observed again with different baseline classifications.
- **Resolved:** absent from a complete comparable scan after being observed in the baseline; accepted-risk and false-positive dispositions are not silently overridden.
- **Reopened:** a previously resolved finding is observed again, or a reviewer explicitly reopens it.
- **Accepted risk / false positive:** explicit reviewer decisions that persist across scans until another review action.

A failed, cancelled, timed-out or partial scan cannot resolve findings. Target-row serialization prevents concurrent ingestion races; older scans retain occurrences without overwriting a newer scan's canonical state or resolving it. No baseline means no automatic disappearance claim. Scope changes start another family and leave previous findings intact.

## API and review

All routes require current authenticated organization membership (`organization_id` selects a membership; it does not grant access), plus server-side project membership for developers/viewers. Owners/admins have organization-wide access. Cookie-authenticated mutations require CSRF protection. Owners/admins and assigned developers can review; viewers cannot. Review commands use optimistic `version` checks and create a `FindingReview` history row plus an `AuditLog` event in the same transaction. Audit events contain field names and IDs, never note content.

- `GET /api/v1/findings`: `project`, `target`, `scan`, `severity`, `confidence`, `status`, `cwe`, `owasp`, `route`, `date_from`, `date_to`; `page` (1-based), `page_size` (1–100), `sort`, `direction`. Date filters use last-seen time; datetime values without a timezone are interpreted as UTC. Route filtering is literal substring matching, not wildcard SQL. Sort values are allowlisted and tied by ID.
- `GET /api/v1/findings/{id}`: canonical summary, normalized metadata, occurrences/evidence sources, history, analysis status and stored policy impact.
- `GET /api/v1/findings/comparison/{scan_id}`: completeness, baseline and saved per-finding classifications; unavailable normalization is explicit null.
- `POST /api/v1/findings/{id}/review`: `action` (`accept_risk`, `false_positive`, `reopen`, `resolve`, `note`), required `note`, current `version`, and `verification_scan_id` for resolution. Resolution requires a later complete scan in the same target/family that verifies absence. A note alone does not change disposition.

The findings table persists filters/sort/pagination in the URL. Detail links preserve list filters. Review UI is hidden for viewers, while the API independently checks permissions. Findings are real stored observations; browser fixtures are explicitly synthetic test-only HTTP responses.

## Operations and migration

Apply Alembic revision `0007` after `0006`; no new environment variables or dependency versions are required. The migration adds scan normalization metadata, finding classification/provenance fields, occurrence derivatives, `reopened`, and review history. Existing findings remain in the `legacy` family. Upgrade/downgrade/re-upgrade is supported on databases without Phase 9 evidence; downgrade refuses to discard retained normalization/review data. The added PostgreSQL enum value remains on a non-destructive downgrade.

Tests and actual verification results are recorded in [PHASE9_TEST_REPORT](PHASE9_TEST_REPORT.md). Existing encrypted-artifact retention/purge automation, real AI execution, deterministic policy implementation and reports remain separate work. No later phase starts automatically.
