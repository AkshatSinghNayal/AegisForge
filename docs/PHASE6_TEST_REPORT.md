# Phase 6 verification — 2026-09-07

Scope: projects, target registration/validation, secret references, immutable scan policies and authenticated UI. No ZAP process or scan job ran. No later application phase was implemented.

## Final results

| Gate                                                    | Result                                                                                                                                                            |
| ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Prettier, ESLint, Ruff and Ruff formatting              | Passed                                                                                                                                                            |
| Strict TypeScript and mypy                              | Passed; 22 backend source modules                                                                                                                                 |
| Generated schema consistency                            | Passed                                                                                                                                                            |
| Frontend Vitest/RTL                                     | 21 passed, including the deferred wizard-state regression                                                                                                         |
| Backend full pytest against disposable PostgreSQL/Redis | 142 passed: 83 unit/security and 59 integration tests; two existing upstream deprecation warnings                                                                 |
| Migrations                                              | Fresh upgrade, repeated upgrade, downgrade/re-upgrade, retained-data round trip and Alembic metadata drift checks passed in the backend suite                     |
| Production web/API artifacts                            | Vite build and API sdist/wheel passed; API package rebuilt after the final network guard                                                                          |
| Real-backend Playwright auth/configuration              | 5 passed, including full project/policy/OpenAPI/credential/archive/restore setup                                                                                  |
| Existing Playwright public/health/lab regression        | 56 passed; 5 backend-dependent cases skipped here and passed separately above                                                                                     |
| Compose configuration and isolation assertions          | Dev/prod passed; scanner remains opt-in, pinned and disconnected                                                                                                  |
| Environment helpers                                     | New key generation, existing-key preservation, missing-key addition, other-entry preservation, second-run stability and mode 0600 passed in a temporary directory |
| Visual review                                           | Viewed desktop target and 390px project screenshots; no clipping or horizontal overflow observed. Desktop target and mobile project axe checks passed.            |
| Git whitespace check                                    | `git diff --check` passed                                                                                                                                         |

## Exact commands

This environment uses the bundled Node runtime and uv/pnpm tooling; ordinary developer machines use the Make targets directly. Docker access required the user's existing `docker` group via `sg`. An initial direct Docker call was denied by the socket; no permission or daemon configuration was changed. One automated approval review timed out and succeeded on retry. A sandboxed Python TestClient run stalled; the complete rerun with process permissions passed.

```sh
PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/tmp/aegis-tools:$PATH UV_CACHE_DIR=/tmp/aegis-uv-cache make lint typecheck schema-check
PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/tmp/aegis-tools:$PATH UV_CACHE_DIR=/tmp/aegis-uv-cache make test build
PATH=/tmp/aegis-tools:$PATH UV_CACHE_DIR=/tmp/aegis-uv-cache uv run --project apps/api pytest -c apps/api/pyproject.toml apps/api/tests/test_configuration.py -m 'not integration' -q
PATH=/tmp/aegis-tools:$PATH UV_CACHE_DIR=/tmp/aegis-uv-cache uv build --project apps/api
sg docker -c '/tmp/aegis-tools/docker-compose -p aegis-phase6 -f docker-compose.yml -f docker-compose.test.yml run --rm --build api'
sg docker -c '/tmp/aegis-tools/docker-compose -p aegis-phase6 -f docker-compose.yml -f docker-compose.test.yml run --rm --no-deps -v /home/akshat/Desktop/aegis-4th-year/apps/api/src:/app/src:ro -v /home/akshat/Desktop/aegis-4th-year/apps/api/tests:/app/tests:ro api pytest'
sg docker -c 'PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/tmp/aegis-tools:$PATH COMPOSE=/tmp/aegis-tools/docker-compose make test-auth-e2e'
PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/tmp/aegis-tools:$PATH make test-e2e
COMPOSE=/tmp/aegis-tools/docker-compose python3 scripts/check_compose.py
sg docker -c '/tmp/aegis-tools/docker-compose -p aegis-phase6 -f docker-compose.yml -f docker-compose.test.yml down --volumes --remove-orphans'
git diff --check
```

The full backend command uses read-only source/test mounts over the already built image to verify final source with the locked dependencies. Its final result was **142 passed in 49.11 seconds**. The final focused network/configuration run was **67 passed, 9 integration cases deselected**. The earlier local unit gate had 80 passing tests; three additional special-address cases were subsequently included in the final full backend run. Do not add these overlapping counts together.

Initial checks caught the API version assertion needing its Phase 6 update, a deferred React form-event bug (fixed and regression-tested), and Playwright label locators that included select options/populated textarea content (replaced with accessible-role locators). A sanitizer test added real response descriptions to verify that required OpenAPI descriptions survive as fixed sanitized text. IPv6 metadata, translation and deprecated site-local guards were tightened during review. Those failed/intermediate runs are superseded by the final results above.

## Artifacts, decisions and limits

Backend files: migration `0004_phase6_configuration.py`; `configuration.py`, `configuration_schemas.py`, `target_validation.py`, `secret_store.py`, `body_limit.py`; extensions to models/settings/main; stable dependencies and uv.lock; configuration tests and updated version expectation. Frontend files: `Configuration.tsx`, its regression test, workspace navigation/onboarding links, product CSS, Playwright setup test/configuration. Infrastructure/tooling: local key generation/helper, Compose key forwarding, disposable browser fixture and runner. Documentation: README, CONFIGURATION, ADR-024, build/test matrices, generated OpenAPI/database schema and phase status.

Key decisions: reuse Phase 5 RBAC; project deletion archives; policies append immutable versions; validate every hop with DNS pinning and verified TLS; private RFC1918/ULA requires administrator declaration and registration; metadata/loopback/special ranges stay blocked; OpenAPI is bounded and sanitized; local secrets use context-bound authenticated encryption; only masked metadata is returned. See [CONFIGURATION](CONFIGURATION.md) for the exact compatibility restrictions and [DECISIONS](DECISIONS.md) for rationale and primary documentation.

Screenshots inspected: `/tmp/aegis-phase6-target.png` and `/tmp/aegis-phase6-project-mobile.png`. These are review artifacts, not committed screenshot baselines. No direct screen-reader session, non-Chromium certification, remote CI run, production managed-secret provider, active scanner, executor egress validation or deterministic gate evaluation is claimed. Configuration lists currently return at most 200 records; counts/recent scans cover all project targets. Local encryption requires the configured stable key and is refused in production. OAuth remains an explicit future interface.

The browser runner removed its disposable containers and volumes; the integration stack was also removed with the command above. Existing application volumes were not touched. Next unblocked work is the next explicitly requested phase, with isolated scan execution still requiring current ownership, network/scope enforcement and one-use active confirmation. Phase 6 does not authorize it.

Git commit blocked: `git add` failed with exit 128 because `.git/index.lock` could not be created on the read-only protected Git metadata. No commit was created and no Git permissions or protected metadata were modified.

## Subsequent strict review — 2026-09-08

The original results above are historical. The subsequent strict review fixes OpenAPI sanitization/prevalidation, archived-project revocation, stale target display, fragmented upload buffering, legacy-policy compatibility and primary-button hover contrast. Its expanded failure-path tests and 52 four-width UI checks are recorded in [TEST_REPORT](TEST_REPORT.md#phase-6-strict-review--2026-09-08); see [PHASE_STATUS](PHASE_STATUS.md) for the latest verdict.
