# Phase 14 verification — 2026-09-22

Result: **PASS for implemented Phase 14 scope**. No subsequent phase was started. Live GitHub-hosted execution and real PR publication were not performed; controlled adapters, real PostgreSQL/Redis, Chromium and local build checks are distinguished below.

## Delivered files and behavior

- `.github/workflows/aegisforge-scan.yml` and `scripts/aegisforge_ci.py`: pinned reusable workflow, reviewed script checkout, organization-key authentication, frozen configuration, deterministic idempotency, retries, terminal polling, cancellation, configurable nonpassing exit codes, redacted JSON artifact, job summary and optional bot-owned comment update.
- `apps/api/src/aegis_api/ci.py`, `github.py`, `scans.py`, `main.py`, `db/models.py`, and migration `0011_github_integration.py`: typed CI contract, signed repository mappings, one-time encrypted webhook secrets, tenant-safe delivery receipts, atomic scan enqueue/replay and current authorization/version enforcement. The scan service exposes an internal transaction option so receipt and outbox commit together.
- `apps/web/src/product/GitHubIntegration.tsx` and `Registry.tsx`: copyable setup instructions, mapping/event/target/policy inputs, one-time secret dismissal, local connection readiness test, deactivation and delivery history. Existing reports, keys and notification controls remain functional.
- Backend CLI/webhook tests, schema/migration expectations, frontend tests and `e2e/github.spec.ts`; the existing reporting journey now selects the first of multiple integration forms. `Dockerfile.test` includes the standalone CLI for test discovery.
- README, `.env.example`, decisions, build plan, status, test matrix, generated schema/OpenAPI and [GITHUB_ACTIONS](GITHUB_ACTIONS.md) with complete push and pull-request examples.

## Exact verification commands and results

Workspace commands ran from `/home/akshat/Desktop/aegis-4th-year`. The bundled Node 24 runtime and existing Python 3.12 environment were used. Temporary tooling/cache stayed under `/tmp`. Network/socket/Docker/browser checks used approved escalation where sandbox restrictions prevented execution.

```sh
PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH \
  UV_CACHE_DIR=/tmp/aegis14-uv-cache make check build
```

Exit 0. Prettier, ESLint, Ruff lint/format, strict TypeScript and mypy passed. The Compose runner tests passed (2). Frontend: **46 tests passed** across 12 files. Backend non-integration: **373 passed, 8 skipped, 135 deselected**. The eight skips are the existing opt-in live ZAP tests; they are not counted as passed. Schema reproduction passed. Vite production assets and API source distribution/wheel built successfully. Two existing Starlette/AnyIO deprecation warnings remain.

The standalone client also passed:

```sh
apps/api/.venv/bin/ruff check scripts/aegisforge_ci.py
apps/api/.venv/bin/ruff format --check scripts/aegisforge_ci.py
apps/api/.venv/bin/pytest -c apps/api/pyproject.toml apps/api/tests/test_ci_client.py
```

Exit 0; **13 CLI tests passed**, including a child process receiving actual SIGTERM and requesting server cancellation. These 13 tests are also included in the backend total above.

Real services and test-image build:

```sh
docker compose -p aegisforge -f docker-compose.yml -f docker-compose.test.yml \
  run --rm --build api pytest -m integration tests/test_github_integration.py
```

Exit 0 for the initial webhook test; PostgreSQL and Redis were started under the fixed project. The built image was then used with current source mounted read-only to test the complete final suite without repeating dependency installation:

```sh
docker compose -p aegisforge -f docker-compose.yml -f docker-compose.test.yml \
  run --rm \
  -v "$PWD/apps/api/src:/app/src:ro" \
  -v "$PWD/apps/api/tests:/app/tests:ro" \
  -v "$PWD/apps/api/migrations:/app/migrations:ro" \
  -v "$PWD/scripts/aegisforge_ci.py:/app/scripts/aegisforge_ci.py:ro" \
  api pytest -m integration
```

Final exit 0: **135 passed, 381 deselected**, including five new database-backed GitHub/CI tests. Migration upgrade, repeat upgrade, downgrade to foundation, full downgrade/re-upgrade and Alembic metadata parity passed against a disposable test database. Cross-tenant foreign keys, session CSRF, organization-key CI submission/replay/cancellation, deterministic result counts, signature rejection, unsupported repositories, changed configuration and disabled mappings were exercised.

```sh
PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH \
  pnpm --filter @aegisforge/web test-e2e --project=production github.spec.ts reporting.spec.ts
```

Exit 0: **2 Chromium journeys passed**. The new journey checks setup, secret dismissal, readiness test, safe delivery history and disablement; existing report/key/notification controls also passed. Axe reported no violations and overflow assertions passed at 390 and 1440 pixels for GitHub setup; the existing reporting journey additionally covers 768 and 1280 pixels. Screenshots at `apps/web/test-results/github-GitHub-setup-secret-73b22-elivery-history-and-disable-production/github-{390,1440}.png` were visually inspected after secret dismissal. No stored secret appears in those screenshots. These browser journeys use controlled HTTP responses; database/API behavior is separately covered above.

```sh
/tmp/aegis14-actionlint/actionlint .github/workflows/aegisforge-scan.yml
git diff --check
```

Exit 0. actionlint 1.7.12 came from the official release and its archive matched published SHA-256 `8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8`. Official upstream `git ls-remote` verification confirmed checkout v4.2.2, upload-artifact v4.6.2 and download-artifact v4.3.0 commit pins. This validates workflow syntax and pins, not hosted GitHub execution.

After verification, services started for testing were stopped without deleting volumes:

```sh
docker compose -p aegisforge stop postgres redis
```

## Corrections during verification

Initial checks exposed two historical schema-test assumptions (table count and Phase 4 table exclusions), and migration/model foreign-key delete-action mismatch. All were corrected; the complete final migration/integration run passed. The failed downgrade assertion initially left only the disposable test database at its historical schema, causing cascading failures in that run; no application database was downgraded. A frontend test hook initially returned a mock function as cleanup; it now resets mocks without returning a callback. Sandbox socket/browser restrictions and an interrupted actionlint download were resolved with approved execution/retry. None of those initial failures are counted as passing results.

## Manual review and operational limits

Reviewed the workflow for secret placement, immutable action pins, trusted script revision, fork restrictions, job permissions and `always()` artifact handling. Inspected both setup screenshots and confirmed the one-time secret is absent after dismissal. Reviewed output projections: no evidence, titles, response bodies, headers, credentials or raw exception messages enter Actions artifacts, summaries or comments. Existing ZAP isolation/authorization and active confirmation controls remain in force.

The workflow requires a configured HTTPS API/application, an authorized passive target, active project gate, organization key and trusted caller workflow. Same-repository PR workflows require environment review/branch protections. GitHub validates nested job permission ceilings even when the optional comment job is skipped; the examples account for this. Comment execution itself is opt-in. No real GitHub comment, inbound public delivery, AWS operation or remote scanner run was sent during this phase. The workflow targets GitHub.com hosted Ubuntu runners; enterprise endpoints require reviewed adaptation.

Hard runner termination can prevent cancellation or artifact upload; the API's independent scan deadline remains the backstop. API idempotency receipts retain the existing 24-hour lifetime; webhook replay receipts remain retained with mappings. Mapping changes and webhook-secret rotation use disable/recreate. Connection tests distinguish local readiness from a real signed inbound ping. These boundaries are documented rather than reported as live-provider verification.

Git handoff uses the existing repository after final documentation checks; the final response records the commit result. The next phase requires a new explicit prompt. **Stop after Phase 14.**
