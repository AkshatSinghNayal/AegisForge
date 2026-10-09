# Phase 15 verification — 2026-10-10

Only administration and audit controls were implemented. Existing uncommitted local-scanner work was preserved. See [ADMINISTRATION](ADMINISTRATION.md) for operating procedures and limitations.

## Changes

New administration, control, audit, network-policy and maintenance modules extend current membership locks and scan admission. Migration 0012 adds organization control settings, audit result/optional direct peer IP and immutable per-object purge receipts. Existing scan, ZAP, report, notification and membership services enforce or audit these controls. The authenticated administration UI, team/policy controls, route aliases, environment switches, generated schemas and database permission SQL are included.

Failed scans require a fresh authorized submission; active consent cannot be reused. Retention preserves provenance and records file deletion separately. Operator switches cannot be overridden by tenants. Hash chaining is documented as optional defense in depth, not enabled.

## Verification

Frontend commands use bundled Node 24:

```sh
export PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH
```

| Command                                                                                   | Result                                                                                         |
| ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `apps/api/.venv/bin/ruff check apps/api`                                                  | PASS                                                                                           |
| `apps/api/.venv/bin/ruff format --check apps/api`                                         | PASS, 101 files                                                                                |
| `apps/api/.venv/bin/mypy --config-file apps/api/pyproject.toml apps/api/src`              | PASS, 56 source files                                                                          |
| `apps/api/.venv/bin/python -m aegis_api.schema_docs --check`                              | PASS                                                                                           |
| `pnpm exec prettier --check .`                                                            | PASS, including final documentation                                                            |
| `pnpm --filter @aegisforge/web lint`                                                      | PASS                                                                                           |
| `pnpm --filter @aegisforge/web typecheck`                                                 | PASS                                                                                           |
| `apps/api/.venv/bin/pytest -q apps/api/tests -m 'not integration' --maxfail=1`            | PASS: 396 tests, 8 opt-in live ZAP tests skipped                                               |
| `pnpm --filter @aegisforge/web test`                                                      | PASS: 46 tests in 12 files                                                                     |
| `python3 scripts/test_compose_runner.py`                                                  | PASS: 2 tests                                                                                  |
| Full PostgreSQL/Redis integration suite below                                             | PASS: 154 tests, including migration roundtrips                                                |
| `apps/api/.venv/bin/pytest -q apps/api/tests/test_administration.py -m 'not integration'` | PASS: 7 tests after descriptor-relative retention hardening                                    |
| Browser command below                                                                     | PASS after final layout improvement: 1 journey; zero axe violations/overflow at 390/768/1280px |
| Web production build via Playwright webServer                                             | PASS: TypeScript, Vite and SEO generation                                                      |
| API build below                                                                           | PASS: wheel and source distribution                                                            |

Exact full integration command (run after `docker compose -p aegisforge up -d --wait postgres redis`):

```sh
docker compose -p aegisforge -f docker-compose.yml -f docker-compose.test.yml run --rm \
  -v /home/akshat/Desktop/aegis-4th-year/apps/api/src:/app/src:ro \
  -v /home/akshat/Desktop/aegis-4th-year/apps/api/tests:/app/tests:ro \
  -v /home/akshat/Desktop/aegis-4th-year/apps/api/migrations:/app/migrations:ro \
  api pytest -q -m integration --maxfail=1
```

The final focused DB rerun uses the same command with `pytest -q tests/test_administration.py -m integration`. The browser command is `pnpm --filter @aegisforge/web exec playwright test administration --project=production`.

API build:

```sh
docker compose -p aegisforge -f docker-compose.yml -f docker-compose.test.yml run --rm \
  -v /home/akshat/Desktop/aegis-4th-year/apps/api/src:/app/src:ro api uv build
```

## Corrections and manual review

Sandboxed HTTP/socket fixtures could not run; approved loopback-enabled execution passed the backend suite. System Node 20 could not start jsdom; bundled Node 24 passed all frontend tests. Migration tests needed the added table in their catalog/downgrade expectations. New failed-scan and expired-session fixtures initially violated existing completeness/expiry constraints; fixtures were corrected without relaxing those constraints. Browser testing caught the shared Button default preventing Save submission; Save and Filter now explicitly submit.

Desktop/mobile screenshots were inspected. The initial journey passed axe and overflow checks at 390/768/1280px; visual review improved navigation and checkbox alignment. The six-request admission race uses independent DB transactions and requires one 202 and five 429 responses. Tests cover policy deactivation, cross-tenant denial, session revocation, credential cleanup, retained artifact metadata, secret-free audit summaries and rejected audit TRUNCATE.

## Limits

Browser responses are synthetic fixtures. No live ZAP, paid Gemini, S3 retention, external notification, production role installation or scheduler deployment was exercised. Status explicitly distinguishes configuration from live availability. Apply restricted role grants with a non-owner/non-superuser production identity. Raw maintenance requires the actual artifact volume and a trusted process; scanner workers retain no database access. Environment switches require all API processes to reload and do not cancel dispatched jobs. Existing local-scanner changes remain separate.

A final verification command was initially rejected by automatic approval review because the account usage limit had been reached. Work resumed after the user's explicit continuation. No approval workaround was used.

No later phase is started; the next phase requires an explicit prompt.

## Final verification and handoff

The final administration database rerun passed **9 tests** after descriptor-relative retention hardening. The final browser rerun passed **1 journey** and rebuilt production assets; mobile and desktop screenshots were inspected. Final Ruff, formatting, mypy, schema drift, Prettier and ESLint checks passed. `python3 scripts/test_local_scanner.py` also passed all 3 existing regression tests with approved socket access. Existing local-scanner changes were preserved outside the Phase 15 commit.
