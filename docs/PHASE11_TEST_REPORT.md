# Phase 11 verification — 2026-09-11

Scope: versioned deterministic project policies, structured builder, accepted-risk exceptions, scan binding, preview, immutable evaluations and role/tenant/security coverage. No subsequent phase was started.

## Implementation files and decisions

- `apps/api/src/aegis_api/policy_engine.py`: closed validated schemas and pure evaluator.
- `policy_service.py`, `policies.py`: safe input capture, project policy publication/activation, preview, append-only evaluation and audit.
- `db/models.py`, `db/enums.py`, migration `0009_deterministic_policies.py`: version/history records, tenant foreign keys, immutable triggers, incomplete outcome and AI-independent passing guard.
- `scans.py`, `scan_lifecycle.py`, `zap_dispatch.py`, `finding_service.py`: captured project policy, gate-bound active confirmation, terminal evaluation, scan result display and baseline preservation.
- `apps/web/src/product/Policies.tsx`, workspace/navigation, scan detail and product CSS: structured builder, read access, publication/activation, historical previews and retained input/match detail.
- Backend rule/service/security tests, frontend unit/browser tests, generated OpenAPI/schema, README, configuration comments, build plan, decisions, status and test matrix.

See [POLICY_ENGINE](POLICY_ENGINE.md) for semantics, API paths, exception approval, immutable replay and migration behavior. No dependencies or secrets were added; existing lockfiles remain unchanged.

## Commands and results

This host's default Node is too old for the pinned frontend dependencies. Verification uses Node 24 from `/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin`, Python 3.12 from `apps/api/.venv`, and uv from `/tmp/aegis-phase10-tools/bin`. The disposable PostgreSQL and Redis containers bind only to loopback ports 55439 and 56389. Tests create and drop a separate database; no application database is migrated or cleared.

```sh
PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/tmp/aegis-phase10-tools/bin:$PATH UV_CACHE_DIR=/tmp/aegis-uv-cache make check build

AEGIS_PROFILE=test AEGIS_DATABASE_URL="$PHASE11_TEST_DATABASE_URL" AEGIS_REDIS_URL=redis://127.0.0.1:56389/0 apps/api/.venv/bin/pytest -c apps/api/pyproject.toml apps/api/tests -m integration -q

PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH pnpm --filter @aegisforge/web exec playwright test --project=production --project=labs
```

`PHASE11_TEST_DATABASE_URL` denotes the disposable loopback test credentials, omitted here. Actual command output is retained in `/tmp/phase11-check-build.log`, `/tmp/phase11-integration-verified.log` and `/tmp/phase11-browser.log` during this workspace session.

| Check                                                               | Result                                                                                                                      |
| ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Prettier, ESLint, Ruff lint/format                                  | Passed                                                                                                                      |
| Strict TypeScript and mypy                                          | Passed; 42 Python source files                                                                                              |
| Frontend unit tests                                                 | 31 passed                                                                                                                   |
| Backend unit/security tests                                         | 320 passed; 8 opt-in live ZAP cases skipped                                                                                 |
| Pure policy matrix                                                  | 68 passed, included in the backend total                                                                                    |
| Full API/database integration, migration roundtrip and schema drift | 109 passed; final focused policy suite 79 passed (68 pure + 11 integration)                                                 |
| Production and laboratory Chromium regression                       | 57 passed initially; the one timed-out public-layout test passed in isolation. Final policy evidence/history test: 1 passed |
| Production frontend/API package builds                              | Vite production build and API sdist/wheel passed                                                                            |

The final complete integration run passed 109 tests, including an explicit active-confirmation gate-version change case. The final focused policy run passed 79 tests after the captured-environment and timestamp refinements. Existing regression expectations were updated from fail to incomplete for scans without a configured gate, matching the new four-outcome contract. The pass-guard test now marks its complete scanner fixture as non-demo; demo scans are rejected at the database boundary.

## Problems found and corrected

- PostgreSQL's generated foreign-key name exceeds the literal identifier length: migration downgrade now uses Alembic's finalized naming convention. Upgrade/downgrade/re-upgrade and metadata parity passed in the 108-test run.
- The old evaluation guard required complete AI enrichment. The new engine/database guard uses scanner completeness, while actual differing synthetic AI outputs and all enrichment states leave decisions unchanged. Identical captured times produce identical digests across changed AI output.
- A schema-catalog test needed the two new history tables counted. A memory-only scan fixture exposed absent configuration on terminal transitions; absent gates are safely ignored when recording bound evaluations.
- Early frontend tests used Node 20 and could not start jsdom workers; the required Node 24 run passed. An early restricted backend run could not finish local-socket cases; the full authorized local-socket run passed.
- Visual inspection found cramped checkbox/button spacing in the initial builder. Added responsive layout, labeled 44px checkbox rows, separate rule sections and readable evidence/history panels.
- The combined browser run had one public-layout timeout during concurrent build verification. Shared distribution updates were a possible contributor. Both the isolated public-layout retry and final policy/evidence browser test passed with stable served assets.
- Legacy historical scans can lack an environment snapshot. Environment-constrained policies fail closed/incomplete rather than substitute the current target environment.

## Manual and automated browser review

The production fixture journey publishes a structured policy, activates it, previews a historical scan, saves two separate evaluations and deactivates the policy. It inspects contributing finding/occurrence IDs and retained snapshots. Axe WCAG A/AA and horizontal overflow checks run at 390, 768 and 1440px. Unit coverage verifies developer read-only controls and multi-value input preservation. Browser API responses are explicitly synthetic; real database/API tests separately verify authorization, schema validation and persistence. No production scan or external notification is executed.

## Limitations and handoff

- Eight opt-in real ZAP tests are skipped, not claimed as passed. This phase does not change ZAP execution/egress mechanisms and does not run scans against external targets.
- Existing upstream Starlette/httpx and AnyIO deprecation warnings remain; they do not fail tests.
- Local production packages are built; no deployment or new live Docker application build is claimed. Browser journeys use Chromium only; no direct screen-reader certification is claimed.
- Published policies and approved exceptions are immutable. Preview requires a published project version. Re-evaluation captures current review state/time; exact replay uses the retained snapshot.
- No gate is activated automatically on existing projects. Apply migration `0009`, publish and explicitly activate a project gate before expecting automatic real-scan evaluations. Legacy environment-constrained previews may be incomplete.
- Reporting, CI integration and deployment remain deferred. The next phase requires an explicit user prompt.

The disposable PostgreSQL and Redis containers were stopped and removed after verification. No application services or stored development data were changed. All 58 production/laboratory cases passed across the main run and isolated retry. The final policy-specific run also passed. The phase commit includes this report; no push or deployment was requested.

Final focused verification commands:

```sh
apps/api/.venv/bin/pytest -c apps/api/pyproject.toml apps/api/tests/test_policies.py apps/api/tests/test_policy_engine.py -q
pnpm --filter @aegisforge/web exec playwright test --project=production policies.spec.ts
pnpm --filter @aegisforge/web exec playwright test --project=production marketing.spec.ts --grep 'public layout at 1920'
```

These use the same Node/database environment described above. Focused policy output is retained in `/tmp/phase11-policy-final.log` and `/tmp/phase11-policy-browser-final.log`; the public-layout rerun is in `/tmp/phase11-browser-retry.log`.
