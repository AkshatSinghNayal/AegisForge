# Phase 9 verification — 2026-09-10

Scope: versioned ZAP normalization, immutable raw evidence, per-observation provenance, comparable-scan lifecycle, audited reviewer mutations, finding APIs and findings UI. No later phase was implemented.

## Results

| Check                                                                        | Result                                                                                                                                                                                     |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Full backend suite with disposable PostgreSQL/Redis                          | **275 passed, 8 skipped** in 154.44s. Skips are opt-in live ZAP tests, not passes.                                                                                                         |
| Focused normalization, findings, migrations, scanner handoff and conventions | **50 passed** in 48.30s. Includes HTTP filtering/pagination, all four roles, CSRF, cross-tenant denial, immutable history, duplicate observations and partial-scan baselines.              |
| Additional real collection → normalization → non-passing gate integration    | **1 passed** in 6.61s.                                                                                                                                                                     |
| Frontend unit regression                                                     | **25 passed** in 14.54s on the clean rerun.                                                                                                                                                |
| Playwright findings journey                                                  | **1 passed** in 25.2s after the final keyboard-tab refinement. Includes URL filter reload, sorting, review mutation, evidence sources, comparison, mobile/desktop axe and overflow checks. |
| Ruff lint/format                                                             | Passed; 64 Python files formatted.                                                                                                                                                         |
| Strict mypy                                                                  | Passed; 37 source files.                                                                                                                                                                   |
| ESLint / strict TypeScript                                                   | Passed.                                                                                                                                                                                    |
| API source distribution and wheel                                            | Both built successfully with the container's configured `uv build`.                                                                                                                        |
| Vite production build                                                        | Passed as part of the browser production web-server build.                                                                                                                                 |
| Generated OpenAPI/convention/database catalog                                | Regenerated and schema drift check passed.                                                                                                                                                 |
| Prettier / Git whitespace                                                    | Passed; `git diff --check` passed.                                                                                                                                                         |

The final query-parameter whitespace regression and golden normalization suite passed **21 tests** in 1.07s after the complete backend run. Header names normalize case/whitespace; query/body parameter names retain meaningful whitespace. Strict mypy passed again after this final refinement.

## Exact commands

Host frontend commands used Node 24 from `/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin` prepended to PATH. Host Python tools used the existing `apps/api/.venv`. `sg docker` activates the account's existing Docker group; no group/permission settings were changed. The host lacks a standalone `uv`, so the configured Python check commands ran directly and the package build used the existing Docker runtime.

```sh
apps/api/.venv/bin/pytest -c apps/api/pyproject.toml apps/api/tests/test_normalization.py -q
apps/api/.venv/bin/ruff check apps/api
apps/api/.venv/bin/ruff format --check apps/api
apps/api/.venv/bin/mypy --config-file apps/api/pyproject.toml apps/api/src
apps/api/.venv/bin/python -m aegis_api.schema_docs
apps/api/.venv/bin/python -m aegis_api.schema_docs --check
pnpm exec prettier --check .
pnpm --filter @aegisforge/web lint
pnpm --filter @aegisforge/web typecheck
pnpm --filter @aegisforge/web test
pnpm --filter @aegisforge/web test-e2e --project=production findings.spec.ts
```

Initial disposable image build and focused migration test:

```sh
sg docker -c 'docker compose -p aegis-phase9-check -f docker-compose.yml -f docker-compose.test.yml run --rm --build api pytest -q tests/test_findings.py tests/test_database.py'
```

Final full suite, with current source/test/migration files mounted read-only:

```sh
sg docker -c 'docker compose -p aegis-phase9-check -f docker-compose.yml -f docker-compose.test.yml run --rm -v /home/akshat/Desktop/aegis-4th-year/apps/api/src:/app/src:ro -v /home/akshat/Desktop/aegis-4th-year/apps/api/tests:/app/tests:ro -v /home/akshat/Desktop/aegis-4th-year/apps/api/migrations:/app/migrations:ro api pytest -q'
```

The focused run used the same command with `tests/test_findings.py tests/test_normalization.py tests/test_database.py tests/test_zap_dispatch.py tests/test_conventions.py` after `pytest -q`. The final extra handoff case used `tests/test_findings.py::test_real_collection_connects_normalization_without_passing_gate`.

```sh
sg docker -c 'docker compose -p aegis-phase9-check -f docker-compose.yml -f docker-compose.test.yml run --rm -v /home/akshat/Desktop/aegis-4th-year/apps/api/src:/app/src:ro api uv build --out-dir /tmp/phase9-dist'
git diff --check
```

## Failures resolved during implementation

The first database run passed 14 tests and failed a new test that incorrectly used `APIError.status_code`; the correct attribute is `status`. The initial full backend suite passed 270 tests and failed an old hardcoded schema table count; the count now includes `finding_reviews`. Subsequent full regression passed. Existing Starlette/httpx and AnyIO deprecation warnings remain upstream warnings.

The first browser run reached the findings table but timed out using an exact `getByLabel` selector. The test now uses the combobox role/name. ESLint caught synchronous state clearing in a React effect; the view now resets through a URL/organization component key. Strict mypy caught reuse of a query-column variable for a CASE expression; the sort expression has its own variable. Visual inspection caught a workspace navigation CSS rule overriding tab layout; the findings selector now has the needed specificity.

An initial host backend run was interrupted after stalling in sandboxed service/network tests; its partial output is not counted. The complete suite ran successfully against disposable Docker services. A frontend unit run under concurrent build/test load passed 24 tests and timed out in the existing configuration-wizard test at its 5-second limit; its clean rerun passed all 25 tests in 14.54s. No timeout threshold was relaxed.

## Visual and manual review

Inspected mobile (390px) and desktop (1440px) evidence screenshots generated by Chromium. Evidence stacks on mobile and appears side by side on desktop, with bounded wrapping/scrolling, explicit masking and provenance. Final screenshots are `/tmp/phase9-evidence-390.png` and `/tmp/phase9-evidence-1440.png`. Playwright checks axe violations and horizontal overflow at both widths, plus tab keyboard navigation. No screen-reader session, non-Chromium certification or real live ZAP execution is claimed.

Browser data is explicitly synthetic HTTP-boundary test data. Production ingestion, authorization, review, storage constraints and migration behavior are independently tested against real PostgreSQL/Redis. No demo observations or responses were added to production paths.

## Changed files

- Backend: `normalization.py`, `finding_service.py`, `findings.py`, `db/models.py`, `db/enums.py`, `main.py`, `scan_lifecycle.py`, `zap/artifacts.py`, `zap/contracts.py`, `zap_dispatch.py`, migration `0007_finding_normalization.py`.
- Frontend: `product/Findings.tsx`, `product/Workspace.tsx`, `product/product.css`, `playwright.config.ts`.
- Tests: golden `fixtures/zap-normalization-v1.json`, `test_normalization.py`, `test_findings.py`, updated migration/schema assertions, `e2e/findings.spec.ts`.
- Documentation/configuration: README, `.env.example` comments, normalization guide, decisions, build plan, phase status, test matrix, this report and generated schema/API catalog.

## Boundaries and handoff

See [FINDING_NORMALIZATION](FINDING_NORMALIZATION.md) for the fingerprint contract, conservative comparison rules, masking, API usage and migration limitations. Historical raw artifacts are not backfilled. Complete evidence does not mean AI/policy/report availability; no passing gate is fabricated. Reference categories are scanner-supplied. Restricted bodies remain encrypted and withheld from ordinary excerpts.

No dependency upgrades or new runtime configuration were introduced. Migration `0007` supports empty-feature downgrade/re-upgrade and refuses to discard retained Phase 9 evidence. The next phase remains subject to a separate explicit prompt. Stop after Phase 9.

## Git handoff

`git add -- .env.example README.md apps/api apps/web docs` failed with exit 128: `Unable to create .../.git/index.lock: Read-only file system`. No commit was created, and protected Git metadata was not modified. The verified changes remain in the working tree. No push or deployment was attempted.

Cleanup command (only the disposable verification project):

```sh
sg docker -c 'docker compose -p aegis-phase9-check -f docker-compose.yml -f docker-compose.test.yml down --volumes --remove-orphans'
```

Final API package rebuild and disposable-project cleanup both completed successfully (exit 0). Test containers, networks and volumes were removed. Final Prettier and Git whitespace checks passed.
