# Phase 13 implementation and verification

The subsequent [strict review](TEST_REPORT.md#phase-13-strict-review--2026-09-16) records additional fixes and supersedes the verification counts below.

Implemented migration 0010 and `reporting.py`, `report_jobs.py`, `notifications.py`, `api_keys.py`, `public_api.py`; registered API/job services; extended private persistence metadata and settings; added ReportSnapshot/OpenAPI contracts; added workspace `DeliveryTools` forms and report download controls; updated Compose storage/environment, dependency lock, README, decisions, build plan, phase status, test matrix and [operational guide](REPORTING_ACCESS.md). No later phase is included.

## Commands and actual results

Commands run from the repository root on 2026-09-12/13. Runtime selection uses the bundled Node and Python; uv 0.12.13 was installed under `/tmp/aegis-tooling` after a restricted-network failure and approved retry. New dependencies are locked in `apps/api/uv.lock`; no existing dependency versions were changed.

| Command                                                                                                                                                                     | Result                                                                                                                                                                                 |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/api/.venv/bin/pytest -c apps/api/pyproject.toml apps/api/tests/test_reporting_access.py -m 'not integration' -q`                                                      | Initial focused run: 14 passed; later focused additions recorded below                                                                                                                 |
| `sg docker -c 'docker compose -p aegisforge up -d --wait postgres redis'`                                                                                                   | Shared actual PostgreSQL and Redis healthy                                                                                                                                             |
| `sg docker -c 'docker compose -p aegisforge -f docker-compose.yml -f docker-compose.test.yml run --rm --build api pytest tests/test_reporting_access.py -m integration -q'` | 3 focused database/HTTP tests passed after fixing an overlong migration constraint name                                                                                                |
| Full backend command below                                                                                                                                                  | Final full run: **467 passed, 8 opt-in live ZAP tests deselected**, two upstream deprecation warnings; includes fresh migrations, roundtrip/schema parity and cross-tenant regressions |
| `pnpm --filter @aegisforge/web test`                                                                                                                                        | **43 passed**, including one-time key dismissal and report queue/error tests                                                                                                           |
| `pnpm --filter @aegisforge/web test-e2e --project=production reporting.spec.ts`                                                                                             | **1 passed**; new workflow covers report, notification and key forms, 390px overflow and axe                                                                                           |
| `apps/api/.venv/bin/ruff check apps/api` and strict `mypy`                                                                                                                  | Passed at implementation gate; final configured gate recorded below                                                                                                                    |
| `python3 scripts/check_compose.py`                                                                                                                                          | Dev/prod configuration and scanner isolation assertions passed; all repository Compose commands use `-p aegisforge`                                                                    |
| PDF generation, `pypdf` extraction, `/usr/bin/pdftoppm -scale-to 1300 -png ...`                                                                                             | PDF text/content verified and both initial sample pages visually inspected; no clipping/overlap. Bundled Poppler failed due to GLIBC mismatch; system Poppler succeeded                |

Full backend regression command (read-only source mounts keep the container on current workspace code):

```sh
sg docker -c 'docker compose -p aegisforge -f docker-compose.yml -f docker-compose.test.yml run --rm -v /home/akshat/Desktop/aegis-4th-year/apps/api/src:/app/src:ro -v /home/akshat/Desktop/aegis-4th-year/apps/api/tests:/app/tests:ro -v /home/akshat/Desktop/aegis-4th-year/apps/api/migrations:/app/migrations:ro api pytest -m "not zap_live" -q'
```

Configured quality/build gate:

```sh
PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH \
UV_CACHE_DIR=/tmp/aegis-uv-cache make check build UV=/tmp/aegis-tooling/bin/uv
```

A separate early local backend run ended with exit 143 before completion; it is not counted as passing. The complete container runs supersede it. Initial TypeScript checking caught a union response-schema inference mismatch, fixed with an explicit Zod union. Initial browser startup failed under the restricted sandbox; approved execution succeeded. No test failure or unavailable check is counted as a pass.

## Coverage and boundaries

Reports: strict schema, classification-only capture, secret fixture exclusion, PDF text, immutable database snapshot, regenerated versions, tenant denial, signed URL tampering/expiry, local integrity checks, private write-once file mode and S3 SSE-KMS/conditional writes. Notifications: encryption/tenant binding, exact HMAC bytes, private/mixed DNS rejection and rebinding, disabled redirect/proxy behavior, retries/backoff/dead-letter/manual retry, subscription deduplication, tenant-safe destination FKs and exception warning redaction. Keys: one-time response, hash-only storage, scopes, expiry/revocation/rate limit and separate session/public HTTP authentication.

Browser form tests use controlled HTTP fixtures; PostgreSQL/Redis authorization tests use real services. No live email, Slack message, GitHub comment, generic webhook or AWS operation occurred. No new ZAP/Gemini invocation was made. The seven opt-in existing live-service browser journeys are excluded from the normal browser run. At-least-once delivery can duplicate an externally accepted message after a crash; receivers should deduplicate delivery IDs. Bucket lifecycle must reclaim S3 orphan/noncurrent objects. Local crash-orphaned objects may require operator cleanup; ordinary recorded report expiry is automated. Large-scale throughput and external provider availability are not certified.

## Final verification and handoff

Final focused database/security suite: **26 passed** after adding translated IPv6/cloud-platform SSRF denial and the legacy-evaluation nonpassing guard. The final configured `make check build` completed with exit 0 outside the sandbox: Prettier, ESLint, Ruff/format, TypeScript, mypy (49 modules), two Compose runner checks, **43 frontend tests**, **344 backend unit tests** (8 opt-in live ZAP skipped, 127 integration cases excluded), generated schema parity, Vite production output and API wheel/sdist all passed. The earlier full container run passed **467 tests** before the final three IP cases and one legacy-gate case; the final focused suite covers those additions. Counts from different runs are not added together.

The normal browser reporter completed **62 passed / 7 opt-in skips** in eight minutes, but its parent command received SIGTERM and exited 143; this is disclosed rather than recorded as a clean command exit. The final changed reporting/notification/key workflow rerun exited 0 with **1 passed**. Both final 390px/1440px notification screenshots and both final sample PDF pages were visually inspected. The narrow registry table now scrolls as a table instead of splitting column labels into individual syllables. Axe and document overflow checks passed.

The first combined quality attempt had three frontend timing/loading failures under concurrent browser/image work; the separate rerun and final configured gate both passed all 43 tests without changing their timeouts. The local TestClient stage stalled in the sandbox; the same individual test passed outside it in 3.24 seconds, and the full approved gate then completed. The stalled sandbox run was interrupted (exit 130), not counted as a pass.

The production API image built successfully and a non-root temporary report-volume write/read/delete check passed. The initially empty report volume created by the test container needed ownership initialized to UID/GID 10001. Test Compose now uses `aegisforge-api-test` and resets storage mounts, so tests neither overwrite the production image tag nor initialize its report volume. Fresh setup was checked in a temporary directory: new keys are generated, `.env` has mode 0600 and rerunning preserves its bytes. Existing project `.env` was not changed.

All development/production Compose configuration and scanner-isolation assertions, final schema parity and `git diff --check` passed. No push, deployment, external notification or AWS request occurred. Git handoff and shared-stack cleanup are recorded below. Stop after Phase 13; Phase 14 requires a separate explicit prompt.

### Git handoff blocker

Ordinary `git add .env.example README.md apps scripts/setup_env.py docker-compose.yml docker-compose.prod.yml docker-compose.test.yml docs` failed with exit 128: `.git/index.lock` cannot be created on the read-only filesystem. The explicit escalation attempt was **rejected by automatic approval review**, which stated that although staging is bounded and authorized, Git metadata is explicitly read-only and AGENTS.md requires disclosing the blocker without modifying protected metadata. No workaround, ownership/permission change, staging, commit or push was performed. The verified files remain in the working tree. A Git-only exception to that restriction requires explicit user authorization before retrying.

The final production API image rebuild completed successfully after all source changes. Shared-stack cleanup uses `docker compose -p aegisforge down` without `-v`; report and existing data volumes remain retained.
