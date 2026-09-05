# Requirement and test matrix

This maps planned tests, not executed application tests. `U` unit, `I` integration, `E` browser/end-to-end, `S` security/abuse. Fixtures use controlled authorized targets and secret canaries; never production targets. Every feature phase implements its tests before being declared complete.

| ID  | Requirement / synopsis module                  | Phases  | Planned tests and decisive assertion                                                                                                                                                                       |
| --- | ---------------------------------------------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R01 | Authentication, rotation and recovery (7.1)    | 3       | U TTL/hash/rotation; I refresh replay revokes family, password reset single-use, revoked sessions denied; E sign-in/out/recovery; S cookie/CSRF/storage/rate-limit tests                                   |
| R02 | Tenant isolation, roles and members (7.1, 7.9) | 3, 10   | U permission matrix; I two tenants cannot read/write/join each other's IDs, jobs, keys or downloads; E org switching/invites; S stale JWT and last-owner races                                             |
| R03 | Project CRUD and assignments (7.1)             | 4       | U request schema; I assigned developer CRUD and viewer denial; E create/edit/archive project; S tampered parent IDs                                                                                        |
| R04 | URL/OpenAPI/secret configuration (7.2)         | 4       | U URL normalization and bounded spec schema; I no secret serialization, remote-ref denial and failed import status; E target setup; S parser bombs and SSRF forms                                          |
| R05 | Ownership, active confirmation and scope (7.2) | 4, 5    | U grant expiry/version binding; I rejected absent/expired/reused grants, scope changes, redirect/rebinding/private IPv4/IPv6; E active confirmation; S authorization revoked while queued/running          |
| R06 | State transitions, schedules and retry (7.3)   | 5       | U exhaustive allowed-edge table plus forbidden-edge rejection, exclusive passive branch; I outbox dedup, cancel/deadline/CAS races, new retry ID, bounded schedule grants; E live status and cancellation  |
| R07 | ZAP and worker isolation (7.3)                 | 5, 11   | I real pinned ZAP fixture spider/passive/active modes, timeout/kill/lease loss; S metadata/internal egress denied, no Docker socket, quotas/TTL cleanup; E failures never clean                            |
| R08 | Evidence and normalization (7.3, 7.5)          | 6       | U fingerprints/dedup/redaction with canaries; I raw hashes/provenance, corrupt artifact failure, cross-scan occurrences; E redacted evidence and expired-artifact states; S hostile text is escaped        |
| R09 | Advisory structured AI (7.4)                   | 7       | U schema/confidence/evidence-ID validation; I provider adapter contract and invalid output handling; E guidance label/source references; S evidence prompt injection cannot change policy or trigger tools |
| R10 | AI outage and privacy (7.4)                    | 7       | I timeout/rate-limit/disabled/mock retains findings and status, retries bounded; S inspect provider/log/report payloads for canaries; E degraded state visible; U outage never yields pass                 |
| R11 | Lifecycle/history and completeness (7.5)       | 6, 9    | U new/recurring/changed/resolved/waiver transitions; I partial/non-comparable scans cannot resolve findings, waiver expiry audited; E history and triage; S viewer cannot disposition                      |
| R12 | PDF/JSON reports (7.5)                         | 9       | U schema and redaction; I async report failure/expiry/download auth; E download both formats; S HTML/script/URL/path injection and cross-tenant report denial; visual PDF review                           |
| R13 | Deterministic policy (7.6)                     | 8       | U exhaustive severity/completeness/enrichment/waiver truth tables; I same snapshot/version yields same result, policy unavailable fails, changed AI severity irrelevant; E reason/version display          |
| R14 | GitHub CI and keys (7.6)                       | 8       | U signature/scopes; I tampered/replayed webhook rejected/deduped, installation binding, expired/revoked key denial; E fixture workflow pass/warn/fail, required-check documentation                        |
| R15 | Notifications and PR guidance (7.6 extension)  | 10      | U safe templates; I outbox dedup/retry/dead-letter, explicit test send; S webhook SSRF, secret canaries and destination permissions; E status/retry/settings                                               |
| R16 | Dashboard and metrics (7.7)                    | 9       | U correct MTTR denominators and timezone buckets; I tenant/project filters and incomplete coverage; E empty/error/real-data charts, keyboard access; S aggregate isolation                                 |
| R17 | Storage, retention and restore (7.8)           | 9, 11   | I local/S3 adapter parity, encrypted/private access, expiry/purge reconciliation, tombstone replay after restore; S raw permission and signed URL scope; E expired report handling                         |
| R18 | Deployment and observability (7.8)             | 1, 11   | I Compose startup, migrations fresh/upgrade, staging backup/restore, health and worker recovery; S IAM/network/secrets/log review; load tests enforce quotas and redact diagnostics                        |
| R19 | Administration/auditing (7.9)                  | 3, 10   | I privilege boundaries and append-only safe audit; E member/policy/integration management; S forged role, cross-org operator access, audit mutation denial                                                 |
| R20 | Public/app UX and design reference             | 2, 3    | U reduced-motion logic; E all owning-phase routes, keyboard/focus/contrast, responsive layouts, native scroll before JS, GSAP fallback, Lenis cleanup on app navigation; no inert controls                 |
| R21 | Reliability/API execution contract             | 1, 5, 8 | U request/error/version schemas; I cursor boundaries, stable paging, idempotency payload conflict, outbox lost-message recovery, side-effect fences; E retry/error handling without fake success           |
| R22 | Demo honesty and documentation                 | 2, 12   | I demo data only from explicit seed, mock rejected in production; E demo/generated/partial labels; documentation review covers setup, limitations and actual check outputs                                 |

## Cross-cutting phase gates

Run configured formatter/linter, TypeScript/mypy, unit/integration tests and relevant builds. Add E2E/security coverage at the changed boundary, migration tests for every schema change, and manual accessible-motion/PDF inspection when applicable. Phase 12 is cumulative regression rather than a substitute for earlier tests. No real notifications or production scans are part of ordinary tests.

## Phase 0 acceptance checks

- Required files and nonempty sections; no production source or dependency manifests added.
- Nine synopsis modules map to phases and test IDs in BUILD_PLAN.
- Every catalog entity has explicit ownership, keys/indexes and retention.
- State graph forward edges and universal terminal rules are unambiguous; terminal states cannot restart; retries are separate scans.
- Required threat categories covered and tied to test IDs.
- Mermaid context/sequence/state diagrams render; validate using temporary tooling outside the repository.
- Check local Markdown links/fences and configured Markdown lint if present (none at discovery).
- Record Git limitation honestly; do not claim a commit when repository metadata is unavailable.

## Phase 1 implemented coverage

- R18/R21: `/health/live` remains HTTP 200 when dependencies fail; readiness uses real async PostgreSQL/Redis probes and returns HTTP 503 for failures/timeouts. Unit tests cover both dependency failures, timeout, cleanup, sanitized output and request correlation IDs. An explicit integration suite checks real available services and separately unreachable PostgreSQL/Redis.
- R18 security: rendered dev/prod Compose assertions prohibit published database/broker/worker ports, API/worker shared networks, worker database credentials, and default-enabled or networked ZAP. Production removes API host ports and source mounts.
- R20 foundation only: root render, validated ready/error responses, unsafe API scheme rejection, keyboard refresh in Chromium. Public route/accessibility/motion coverage remains Phase 2.
- R22: the root explicitly identifies Phase 1 limitations. `seed-demo` does not fabricate domain records. `.env.example` contains blank credential fields and safe descriptions; setup generates ignored local secrets.
- Verification is recorded in PHASE_STATUS. Live integration tests and Docker builds exist but are not counted as passed without execution. There are no domain schema changes to validate yet; fresh/repeated Alembic runner checks remain in the live Compose CI gate.

## Phase 2 implemented coverage

R20/R22: five component interaction tests cover Dialog, Dropdown, Tabs, Accordion and Sidebar. Chromium checks development labs at all seven requested widths, axe WCAG A/AA at 390/1440, four full-page screenshot baselines, real modal keyboard wrapping and focus restoration, popover dismissal and sidebar navigation, normal-motion pin/count-up and live reduced-motion cleanup. Production tests deny both development routes and retain the health journey. All displayed sample content is labeled illustrative/local; no requests execute scans. No backend schema or security boundary changes. See PHASE_STATUS for actual execution results.
