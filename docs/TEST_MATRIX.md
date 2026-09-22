# Requirement and test matrix

This maps planned tests, not executed application tests. `U` unit, `I` integration, `E` browser/end-to-end, `S` security/abuse. Fixtures use controlled authorized targets and secret canaries; never production targets. Every feature phase implements its tests before being declared complete.

| ID  | Requirement / synopsis module                  | Phases                          | Planned tests and decisive assertion                                                                                                                                                                       |
| --- | ---------------------------------------------- | ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R01 | Authentication, rotation and recovery (7.1)    | Identity prerequisite (TBD)     | U TTL/hash/rotation; I refresh replay revokes family, password reset single-use, revoked sessions denied; E sign-in/out/recovery; S cookie/CSRF/storage/rate-limit tests                                   |
| R02 | Tenant isolation, roles and members (7.1, 7.9) | Identity prerequisite (TBD), 10 | U permission matrix; I two tenants cannot read/write/join each other's IDs, jobs, keys or downloads; E org switching/invites; S stale JWT and last-owner races                                             |
| R03 | Project CRUD and assignments (7.1)             | 6                               | U request schema; I admin project CRUD, assigned developer target CRUD and viewer denial; E create/edit/archive project; S tampered parent IDs                                                             |
| R04 | URL/OpenAPI/secret configuration (7.2)         | 6                               | U URL normalization and bounded spec schema; I no secret serialization, remote-ref denial and failed import status; E target setup; S parser bombs and SSRF forms                                          |
| R05 | Ownership, active confirmation and scope (7.2) | 6, future executor              | U grant expiry/version binding; I rejected absent/expired/reused grants, scope changes, redirect/rebinding/private IPv4/IPv6; E active confirmation; S authorization revoked while queued/running          |
| R06 | State transitions, schedules and retry (7.3)   | 5                               | U exhaustive allowed-edge table plus forbidden-edge rejection, exclusive passive branch; I outbox dedup, cancel/deadline/CAS races, new retry ID, bounded schedule grants; E live status and cancellation  |
| R07 | ZAP and worker isolation (7.3)                 | 5, 11                           | I real pinned ZAP fixture spider/passive/active modes, timeout/kill/lease loss; S metadata/internal egress denied, no Docker socket, quotas/TTL cleanup; E failures never clean                            |
| R08 | Evidence and normalization (7.3, 7.5)          | 6                               | U fingerprints/dedup/redaction with canaries; I raw hashes/provenance, corrupt artifact failure, cross-scan occurrences; E redacted evidence and expired-artifact states; S hostile text is escaped        |
| R09 | Advisory structured AI (7.4)                   | 7                               | U schema/confidence/evidence-ID validation; I provider adapter contract and invalid output handling; E guidance label/source references; S evidence prompt injection cannot change policy or trigger tools |
| R10 | AI outage and privacy (7.4)                    | 7                               | I timeout/rate-limit/disabled/mock retains findings and status, retries bounded; S inspect provider/log/report payloads for canaries; E degraded state visible; U outage never yields pass                 |
| R11 | Lifecycle/history and completeness (7.5)       | 6, 9                            | U new/recurring/changed/resolved/waiver transitions; I partial/non-comparable scans cannot resolve findings, waiver expiry audited; E history and triage; S viewer cannot disposition                      |
| R12 | PDF/JSON reports (7.5)                         | 9                               | U schema and redaction; I async report failure/expiry/download auth; E download both formats; S HTML/script/URL/path injection and cross-tenant report denial; visual PDF review                           |
| R13 | Deterministic policy (7.6)                     | 8                               | U exhaustive severity/completeness/enrichment/waiver truth tables; I same snapshot/version yields same result, policy unavailable fails, changed AI severity irrelevant; E reason/version display          |
| R14 | GitHub CI and keys (7.6)                       | 8                               | U signature/scopes; I tampered/replayed webhook rejected/deduped, installation binding, expired/revoked key denial; E fixture workflow pass/warn/fail, required-check documentation                        |
| R15 | Notifications and PR guidance (7.6 extension)  | 10                              | U safe templates; I outbox dedup/retry/dead-letter, explicit test send; S webhook SSRF, secret canaries and destination permissions; E status/retry/settings                                               |
| R16 | Dashboard and metrics (7.7)                    | 9                               | U correct MTTR denominators and timezone buckets; I tenant/project filters and incomplete coverage; E empty/error/real-data charts, keyboard access; S aggregate isolation                                 |
| R17 | Storage, retention and restore (7.8)           | 9, 11                           | I local/S3 adapter parity, encrypted/private access, expiry/purge reconciliation, tombstone replay after restore; S raw permission and signed URL scope; E expired report handling                         |
| R18 | Deployment and observability (7.8)             | 1, 11                           | I Compose startup, migrations fresh/upgrade, staging backup/restore, health and worker recovery; S IAM/network/secrets/log review; load tests enforce quotas and redact diagnostics                        |
| R19 | Administration/auditing (7.9)                  | Identity prerequisite (TBD), 10 | I privilege boundaries and append-only safe audit; E member/policy/integration management; S forged role, cross-org operator access, audit mutation denial                                                 |
| R20 | Public/app UX and design reference             | 2, 3                            | U reduced-motion logic; E all owning-phase routes, keyboard/focus/contrast, responsive layouts, native scroll before JS, GSAP fallback, Lenis cleanup on app navigation; no inert controls                 |
| R21 | Reliability/API execution contract             | 1, 5, 8                         | U request/error/version schemas; I cursor boundaries, stable paging, idempotency payload conflict, outbox lost-message recovery, side-effect fences; E retry/error handling without fake success           |
| R22 | Demo honesty and documentation                 | 2, 12                           | I demo data only from explicit seed, mock rejected in production; E demo/generated/partial labels; documentation review covers setup, limitations and actual check outputs                                 |

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

## Phase 3 public website acceptance

`apps/web/e2e/marketing.spec.ts` covers all 17 public routes and unique metadata, internal destination inventory, setup/architecture CTAs, documentation search and empty state, six viewport widths (360–1920px), mobile drawer, normal desktop pin/crossfade, live reduced-motion teardown and stacked content, Lenis removal on health navigation, unknown docs, static metadata without JavaScript, trailing-slash routes, short desktop fallback, sitemap/robots, and axe WCAG A/AA checks on desktop/mobile home. Existing health and laboratory tests remain in the full regression. Frontend unit tests reject unsafe canonical origins and malformed public contact addresses. No domain change requires new database or scan-security integration tests in this phase.

Screenshot outputs in `/tmp/aegis-home-{mobile,desktop}.png` support visual inspection and are not invented screenshot-regression baselines. No supplied reference video, direct screen-reader session, non-Chromium certification, Lighthouse measurement or live Docker verification is claimed.

### Phase 3 strict review completion — 2026-09-06

See [TEST_REPORT](TEST_REPORT.md). The expanded marketing review checks all 17 routes at 360/390/768/1024/1280/1440/1920px with axe WCAG 2/2.1 A/AA and 2.2 AA tags, case variants, footer/mobile navigation focus, complete nonvisual workflow, and normal pin containment. Build configuration failures and the real documented setup command are tested. Final totals: 18 frontend tests, 9 backend unit/security tests, 3 live integration tests, 42 Playwright tests. Development/production Docker health, repeated migrations and complete review-stack teardown passed. The missing-Docker gate is resolved.

## Phase 4 implemented coverage

R02/R18/R21: real PostgreSQL disposable-database upgrade/downgrade/re-upgrade and Alembic metadata-drift checks; two-organization factories; composite FK/unique/delete behavior; tenant repository get/add/CAS denial; immutable graph/history and timestamp triggers; signed cursor boundaries, equal timestamps and foreign-filter emptiness; idempotency scan/report/webhook operation scopes, payload conflict, TTL, concurrent retry and rollback. R08/R13 foundation guards separate evidence/advice/policy and forbid passing incomplete snapshots. R22 factories use synthetic `.invalid` targets with disabled external actions and no actual secrets. API E2E boundary tests check sanitized HTTP/validation/unexpected errors, correlation headers and production docs denial. Authentication/project permissions, execution and browser CRUD journeys remain deferred; they are not claimed by these tests.

## Phase 5 implemented acceptance mapping

| Requirement                                                                                 | Executable evidence                                                                 |
| ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Password storage, role action matrix                                                        | `test_auth.py::test_password_hash_and_policy`                                       |
| Registration, verification, refresh rotation/replay and logout                              | `test_registration_rotation_replay_logout`                                          |
| Reset expiry/single use and all-session revocation                                          | `test_reset_expiry_single_use_revokes_all`                                          |
| Brute-force counters, generic failures and CSRF                                             | `test_rate_limit_and_csrf`                                                          |
| Every role, foreign organizations/object IDs, assigned-project visibility, deactivation     | `test_role_endpoints_and_real_foreign_ids` (four roles)                             |
| Invite email binding/reuse and ownership transfer                                           | `test_invite_binding_single_use_and_ownership`                                      |
| Registration/login/logout/protected route/bootstrap/onboarding/switcher/mobile/collapse     | `apps/web/e2e/auth.spec.ts` via `make test-auth-e2e`                                |
| Simultaneous refresh replay, secure cookies, access expiry, complete member mutation matrix | Additional `test_auth.py` integration cases                                         |
| Existing provenance and migration regression                                                | Existing database and Phase 4 review suites, including upgrade/downgrade/re-upgrade |

Future policy/integration/scanner mutation permissions are tested as authorization policy only; nonexistent future endpoints are not reported as endpoint-tested. SMTP test delivery is captured locally in the API tests, not sent to external recipients.

## Phase 6 implemented coverage

R02–R05/R13/R19/R21: `test_configuration.py` covers URL syntax, public/private/special IPv4/IPv6 classifications, mixed DNS answers, numeric aliases, connect-time DNS pinning, redirect rebinding, metadata addresses, invalid/oversized/deep/aliased/tagged OpenAPI, external references, sanitized secret canaries, context-bound encryption, input-only credential schemas, policy guards, real PostgreSQL project/target CRUD, archive/restore, admin/developer/viewer assignment enforcement, foreign IDs, immutable policy revisions and failed-validation atomicity. Existing migration round trips and metadata drift checks include revision 0004.

R20: `configuration.spec.ts` runs real registration/login/project creation, standard/custom internal-test policy setup, OpenAPI target wizard, encrypted bearer reference creation, credential revocation, project edit/archive/restore and desktop/mobile axe checks. It uses the disposable HTTP fixture only. Full test results and limitations are recorded in PHASE_STATUS.md. No scanner, gate or production secret-provider execution is claimed.

## Phase 7 execution coverage

`test_scans.py` covers the complete state graph, stale fences, safe-code redaction, provider guards, idempotent creation/conflict, quotas, active grant binding/consumption, cancellation/deadline, worker-loss safe versus unsafe retries, Redis publication interruption, real Redis duplicate admission and fail-closed connection errors, missing/invalid provider results, selected-reference/version/CSRF/RBAC denial, and ordered SSE replay. `Scans.test.tsx` covers duplicate event merging. `scans.spec.ts` runs the real PostgreSQL/Redis/Celery mock pipeline, browser connection recovery, final failing gate, history metadata, cancellation and responsive axe/overflow inspection. See PHASE7_TEST_REPORT.md for actual results and limitations.

## Phase 8 scanner execution coverage

`test_zap.py` covers both provider contracts, DNS/allowlist/authorization and active-internet denial, scoped worker decryption, OpenAPI sanitization/import, traditional/AJAX ordering, active-rule restriction, bounded polling, timeout/cancellation/crashes/malformed responses, budget failure, encrypted write-once artifacts, conservative redaction, Docker resource limits and management isolation. Real loopback HTTP/TLS gateway tests assert that denied destinations cause no upstream connection.

`test_zap_dispatch.py` checks tenant/job/fence/version binding, real progress/replay, immutable PostgreSQL artifact insertion, cross-tenant rejection, partial completion and no unsafe retry. Migration regressions include revision 0006 and downgrade/re-upgrade without evidence deletion.

`test_zap_live.py` is explicitly enabled with `AEGIS_RUN_ZAP_LIVE=1`: digest-pinned ZAP runs only against a disposable internal training target, with passive, active, OpenAPI, cancellation, deadline, process-crash and cleanup cases. A second unauthorized canary must receive zero requests. The route/lease test attempts direct target/canary access, a foreign proxy request and heartbeat loss. Ordinary suite skips are not counted as successful live tests. Actual commands/results are recorded in PHASE8_TEST_REPORT.md.

## Phase 9 implemented coverage

R02/R08/R11/R19/R21: golden raw ZAP fixture tests cover stable fingerprints, distinct routes/parameters/methods/rules, independent severity/confidence, masking and source pointers. PostgreSQL tests cover every observation, replay idempotency, baseline selection, changed/resolved/reopened state, partial/failed non-resolution, persistent dispositions, versioned review, role/project/tenant denial, CSRF, filter/pagination boundaries, immutable review rows and composite foreign keys. Migration tests include revision 0007 and schema drift.

R20: `findings.spec.ts` exercises URL filter persistence/reload, sorting, detail sections, masked HTTP evidence/provenance, reviewer state changes and comparison with explicitly synthetic HTTP boundary fixtures. Database/API integration tests independently verify production service behavior. See [PHASE9_TEST_REPORT](PHASE9_TEST_REPORT.md) for actual results and limitations.

## Phase 10 implemented verification

`test_ai.py` covers injection/secret/PII exclusion, deterministic input bounds, strict output schema, malformed/oversized responses, URL allowlisting, invented citations, root-cause labels, mock restrictions, SDK configuration, retry recovery and exhaustion. `test_ai_routes.py` covers real PostgreSQL retained versions, degraded failures without gate/finding mutation, cooldown, immutable analyses/feedback and tenant/project/role denial. Migration regression checks schema parity and downgrade/upgrade.

`AIGuidance.test.tsx` verifies inert XSS rendering for output/feedback, local-only checklists, citations, regeneration, feedback and viewer restrictions. The findings production-browser flow exercises generation, regeneration, retained versions, feedback, citations, XSS text, keyboard navigation, mobile/desktop overflow and axe accessibility. See [Phase 10 verification](PHASE10_TEST_REPORT.md) for exact outcomes and limitations.

Phase 10 strict review adds independently parameterized credential/PII cases, pre-truncation redaction boundaries, preservation of ordinary security guidance, whitespace/duplicate/hypothesis overflow and multibyte output rejection. Real SDK serialization tests cover STOP, MAX_TOKENS, SAFETY, 429 and 503 responses without live network calls; database tests exercise the actual three-attempt failure pipeline. Frontend tests reject stale feedback success notices. Browser inspection now includes 390, 768, 1280 and 1440px plus focus restoration after citations. Current review outcomes are in [TEST_REPORT](TEST_REPORT.md).

## Phase 11 implemented coverage

`test_policy_engine.py` table-tests every match field/operator, confidence/severity/status values, count boundaries, distinct finding aggregation, outcome precedence, missing baselines, expired exceptions, incomplete/demo scans, strict input rejection and deterministic replay. `test_policies.py` uses real PostgreSQL for immutable policy/activation/evaluation history, retained identical evaluations, actual changed advisory outputs, baseline history, exception approval and expiry, tenant/project/role denial, CSRF and bound scan failure evaluation. Existing migration roundtrip/schema drift and full API security regressions include revision 0009.

`Policies.test.tsx` checks developer controls and structured comma-list input. `policies.spec.ts` uses synthetic HTTP fixtures for publication, activation/deactivation, preview and appended history, with axe and overflow checks at 390/768/1440px. The policy service and pure evaluator are independently exercised against real database records. Actual commands, results and limitations are recorded in [PHASE11_TEST_REPORT](PHASE11_TEST_REPORT.md).

## Phase 12 additions

- Analytics: empty denominators, aware windows/timezones, complete/partial/failed populations, MTTR, project/target exclusion, chart/risk consistency, latest gate once per scan and invalid-duration accounting.
- Registries: tenant scope, administrative role denial, credential/hash withholding and cross-tenant revocation denial.
- HTTP: unauthenticated denial, foreign organization denial, validation errors and schema-validated empty dashboard.
- Frontend: empty/partial/stale/error/retry states, invalid MTTR omission, shared URL aggregate filters and CSV formula handling.
- Browser: dashboard/navigation as owner/developer/viewer; four dashboard visual widths, accessibility, overflow, URL filter, CSV and retry checks. Existing journey suites remain in place; actual results and live-service limitations are in [Phase 12 verification](PHASE12_TEST_REPORT.md).

- Live Phase 12 follow-up: owner dashboard/Team/Settings, identity, full configuration and real mock-worker SSE/cancellation scenarios passed across corrected runs. A regression test ensures detail headings remain present while loading and errors offer retry. See the final handoff report for exact results.

## Phase 13 verification

`apps/api/tests/test_reporting_access.py` covers PDF extraction, strict JSON snapshots, secret omission, immutable versioned snapshots, tenant denial, signed-link expiry/integrity, private write-once local/S3 storage settings, DNS/IP SSRF denial, exact-byte HMAC and redirects, encrypted destination binding, durable retry/dead-letter/manual retry, event deduplication, exception expiry notifications, and API-key one-time display/hash/scopes/expiry/revocation/rate limits over HTTP. PostgreSQL migration/schema regression remains in the full integration suite. `DeliveryTools.test.tsx` covers one-time secret dismissal and report success/error state. `e2e/reporting.spec.ts` exercises all three workspace forms with HTTP fixtures, mobile accessibility/overflow and desktop/mobile screenshots. Live third-party provider delivery is not part of these controlled tests.

## Phase 14 verification

`test_ci_client.py` covers pass/warn/fail/incomplete exits, network retry with stable keys, deadline and cancellation cleanup, redacted artifacts/job summaries, and bot-owned marker update-in-place. `test_github_integration.py` covers exact-byte signatures, unknown repositories, fork/base/action rejection, encrypted one-time secrets, atomic duplicate delivery/payload replay, frozen versions, real API-key creation/poll/cancel, deterministic retained result counts, and tenant/CSRF/deactivation denial. `GitHubIntegration.test.tsx` and `e2e/github.spec.ts` cover setup, secret dismissal, local readiness testing, disablement, delivery history and mobile/desktop accessibility. Real PostgreSQL migration and cumulative integration suites remain required; live GitHub publication is separate from controlled tests.
