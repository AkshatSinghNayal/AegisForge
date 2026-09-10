# Phase 10 verification — 2026-09-10

This is the original implementation handoff. The subsequent strict review, corrected defects and current results are recorded in [TEST_REPORT](TEST_REPORT.md).

Phase 10 adds safe advisory enrichment and stops before policy evaluation or reporting. Phase 9 changes were already uncommitted when work began and were preserved. See [AI guidance](AI_GUIDANCE.md) for the input, schema, privacy, authorization and failure contracts.

## Results

| Check                                                           | Result                                                                                                                                           |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Initial focused backend/security/migration suite                | 49 passed                                                                                                                                        |
| Full backend regression against disposable PostgreSQL/Redis     | 314 passed, 8 opt-in live ZAP tests skipped; 2 existing upstream deprecation warnings                                                            |
| Final added timeout and HTTP CSRF/role cases                    | 46 passed; includes the added real deadline and HTTP CSRF/role cases                                                                             |
| Frontend Vitest/RTL                                             | 28 passed in 7 files                                                                                                                             |
| Production-browser findings/AI flow                             | 1 passed; generation, regeneration, retained versions, feedback, citations, checklist, XSS, keyboard navigation, mobile/desktop axe and overflow |
| Full configured browser regression                              | 57 passed, 6 live-service auth/configuration/scan browser cases skipped (not enabled in this run)                                                |
| Ruff, formatting, ESLint, strict TypeScript/mypy, schema parity | Passed: Prettier, Ruff/format, ESLint, strict TypeScript/mypy and schema check                                                                   |
| Vite production build                                           | Passed as part of browser run                                                                                                                    |
| API wheel/sdist build                                           | Passed: wheel and source distribution                                                                                                            |
| Live Gemini                                                     | Not run: no paid live-provider credentials or request needed for deterministic tests                                                             |

SDK resolution added official `google-genai==2.22.0` and compatible dependencies to `apps/api/uv.lock`. Its `<3` constraint follows Google's documented major-version boundary. Existing `websockets` resolved from 17.1 to SDK-compatible 16.1.1. No prerelease was installed. The installed SDK itself is exercised with a mocked transport boundary to verify structured schema, disabled tools, timeout and disabled nested retries.

## Exact commands

Host commands use bundled Node 24 via this prefix:

```sh
PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH
```

```sh
python3 -m pip install --target /tmp/aegis-phase10-tools uv==0.12.10
/tmp/aegis-phase10-tools/bin/uv add --project apps/api 'google-genai<3'
apps/api/.venv/bin/pytest -q apps/api/tests/test_ai.py
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
pnpm --filter @aegisforge/web test-e2e
/tmp/aegis-phase10-tools/bin/uv build --project apps/api --out-dir /tmp/aegis-phase10-dist
```

Disposable database/image verification (network/Docker/browser operations used approved sandbox escalation):

```sh
sg docker -c 'docker compose -p aegis-phase10-check -f docker-compose.yml -f docker-compose.test.yml run --rm --build api pytest -q tests/test_ai.py tests/test_ai_routes.py tests/test_database.py'
sg docker -c 'docker compose -p aegis-phase10-check -f docker-compose.yml -f docker-compose.test.yml run --rm -v /home/akshat/Desktop/aegis-4th-year/apps/api/src:/app/src:ro -v /home/akshat/Desktop/aegis-4th-year/apps/api/tests:/app/tests:ro -v /home/akshat/Desktop/aegis-4th-year/apps/api/migrations:/app/migrations:ro api pytest -q'
sg docker -c 'docker compose -p aegis-phase10-check -f docker-compose.yml -f docker-compose.test.yml run --rm -v /home/akshat/Desktop/aegis-4th-year/apps/api/src:/app/src:ro -v /home/akshat/Desktop/aegis-4th-year/apps/api/tests:/app/tests:ro api pytest -q tests/test_ai.py tests/test_ai_routes.py tests/test_findings.py'
```

The final focused run adds a real cancellation deadline test and HTTP-level AI generation/feedback CSRF and viewer denial to the already-passing full regression. No assertion replaces database authorization with a browser fixture.

## Manual and visual checks

Inspected Chromium's 390px and 1440px screenshots at `/tmp/phase10-guidance-390.png` and `/tmp/phase10-guidance-1440.png`. Generated guidance is bordered and labeled, separate from the Evidence tab. Citation IDs wrap, mobile controls remain usable, prior versions collapse, and hostile markup appears as literal text. The browser fixture deliberately bypasses backend rejection to test rendering defense in depth; this is synthetic HTTP-boundary data, not fabricated production analysis. No screen-reader session or non-Chromium certification is claimed.

## Changed files and limitations

Backend: `ai.py`, `ai_routes.py`, settings, main router, AI models/feedback, migration `0008_ai_guidance.py`, pyproject and lockfile. Frontend: `AIGuidance.tsx`, finding-tab integration and CSS. Tests: `test_ai.py`, `test_ai_routes.py`, findings HTTP/browser checks, schema/migration expectations and `AIGuidance.test.tsx`. Configuration/docs: Compose API settings, `.env.example`, README, decisions, phase status, build plan, test matrix, threat model, AI guidance guide, this report and generated schemas.

Generation is on demand, disabled by default and limited to classification-only input. No optional local model is bundled. Process termination before the synchronous request commits leaves no new analysis; old analyses/findings remain intact. No durable AI queue, retention cleanup, fleet billing quota or automatic training is implemented. Provider quality and live Gemini availability are not established by mock tests. Policy evaluation, reports and later phases are not implemented here. Next unblocked work requires a separate explicit phase prompt.

Initial local uv installation failed due sandbox DNS restrictions; approved retry succeeded. Initial Ruff/mypy checks caught formatting and a missing newly added SDK before dependency resolution; corrected before verification. These initial attempts are not counted as passing checks.

## Git and cleanup

`git diff --check` passed. The explicit `git add` attempt failed with exit 128: `Unable to create .../.git/index.lock: Read-only file system`. No commit was created; changes remain in the working tree. Protected Git metadata was not modified or escalated. No deployment or push was attempted.

```sh
git diff --check
git add -- apps/api/src/aegis_api/ai.py apps/api/src/aegis_api/ai_routes.py apps/api/migrations/versions/0008_ai_guidance.py apps/web/src/product/AIGuidance.tsx docs/AI_GUIDANCE.md
sg docker -c 'docker compose -p aegis-phase10-check -f docker-compose.yml -f docker-compose.test.yml down --volumes --remove-orphans'
```

Disposable-service cleanup passed (exit 0): only the Phase 10 test project’s containers, networks and volumes were removed.
