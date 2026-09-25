# Phase 14 strict review — 2026-09-25

**CONDITIONAL PASS — safe to begin the next explicitly requested phase.** Five confirmed blockers were reproduced, fixed and regression-tested. No next-phase work was started. This review supersedes the original [Phase 14 handoff](PHASE14_TEST_REPORT.md); historical reports below remain unchanged.

## Confirmed defects fixed

- **CI replay context:** the server fingerprint covered the generic scan input but omitted CI project/environment/gate context. Reusing a key after activating a new gate returned the old scan. Fingerprint the complete validated CI submission; the regression now gets 409 instead of 202.
- **Delivery conflict precedence:** an OR query could return a matching payload receipt before a conflicting delivery-ID receipt. Check the scoped delivery ID first, then payload/event deduplication. A PostgreSQL regression exercises an alternate legal query plan and now rejects the conflicting ID with 409.
- **Total network deadline:** socket inactivity timeouts allowed slow connection setup or a continuously trickling body to exceed the configured deadline. A POSIX interval timer bounds each request by the remaining total deadline. Tests cover blocked open/read, a real local HTTP server trickling bytes, and signal cancellation.
- **Contradictory job summaries:** every poll appended another heading and verdict. Replace the step summary with its latest bounded snapshot; the three-poll regression now leaves exactly one final heading/verdict.
- **Malformed passing response:** the CLI accepted pass/warn with absent evidence counts. Reject these responses and retain the conservative incomplete result.

Additional failure tests cover missing/wrong signatures, missing/invalid delivery IDs, unsupported event types, expired target authorization, demoted mapping creators and inactive organizations. They assert no scan is enqueued and synthetic credentials/body canaries are absent from responses and captured logs. Existing coverage checks unsupported repositories, arbitrary webhook URLs, cross-tenant mappings, duplicate deliveries, policy/version binding, pass/warn/fail/incomplete, retries, timeout, actual SIGTERM, and owned-marker PR comment updates/redaction. No new schema, dependencies or environment settings were introduced.

## Commands and actual results

Commands ran from the repository root. Node/pnpm used `PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH`; uv used `UV_CACHE_DIR=/tmp/aegis14-review-uv-cache`.

| Command                                                                                                                                                                                                                                                                                                           | Result                                                                                                                                                                                                                                                                         |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `make check build`                                                                                                                                                                                                                                                                                                | PASS: Prettier, ESLint, Ruff lint/format, TypeScript, mypy (51 files), schema-doc freshness, 2 Compose-runner tests, 46 frontend tests, 378 backend tests; 8 opt-in live-ZAP tests skipped, 145 integration tests deselected. Vite production build and API wheel/sdist built. |
| `apps/api/.venv/bin/ruff check scripts/aegisforge_ci.py` and `apps/api/.venv/bin/ruff format --check scripts/aegisforge_ci.py`                                                                                                                                                                                    | PASS; supplements configured lint, which targets `apps/api`.                                                                                                                                                                                                                   |
| `docker compose -p aegisforge -f docker-compose.yml -f docker-compose.test.yml run --rm -v "$PWD/apps/api/src:/app/src:ro" -v "$PWD/apps/api/tests:/app/tests:ro" -v "$PWD/apps/api/migrations:/app/migrations:ro" -v "$PWD/scripts/aegisforge_ci.py:/app/scripts/aegisforge_ci.py:ro" api pytest -m integration` | PASS: 145 integration tests; 386 deselected. Includes Alembic up/down roundtrip and metadata drift check.                                                                                                                                                                      |
| `pnpm --filter @aegisforge/web test-e2e --project=production github.spec.ts reporting.spec.ts`                                                                                                                                                                                                                    | PASS: 2 Chromium journeys, including setup, secret dismissal, connection readiness, delivery history, disable, API-key/reporting regression controls.                                                                                                                          |
| `/tmp/aegis14-review-actionlint/actionlint .github/workflows/aegisforge-scan.yml`                                                                                                                                                                                                                                 | PASS. Official actionlint 1.7.12 archive verified against SHA-256 `8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8`.                                                                                                                                          |
| `git diff --check`                                                                                                                                                                                                                                                                                                | PASS.                                                                                                                                                                                                                                                                          |

The first broad integration invocation mounted current source/tests but retained a stale migration inside the cached image: 144 passed, one metadata-drift failure. The checked-in migration already has the required `ON DELETE RESTRICT`. Mounting current migrations fixed the test environment; the complete integration suite was rerun. This was not counted as an application defect or hidden as a passing run. The initial five defect reproductions failed before their corresponding fixes. Backend runs emit existing Starlette/httpx and AnyIO deprecation warnings.

## UI inspection

Manually inspected the generated full-page GitHub setup screenshots at **390, 768, 1280 and 1440px**. Labels, inputs, mapping IDs, delivery history and action buttons fit; navigation collapses at smaller widths. Each width also passed no-horizontal-overflow and axe assertions. The one-time secret was dismissed before screenshots. Evidence is in `apps/web/test-results/github-GitHub-setup-secret-73b22-elivery-history-and-disable-production/github-{390,768,1280,1440}.png` (generated, untracked). No confirmed responsive/accessibility blocker required a UI implementation change.

## Non-blocking limits and operational notes

- No real GitHub-hosted workflow, artifact upload or public PR comment was executed. CLI/comment HTTP contracts and redaction are locally tested; browser journeys use explicit synthetic API fixtures. Database integration exercises real PostgreSQL-backed API behavior. Browser fixture success is not a live GitHub connection test.
- Eight opt-in live ZAP tests were skipped; this phase does not modify scanner execution. No live third-party scan was initiated.
- The CLI deadline implementation targets the documented Linux Actions runner/main thread. Hard runner loss cannot guarantee remote cancellation or final artifact upload. Existing pre-fix CI receipts may fail closed with 409 until their 24-hour expiry; setup docs describe this compatibility behavior.
- `docker system df` before testing and after stopping test services: Images **633.4MB reclaimable (57%)**; Build Cache **3.385GB reclaimable**. Neither exceeds 5GB; no housekeeping flag and no pruning performed. The test-only PostgreSQL/Redis services were stopped after verification to restore their initial stopped state.

# Phase 10 strict review — 2026-09-10

**CONDITIONAL PASS — safe to begin the next explicitly requested phase.** All confirmed blockers below were fixed and verification passed. The exact non-blocking limits are live-provider/opt-in coverage, the documented on-demand scope and read-only Git metadata. This section supersedes the original Phase 10 handoff; historical reports follow unchanged.

## Confirmed defects fixed

| ID      | Severity | Evidence and correction                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AI10-01 | P1       | `redact_text` delegated to the scanner artifact helper, which masked entire fields containing ordinary words such as “session” and truncated all other fields at 1,024 characters before email masking. A synthetic email crossing that boundary leaked `person@example`; a 1,600-character remediation lost its ending. Replaced with targeted complete-value masking before truncation, including headers, quoted credentials, bearer/basic, PEM, JWT, URL credentials, email and phone cases. Normal security guidance and declared field lengths are preserved. |
| AI10-02 | P2       | Whitespace-only guidance and duplicate JSON keys/citations passed validation; a long root-cause explanation was silently sliced when adding its label. `guidance-v2` rejects these cases, retains the full accepted hypothesis and fails closed on label overflow. The unchanged prompt remains `guidance-v1`.                                                                                                                                                                                                                                                      |
| AI10-03 | P2       | Gemini's `finish_reason` was ignored, so a safety/token-limited response containing syntactically valid JSON could be recorded as complete. Require exactly one STOP candidate. Tests exercise the real installed SDK's serialization/retry machinery with local transport responses for STOP, MAX_TOKENS, SAFETY, HTTP 429 and HTTP 503. No real provider call occurs.                                                                                                                                                                                             |
| AI10-04 | P2       | Citation navigation unmounted the focused button without restoring focus, and a failed feedback write could retain the previous successful-save notice. Citation navigation now focuses the Evidence tab; each feedback attempt clears stale success text. RTL and Chromium assertions cover both corrections.                                                                                                                                                                                                                                                      |
| AI10-05 | P2       | The AI HTTP endpoints exposed unstructured `Any` responses despite the strict guidance contract. Added typed Pydantic analysis/feedback response schemas and a typed SQLAlchemy analysis query, and regenerated OpenAPI. The generated schema catalog now correctly names migrations through 0008.                                                                                                                                                                                                                                                                  |

Fix scope is limited to Phase 10. No policy engine, reporting, scanner behavior change, optional local model or next-phase feature was added. Existing uncommitted Phase 9 work was preserved. The new schema version does not mutate or rewrite prior immutable analysis records.

## Requirement and security review

Read the user's Phase 10 requirements, AGENTS.md, build plan, decisions, phase status, implementation report, tracked Git diff and all new/untracked Phase 9/10 files relevant to the AI integration. Verified the locked official SDK, explicit local/test-only mock restriction, minimal classification-only input, evidence delimiters/system instruction, schema/length/URL/citation checks, metadata, retries, degraded outcomes, retained versions, feedback, frontend labels and inert React rendering.

No confirmed tenant bypass was found. Reads/writes use server-resolved membership and scoped finding/project authorization; analysis joins include organization and finding, and feedback has composite tenant foreign keys. CSRF and role denial are exercised through real HTTP tests. Database tests run the actual retry pipeline for timeouts, malformed/oversized output and nonexistent citations and assert retained degraded records without changing scanner severity/state/version/normalized evidence. Immutable version/feedback constraints, prior-version retention, denied cross-tenant access, project denial and migration roundtrips pass. No model path writes scanner evidence or policy evaluations. No production fake success or inert action remains in the changed UI.

The minimum shared evidence is normalized scanner classification plus the exact occurrence ID; free target text, routes, headers, bodies and reviewer notes are excluded. That deliberately limits diagnostic specificity and is disclosed in the UI. Feedback is stored for review and never sent to a model or used for automatic training.

## Actual verification

| Command/check                                                                             | Result                                                                                    |
| ----------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Full backend unit/integration/security/migration suite, disposable PostgreSQL/Redis       | 340 passed, 8 opt-in live ZAP skipped, 2 existing upstream deprecation warnings; 125.17s  |
| Final adversarial AI unit/SDK suite (includes subsequently added 429/503/multibyte cases) | 58 passed; 7.66s                                                                          |
| Frontend Vitest/RTL                                                                       | 29 passed in 7 files; 36.31s                                                              |
| ESLint and strict TypeScript                                                              | Passed                                                                                    |
| Ruff lint/format and strict mypy                                                          | Passed; 69 Python files formatted, 39 source files typechecked                            |
| Generated schema consistency and Prettier                                                 | Passed; final documentation formatting and schema consistency checked                     |
| Vite production build                                                                     | Passed as browser-suite prerequisite                                                      |
| API wheel and source distribution                                                         | Passed, artifacts in `/tmp/aegis-phase10-review-dist`                                     |
| Phase 10 production-browser flow                                                          | Passed at all four requested widths; 47.0s                                                |
| Full configured Chromium regression                                                       | 57 passed, 6 opt-in live-service workflows skipped; 5.7m                                  |
| Git whitespace / commit / cleanup                                                         | Whitespace passed; commit blocked by read-only `.git`; disposable review services removed |

Commands run from the repository root. Frontend commands use bundled Node 24 with `PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH`.

```sh
apps/api/.venv/bin/ruff check apps/api
apps/api/.venv/bin/ruff format --check apps/api
apps/api/.venv/bin/mypy --config-file apps/api/pyproject.toml apps/api/src
apps/api/.venv/bin/pytest -q apps/api/tests/test_ai.py
apps/api/.venv/bin/python -m aegis_api.schema_docs
apps/api/.venv/bin/python -m aegis_api.schema_docs --check
pnpm exec prettier --check .
pnpm --filter @aegisforge/web lint
pnpm --filter @aegisforge/web typecheck
pnpm --filter @aegisforge/web test
pnpm --filter @aegisforge/web test-e2e
/tmp/aegis-phase10-tools/bin/uv build --project apps/api --out-dir /tmp/aegis-phase10-review-dist
sg docker -c 'docker compose -p aegis-phase10-review -f docker-compose.yml -f docker-compose.test.yml run --rm --build api pytest -q'
git diff --check
```

The broader Docker suite ran after all runtime/security corrections. Three subsequent tests added HTTP 429, HTTP 503 and multibyte byte-budget cases; all 58 final focused tests passed. A later generated-documentation header correction does not change runtime behavior. Initial formatter diagnostics during edits were corrected; no failing runtime assertion was waived or weakened.

## UI inspection

Inspected the actual Chromium screenshots at **390, 768, 1280 and 1440px**:

- `/tmp/phase10-guidance-390.png`
- `/tmp/phase10-guidance-768.png`
- `/tmp/phase10-guidance-1280.png`
- `/tmp/phase10-guidance-1440.png`

At all four widths the advisory label, version metadata, confidence, uncertainty, evidence links, checklist, feedback and retained version panels remain readable without horizontal overflow. The responsive sidebar collapses on mobile/tablet. Explicit browser axe checks report no violations. Keyboard citation navigation now restores focus to Evidence. Model HTML is literal text with no `img`/`script` nodes. These are labeled synthetic HTTP-boundary fixtures, including retained v1 metadata, to test UI behavior independently from backend rejection. Human visual inspection supplements assertions; it is not a claim of screen-reader or non-Chromium testing.

## Live Gemini credential check — user follow-up

The initial review intentionally used deterministic/provider-transport tests and had not independently established whether a live key was configured. On the user's follow-up, checked the current process environment, parsed root `.env`, `apps/api/.env` (absent), and the configured project's API container environment. `AEGIS_GEMINI_API_KEY`, `GEMINI_API_KEY` and `GOOGLE_API_KEY` are absent or empty in each checked configuration source. The one project API container is exited. Only presence/state booleans were emitted; no credential values were printed.

No live Gemini request was made because no configured key was found. A live end-to-end analysis of a retained real Phase 8 demo-target finding remains unverified. Configure the server-side `AEGIS_GEMINI_API_KEY` locally to unblock that requested verification; no synthetic finding may substitute for real ZAP evidence.

## Exact non-blocking limitations

- No live Gemini call or provider-quality verification. The service remains disabled by default; the installed SDK is tested against simulated transport responses, not a live account.
- Eight real-ZAP tests and six live-service auth/configuration/scan browser workflows are opt-in and were not enabled for this review. API authentication/authorization and database integration were tested independently.
- Generation remains on-demand and classification-only. The optional LocalAIProvider is not implemented or bundled. A synchronous request lost before commit leaves no new version; old records are preserved. Durable AI jobs, global billing quotas and retention cleanup remain outside this phase.
- Git metadata is protected. Commit outcome is recorded below; no permission workaround, deployment or push is authorized by this review.

## Handoff

No unresolved phase blocker remains. `git add` failed with exit 128 (`.git/index.lock: Read-only file system`); no commit was created and no metadata workaround was attempted. Docker cleanup exited 0 and removed only the disposable review project's containers, networks and volumes. The final API package was rebuilt after the documentation-generator correction. No deployment, push or next phase was started.

```sh
git add -- apps/api/src/aegis_api/ai.py apps/api/src/aegis_api/ai_routes.py apps/web/src/product/AIGuidance.tsx apps/web/src/product/Findings.tsx docs/TEST_REPORT.md docs/PHASE_STATUS.md
sg docker -c 'docker compose -p aegis-phase10-review -f docker-compose.yml -f docker-compose.test.yml down --volumes --remove-orphans'
```

---

# Touch-target correction — 2026-09-06

**PASS: R012-04 resolved.** The user authorized correcting the three Phase 3 link groups previously excluded from the retroactive audit’s fix scope. All three now meet the design system’s minimum **44px width and height** at **360, 390, 768, 1024, 1280, 1440 and 1920px**. This supersedes the outstanding target-size condition below; historical audit results are retained as historical evidence. Chromium automation remains the verification scope, not human screen-reader or cross-browser certification.

## Changes and regression evidence

`apps/web/src/marketing/marketing.css` gives footer, outcome and docs masthead anchors flex alignment, `min-height: 44px`, `min-width: 44px` and vertical padding. Footer links replace external margins with 10px vertical padding; outcome and masthead links use 8px padding. Text size, weight, colors and destinations remain unchanged. Hit areas are real anchor boxes, not overlapping pseudo-elements.

`apps/web/e2e/marketing-targets.spec.ts` adds seven production-browser cases. Each reads `getBoundingClientRect()` and asserts both dimensions are at least 44px for every footer anchor on home/docs/getting-started, both home outcome links, and the masthead on docs index/getting-started. It waits for lazy rendering, requires visible nonempty groups, and checks exact counts for outcome/masthead links, preventing absent elements from silently passing.

The corrected test failed before the CSS fix at 360px, reproducing the original heights (footer 23.765625px, outcome 26.390625px and masthead 15px). The same assertions pass after the fix at all seven widths. Existing public page accessibility/overflow checks were rerun across all **17 routes × 7 widths = 119 combinations**, with **zero axe violations and no horizontal overflow**. WCAG tags: 2/2.1 A/AA and 2.2 AA. These axe checks complement the stricter explicit 44px assertions.

## Actual commands and results

Commands ran from the repository root with the installed toolchain:

```sh
export PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/tmp/aegis-tools:$PATH
export UV_CACHE_DIR=/tmp/aegis-uv-cache
pnpm --filter @aegisforge/web exec playwright test marketing-targets -g 'at 360'
make check
uv run --project apps/api pytest -c apps/api/pyproject.toml apps/api/tests -m 'not integration'
pnpm --filter @aegisforge/web exec playwright test --fully-parallel
uv build --project apps/api
pnpm exec prettier --check .
git diff --check
```

| Check                                                | Actual result                                                                                                                                                                                                                  |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Pre-fix targeted regression                          | Exit 1, reproduced all three undersized groups after correcting an initial lazy-render timing issue.                                                                                                                           |
| Prettier, ESLint, Ruff lint/format, TypeScript, mypy | Passed; mypy checked 6 source files.                                                                                                                                                                                           |
| Frontend unit tests                                  | 20 passed.                                                                                                                                                                                                                     |
| Backend unit/security tests                          | 9 passed, 3 integration tests deliberately deselected; separate approved retry completed in 3.70s.                                                                                                                             |
| Full Playwright suite                                | **56 passed**, 5.8 minutes, including all seven new touch-target cases, 119 public axe/layout combinations, lab accessibility, four unchanged screenshot baselines, keyboard navigation, modal/sidebar and motion regressions. |
| Web production build                                 | Passed as Playwright web-server prerequisite: TypeScript, Vite and SEO generation.                                                                                                                                             |
| API sdist/wheel build                                | Passed on approved retry.                                                                                                                                                                                                      |
| Final documentation formatting and diff whitespace   | Passed.                                                                                                                                                                                                                        |

The first sandbox browser invocation could not start its server; approved execution succeeded. An initial test queried footer count before lazy content arrived; it was corrected to wait for the first visible anchor before reproducing the real sizing failures. `make check` passed frontend/lint/types but stalled in sandboxed backend TestClient tests; that run was interrupted (exit 130), not claimed as a complete pass. The separate approved backend retry passed. The first API build failed on sandbox PyPI DNS access; approved retry produced both artifacts. Non-failing Starlette/AnyIO warnings remain. One browser navigation to service health logged an expected unavailable local API proxy because this frontend run did not start Docker; all browser assertions passed.

No backend code, dependencies, runtime settings or database schema changed. Docker integration was not repeated for this CSS/test-only correction; its earlier results below are historical. README, ADR-019 and PHASE_STATUS now identify the target-size finding as resolved. No next phase started.

---

# Retroactive Phase 0–2 audit — 2026-09-06

This section supersedes earlier completion claims for Phases 0–2. The historical Phase 3 report is retained below. No Phase 3 implementation was changed and Phase 4 was not started.

| Phase | Verdict              | Qualification                                                                                                                                                                                                                                                                                                                                                           |
| ----- | -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0     | **PASS**             | Documentation drift corrected; architecture is consistent with the implemented foundation. Deferred controls remain design contracts, not tested product capabilities.                                                                                                                                                                                                  |
| 1     | **PASS**             | Independent clean-export setup/check/build and fresh development/production Docker gates passed. Remote GitHub Actions execution is not claimed; local equivalents were run. Domain migration semantics cannot be tested before domain revisions exist.                                                                                                                 |
| 2     | **CONDITIONAL PASS** | Reproduced label/clipboard defects fixed and verified. Lab accessibility/targets pass, but Phase 3 consumers do not universally preserve the 44px contract: footer links 23.77px, home outcome links 26.39px, docs masthead 15px. Those Phase 3 files are outside the allowed fix scope. Chromium automation is not human screen-reader or cross-browser certification. |

## Sources and scope

Recovered the original Master Context and Phase 0 prompt from task **Analyze StackHawk frontend design**, Phase 1 from **Scaffold monorepo foundation**, and Phase 2 from **Build AegisForge design system**. These are the original user messages, not reconstructed requirements from handoff summaries. Reviewed the phase history (`19ed322` initial README → `f17cb78` architecture → `0c3ea57` foundation → `b9c70db` design system), subsequent Phase 3 commits `8581b10` and `888ae88`, current architecture, source/configuration, tests and lockfile-backed installation. Phase 3 changed the lab shell’s health link to `/status`; it did not change the backend or the Phase 0 data/state/security contracts.

A fresh directory `/tmp/aegis-retro-audit` was populated by `git archive HEAD | tar -x -C /tmp/aegis-retro-audit` at `888ae88`. It had no copied `.env`, `node_modules`, virtual environment or database volumes. Setup generated its own ignored mode-0600 credentials. Installed toolchain, dependency caches and Docker build layers were reused: this verifies clean source/setup, not a brand-new OS or empty-cache network install. Final Phase 2 fixes and regression files were copied into that export for the final 49-test browser run. No dependency versions changed.

## Architecture consistency and drift

| Contract                                                                        | Evidence through Phases 1–3                                                                                                                                                                                                                                                                                                   | Result                                                                                                                                                   |
| ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ADR-001/002, tenant ownership, composite FKs, roles, rotating sessions and CSRF | No domain tables, membership queries, authentication endpoints or browser token storage exist. Public `/` and lab app-shell specimens are separate; shell specimens do not claim authorization.                                                                                                                               | Consistent deferred scope, not proof of tenant/session enforcement.                                                                                      |
| ADR-003, selected stack and storage                                             | React/strict TS/Vite/Tailwind, FastAPI/Pydantic, async SQLAlchemy/asyncpg, Alembic, Redis/Celery and both locks exist and run. PostgreSQL is the only database.                                                                                                                                                               | Pass. Shared package/scanner directories in the roadmap were aspirational; corrected the layout text to identify actual locations.                       |
| DATA_MODEL, ADR-004/008/009, evidence/AI/policy/report separation and retention | All 35 entity rows specify owner and retention. No scanner results, AI provider, report store or policy engine exists. Public specimens explicitly say illustrative/no scan executed; no generated advice decides a gate.                                                                                                     | Consistent; runtime provenance, retention and outage truth-table tests belong to later feature phases.                                                   |
| SCAN_STATE_MACHINE, ADR-006/011                                                 | 13 forward edges form an acyclic graph, passive/active guards are exclusive, universal failed/cancelled/timed_out edges and first-committed terminal precedence are specified. Completed is distinct from completeness/gate; outage never permits pass. No runtime scan enum or executor contradicts this.                    | Pass as architecture; no actual scan-state transition tests are claimed.                                                                                 |
| CONTAINERS, ADR-005 and threat boundaries                                       | Worker is a separate process/container with no DB credentials or API/database network membership. PostgreSQL/Redis/worker publish no host ports. Opt-in ZAP is digest-pinned and networkless.                                                                                                                                 | Foundation boundary passes. Target egress, runner, resource quotas and worker-compromise exercises remain explicitly deferred, and no scan was executed. |
| API_CONTRACT                                                                    | Only unversioned `/health/live` and `/health/ready` are implemented; safe statuses and server-generated request IDs, real bounded probes and readiness 503 on dependency failure. Business `/api/v1`, pagination, idempotency, authorization and generated TS types remain planned. Current health response is Zod-validated. | No endpoint/authorization drift; no fake business success endpoint.                                                                                      |
| THREAT_MODEL                                                                    | T01–T15 include all eight originally required categories. Current tests cover health failure, timeout, configuration secrecy, log allowlisting and Compose isolation. Other release gates prohibit premature scanning/multi-user/AI/delivery release.                                                                         | Consistent with implemented scope.                                                                                                                       |
| ADR-007/014/015 and phase traceability                                          | Phase 3 legitimately moved service health from `/` to `/status` and superseded provisional identity numbering. DESIGN_SYSTEM still named `/`; BUILD_PLAN/TEST_MATRIX still mapped identity to Phase 3; AGENTS still described a documentation-only repository.                                                                | Corrected stale documentation without assigning a new identity phase or changing Phase 3.                                                                |

Current context, sequence and state Mermaid blocks were independently extracted and rendered with mmdc; all three returned exit 0 and produced valid SVG/viewBoxes. Local Markdown links/fences and 35 complete entity rows were checked. No Markdown-specific linter is configured; configured Prettier passes and intentionally excludes the architecture-baseline files. No application testing is attributed to documentation inspection.

## Confirmed defects and fixes

| ID      | Scope                   | Reproduction before fix                                                                                                                                                             | Fix and final evidence                                                                                                                                             |
| ------- | ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| R012-01 | Phase 2, P2             | `<Input id="target" label="Target" />` overrides the input ID after generating a different label `htmlFor`; `getByLabelText('Target')` fails. Textarea/Select have the same defect. | Use caller ID or generated ID consistently. Regression verifies all three labels and Input’s error description. Passed.                                            |
| R012-02 | Phase 2, P2             | With `navigator.clipboard` undefined, CopyButton throws `TypeError: Cannot read properties of undefined (reading 'writeText')` and keeps saying Copy.                               | Catch synchronous API absence and asynchronous rejection; show Copy unavailable. Regression reproduced the uncaught exception before the fix and passes afterward. |
| R012-03 | Phase 0/2 documentation | Stale identity mappings, implemented-layout claim, baseline wording and health URL described above.                                                                                 | Corrected BUILD_PLAN, TEST_MATRIX, AGENTS and DESIGN_SYSTEM; documented in ADR-018.                                                                                |

No backend implementation blocker was found. `seed-demo` explicitly makes no changes because no domain schema exists; this is the original Phase 1 scope, not a fake seeded result. Disabled-by-profile ZAP and visibly labeled development simulations are intentional. No TODO-only endpoint, fake production success, fabricated live finding, real integration connection or secret-bearing committed setting was found in scope. Tests that inject availability are distinguished from the real-service tests below.

## Commands and actual results

Toolchain environment for host commands:

```sh
export PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/tmp/aegis-tools:$PATH
export UV_CACHE_DIR=/tmp/aegis-uv-cache
```

| Command/check                                                                                    | Actual result                                                                                                                                                                                                  |
| ------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make setup check build` in the clean export                                                     | Exit 0: frozen pnpm install (300 packages), frozen uv sync (57 packages), Chromium setup, formatter/lint/types, 18 baseline frontend tests, 9 backend unit/security tests, web/SEO and API sdist/wheel builds. |
| `pnpm --filter @aegisforge/web test` with new regressions, before fixes                          | Exit 1: 18 passed, 2 failed, one uncaught clipboard TypeError. This is reproduced failure evidence, not a passing run.                                                                                         |
| Final `make check build` in the working repository                                               | Exit 0: Prettier, ESLint, Ruff lint/format, strict TypeScript, mypy (6 source files), **20 frontend tests**, **9 backend unit/security tests**, web/SEO build and API sdist/wheel.                             |
| `pnpm --filter @aegisforge/web exec playwright test --fully-parallel` baseline export            | Exit 0: **42 passed**, 3.2 minutes.                                                                                                                                                                            |
| Supplemental scratch `playwright test retro-labs --fully-parallel`                               | Exit 0: 7 measurement/focus/axe cases. Public target dimensions were logged, not asserted as passing; they exposed the Phase 3 limitations.                                                                    |
| Final `pnpm --filter @aegisforge/web exec playwright test --fully-parallel` in export with fixes | Exit 0: **49 passed**, 3.4 minutes. Includes seven permanent lab target/focus/axe regression cases.                                                                                                            |
| mmdc for `/tmp/retro-{CONTEXT,CONTAINERS,SCAN_STATE_MACHINE}-0.mmd`                              | All exit 0; output `/tmp/retro-{CONTEXT,CONTAINERS,SCAN_STATE_MACHINE}.svg`, valid XML/viewBoxes. Used `/tmp/aegis-puppeteer.json`.                                                                            |
| Documentation structure checks                                                                   | Valid local links/fences; 35 complete entity ownership/retention rows; 13 acyclic forward edges with no terminal outgoing edge.                                                                                |

Browser coverage includes widths **360/390/768/1024/1280/1440/1920**, no horizontal overflow in both labs and all 17 public pages (119 public combinations), public axe WCAG 2/2.1 A/AA and 2.2 AA tags, both labs’ axe/target measurements at all seven widths, four unchanged 390/1440 screenshot baselines, dialog focus wrap/restore, sidebar navigation, dropdown/tabs/accordion unit interactions, public keyboard navigation, normal pinning, live reduced-motion change and Lenis cleanup. Lab target checks measure visible enabled controls and associated checkbox/radio label click areas; hidden overlays and disabled controls are excluded from that dimension sweep, while existing tests exercise modal/drawer behavior separately.

Text/control token contrast calculations against canvas/surface/raised backgrounds: text minimum **13.59:1**, muted text **7.07:1**, interactive border **3.15:1**, mint focus ring **11.48:1**. These are specific design-system token pairs, not certification of every consumer state. Browser axe reported zero violations in the exercised states. Reviewed current mobile home capture and matching mobile UI baseline for wrapping/containment; screenshot comparisons cover desktop/mobile labs. No exhaustive visual inspection of all 119 captures, human assistive-technology review or non-Chromium test is claimed.

## Independent live Docker gate

Docker used the existing user’s docker-group membership via `sg docker -c '…'`; no socket/group permissions were changed. All commands below ran from the clean export under project `aegisforge-retro-audit`, with fresh named volumes. The idle ZAP profile was not started.

```sh
docker compose -p aegisforge-retro-audit up --build -d --wait --wait-timeout 240
docker compose -p aegisforge-retro-audit ps
python3 scripts/check_compose.py
docker compose -p aegisforge-retro-audit exec -T api alembic upgrade head
docker compose -p aegisforge-retro-audit exec -T api alembic upgrade head
docker compose -p aegisforge-retro-audit -f docker-compose.yml -f docker-compose.test.yml run --rm --no-deps --build api
uv run --project apps/api alembic -c apps/api/alembic.ini revision -m retro_tooling_probe
docker compose -p aegisforge-retro-audit -f docker-compose.yml -f docker-compose.prod.yml up --build -d --wait --wait-timeout 240
docker compose -p aegisforge-retro-audit -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -p aegisforge-retro-audit exec -T api alembic upgrade head
docker compose -p aegisforge-retro-audit exec -T api alembic current
docker compose -p aegisforge-retro-audit exec -T api alembic downgrade base
node apps/web/retro-smoke.mjs
docker compose -p aegisforge-retro-audit -f docker-compose.yml -f docker-compose.prod.yml down --volumes --remove-orphans
docker ps -aq --filter label=com.docker.compose.project=aegisforge-retro-audit
docker volume ls -q --filter label=com.docker.compose.project=aegisforge-retro-audit
docker network ls -q --filter label=com.docker.compose.project=aegisforge-retro-audit
```

| Gate                                         | Actual result                                                                                                                                                                                                                                                                                   |
| -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Development build/start/health               | Exit 0; **web, api, worker, postgres, redis healthy**.                                                                                                                                                                                                                                          |
| Dev/prod/scanner Compose boundary assertions | Exit 0; no published DB/broker/worker, no API/worker shared network, no worker DB credential; production API unpublished; opt-in digest-pinned networkless scanner.                                                                                                                             |
| Existing migration runner twice              | Both exit 0 against fresh real PostgreSQL; baseline has no domain revisions.                                                                                                                                                                                                                    |
| Actual integration tests                     | **3 passed**, 4.00s: available services ready; unreachable PostgreSQL and unreachable Redis each return readiness 503 while liveness remains 200. No integration skip.                                                                                                                          |
| Migration generation and lifecycle           | Temporary export-only no-op revision `b2054d2158fd` generated successfully, including automatic versions-directory creation. Production audit image included this probe; upgrade/current confirmed that head and downgrade base passed. No domain table was added and no revision is committed. |
| Production build/start/health                | Exit 0; **all five services healthy**; only localhost:8080 published.                                                                                                                                                                                                                           |
| Unmocked production browser journey          | `/status` reports real API/PostgreSQL/Redis ready; Refresh status repeats successfully. Nginx `/health/live` returns 200/alive; `/health/ready` returns 200/ready. Scratch script uses Chromium with no request interception.                                                                   |
| Teardown and orphan checks                   | Exit 0; **5 service containers, 2 audit volumes and 4 networks removed**. All three project-label queries returned empty. Unrelated resources and build caches retained.                                                                                                                        |

## Limitations and failed attempts

The first export command failed because the destination directory did not yet exist; it was created before retrying successfully. The initial clean pnpm install was blocked by sandbox cache access; the approved retry passed. The first sandbox `sg docker` attempt could not open its audit interface; approved execution passed. One final host check run was terminated with exit 143 during backend tests; the full approved retry completed successfully. These failed/interrupted attempts are not counted as passes. Existing Starlette/httpx and AnyIO deprecation warnings are non-failing.

Hosted GitHub Actions and a fresh OS were not exercised. Domain migration data transformations, authenticated application pages, tenant enforcement, actual scanning, secret-store/redaction/report/AI/gate behavior and target-network isolation remain future phase tests. No original screenshot/video similarity certification is claimed.

**Outstanding outside-scope finding R012-04 (Phase 3, P2):** at every requested width, `.m-footer a` measures about 23.77px high; the home `.outcome a` links measure 26.39px; `AEGISFORGE DOCS` measures 15px. These fall below the explicit 44px design requirement despite passing axe AA smoke checks, which do not establish that stricter target requirement. Phase 3 markup/styles are unchanged as instructed. Phase 2 therefore receives a conditional verdict for its current consumers, not an unrestricted accessibility pass.

---

# Phase 3 test report

Review date: 2026-09-06. Reviewed baseline: `8581b10` (Phase 3 public website). Scope: public website review and confirmed blockers only, plus the explicitly requested resolution of Phase 1's local Docker gate. No identity, scanner execution, tenant domain services, billing, external notifications or public deployment was added.

## Verdict

**CONDITIONAL PASS — no unresolved implementation blockers.** The requested local suite and Docker verification passed after fixes. It is safe to begin the next explicitly authorized implementation phase. The original missing-Docker gate is resolved.

Exact non-blocking limits:

- The supplied reference video is absent from the workspace, so exact visual matching cannot be certified; the written pin/crossfade/scroll rhythm was implemented and tested.
- Browser execution used Chromium/Linux and automated axe checks. Manual assistive-technology review, other browser engines and a measured Lighthouse score are not claimed.
- Before public publication, configure the actual `VITE_SITE_URL` and a verified `VITE_SECURITY_CONTACT`. Local defaults remain deliberate. Account creation still leads to the substantive setup guide because authentication is outside Phase 3; integrations and product UI remain explicitly illustrative. Page bodies are client-rendered, with static metadata and a no-JavaScript notice.

## Confirmed defects and fixes

| ID    | Severity | Reproduction / impact                                                                                                                                                         | Final fix and regression                                                                                                                                                                                                                                |
| ----- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R3-01 | P1       | The setup guide copied a blank `.env` before a preserve-existing generator, preventing credential creation and potentially overwriting an existing configuration.             | Removed the copy step. Execute the documented generator in a temporary directory; verify both credentials are generated and unchanged on repeat. Passed.                                                                                                |
| R3-02 | P1       | Invalid disclosure contact was accepted by the SEO build but rejected by browser startup. A malformed origin threw from `safeParse` instead of returning a validation result. | Shared schema with safe URL parsing; build rejects invalid public settings with field-only diagnostics. Tests cover malformed/credential-bearing origins, invalid email and actual CRLF injection; positive canonical/sitemap/robots generation passes. |
| R3-03 | P2       | React Router matched case-insensitively but page lookup did not: `/SECURITY` crashed, `/PLATFORM` could render pricing.                                                       | Normalize public paths/slugs and canonical paths. Case-variant browser regression failed before the fix and passed afterward.                                                                                                                           |
| R3-04 | P2       | Keyboard activation of a footer link left focus in the footer instead of the new page.                                                                                        | Navigation-aware heading focus after route/drawer lifecycle. Footer and mobile drawer regressions pass.                                                                                                                                                 |
| R3-05 | P2       | `visibility: hidden` on inactive pinned panels removed middle workflow steps from screen-reader navigation.                                                                   | Complete nonvisual workflow list, with visual specimens hidden from the accessibility tree. Unit and browser role queries verify every step without visual scroll progression.                                                                          |
| R3-06 | P2       | Mobile story cards lacked the requested small in-view transitions.                                                                                                            | 16px/opacity entry with 0.5s duration and a small stagger, scoped to mobile/no-preference. Normal flow and reduced-motion fallbacks remain intact.                                                                                                      |

No tenant-scope query, scan authorization execution or evidence-storage implementation was introduced in this phase. Those future controls cannot be claimed as implemented or tested here. No new secret leakage, fabricated scanner result, fake gate result, billing success path or connected integration was found. Existing health failure/log-redaction tests passed. The unsafe pathname cast was addressed through normalized routing; no unrelated typing refactor was performed.

## Final commands and results

Commands ran from the repository root. The toolchain prefix selects the installed Node 24/uv/Python 3.12 environment:

```sh
PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/tmp/aegis-tools:$PATH UV_CACHE_DIR=/tmp/aegis-uv-cache make check build
PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH pnpm --filter @aegisforge/web exec playwright test --fully-parallel
```

| Check                                      | Actual final result                                                                        |
| ------------------------------------------ | ------------------------------------------------------------------------------------------ |
| Prettier / ESLint / Ruff lint and format   | Passed                                                                                     |
| Strict TypeScript / mypy                   | Passed; mypy checked 6 source files                                                        |
| Frontend Vitest                            | 18 passed, 4 test files                                                                    |
| Backend unit/security pytest               | 9 passed; integration markers run separately below                                         |
| Web production build and SEO               | Passed, 17 public route metadata files plus sitemap/robots                                 |
| API package build                          | sdist and wheel passed                                                                     |
| Full Playwright suite                      | 42 passed, 2.4 minutes, including existing health/lab regression                           |
| Public accessibility                       | 119 route/viewport combinations; zero axe violations under WCAG 2/2.1 A/AA and 2.2 AA tags |
| Layout widths                              | 360, 390, 768, 1024, 1280, 1440, 1920px; no horizontal overflow                            |
| Case variants / keyboard footer regression | Both passed; each reproduced a failure before its fix                                      |
| Normal pin, mobile and reduced motion      | Passed, including 1280/1440px pin containment and nonvisual step access                    |

Full-page captures exist locally under `/tmp/aegis-phase3-review/` for all 119 public route/viewport combinations, plus normal pinned screenshots. Inspected contact sheets and selected full-page views for typography, content wrapping, cockpit containment, docs sidebar/code layout, pricing, legal pages and footer behavior at 390/768/1280/1440px; also inspected representative 360/1024/1920px overviews. These are review artifacts, not new golden screenshot baselines. Existing laboratory baselines continue to pass.

## Live Docker verification

The old Codex process lacked the newly added supplementary group. `id akshat` confirmed membership in `docker`; the socket belonged to `root:docker`. Docker commands ran through `sg docker -c '…'` to use that existing membership. No group or socket permissions were changed. Compose plugin version: 5.5.1.

The following commands were executed inside that group context. The isolated project had no pre-existing containers or volumes, so its teardown did not remove user project data.

```sh
docker compose config --quiet
docker compose -p aegisforge-phase3-review up --build -d --wait --wait-timeout 240
docker compose -p aegisforge-phase3-review ps
docker compose -p aegisforge-phase3-review -f docker-compose.yml -f docker-compose.test.yml run --rm --no-deps --build api
docker compose -p aegisforge-phase3-review exec -T api alembic upgrade head
docker compose -p aegisforge-phase3-review exec -T api alembic upgrade head
VITE_SITE_URL=http://localhost:8080 docker compose -p aegisforge-phase3-review -f docker-compose.yml -f docker-compose.prod.yml config --quiet
VITE_SITE_URL=http://localhost:8080 docker compose -p aegisforge-phase3-review -f docker-compose.yml -f docker-compose.prod.yml up --build -d --wait --wait-timeout 240
python3 scripts/check_compose.py
python3 /tmp/aegis-production-smoke.py
docker compose -p aegisforge-phase3-review -f docker-compose.yml -f docker-compose.prod.yml down --volumes --remove-orphans
```

| Docker gate                                | Actual result                                                                                                                       |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| Compose validation and boundary assertions | Passed for dev/prod; scanner remains opt-in, digest-pinned, networkless and unpublished                                             |
| Development image builds/startup           | Passed; web, API, worker, PostgreSQL and Redis all healthy                                                                          |
| Real-service integration tests             | **3 passed** in 4.89s: healthy actual dependencies, unreachable database and unreachable Redis; each failure returned readiness 503 |
| Initial and repeated migration             | Both exit 0 against real PostgreSQL; no domain migration revisions exist yet                                                        |
| Production image builds/startup            | Passed; all five default services healthy, only Nginx published at localhost:8080                                                   |
| Production Nginx smoke                     | All 17 public routes served with correct canonical origin; actual `/health/live` 200/alive and `/health/ready` 200/ready            |
| Teardown                                   | Passed; removed 5 service containers, 2 named volumes and 4 networks                                                                |
| Orphan assertions                          | Label-filtered Docker queries confirmed zero review containers, volumes and networks                                                |

The unit invocation deselected integration markers, and the integration invocation deselected unit tests; all **12 backend tests** ran across those two commands. No required integration test remains skipped because of Docker. The idle ZAP profile was not started and no scan target was contacted. Cached images/build layers and unrelated Docker resources were intentionally retained.

## Earlier failures and final-state accuracy

The original 30-test baseline passed before the stricter review. New tests reproduced malformed-origin validation, case-variant routing and footer-focus defects. A test fixture initially used an HTTP `import.meta.url` with a filesystem-only helper; it was corrected to an explicit resolved script path. Two React Testing Library query options were caught by strict TypeScript and removed. An interrupted exploratory browser run left two test servers; only those identified processes were stopped before rerunning. A previously declined final browser approval was superseded by the user's explicit Docker-resume/full-suite request; the complete final 42-test run passed.

The initial missing-daemon and later stale-group errors are resolved, not current limitations. Existing Starlette/httpx and AnyIO deprecation warnings remain non-failing. No earlier failure or interrupted/declined run is counted as a pass. No next phase was started.

## Phase 4 database/API foundation — 2026-09-06

Scope: implement the explicitly requested persistence foundation before authentication/execution. All 22 entities plus durable idempotency, migration 0001, internal tenant repositories and convention schemas are present. See [PERSISTENCE](architecture/PERSISTENCE.md) for architectural limits and [generated database schema](generated/database-schema.md) for the file-level catalog. No business API endpoint, real scan, AI analysis, report or notification is claimed.

Commands use the existing Node 24 runtime and uv executable where host defaults differ. Docker commands run with `sg docker -c` outside the sandbox to activate existing group membership. All database resources belong to the isolated Compose project `aegisforge-phase4`; tests create/drop uniquely named disposable databases and never downgrade the ordinary development database.

| Command                                                                                                                                                              | Result                                                                                                                                                                                                    |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sg docker -c 'docker compose -p aegisforge-phase4 up -d --wait postgres redis'`                                                                                     | PostgreSQL and Redis healthy.                                                                                                                                                                             |
| `PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH UV_CACHE_DIR=/tmp/aegis-uv-cache make UV=/tmp/aegis-tools/uv check build` | PASS: Prettier, ESLint, Ruff check/format, TypeScript, strict mypy (14 source files), 20 frontend tests, 14 backend unit/security tests, schema-drift check, production web build, API wheel/sdist build. |
| `UV_CACHE_DIR=/tmp/aegis-uv-cache /tmp/aegis-tools/uv run --project apps/api python -m aegis_api.schema_docs`                                                        | Generated current-route OpenAPI, reusable convention JSON schemas and full PostgreSQL catalog.                                                                                                            |

The integration suite verifies empty-database upgrade, latest-revision downgrade, repeated re-upgrade and Alembic metadata parity; scoped uniqueness/FKs/deletion; two-tenant read/add/CAS denial; all-entity fixture graph, immutable identity/history and direct-SQL timestamps; UTC/enums and response privacy; stable finding/event pagination; signed-cursor tampering/filter binding; scan/report/webhook idempotency scope, mismatch, expiry, concurrent retry and rollback. API boundary tests exercise sanitized 404/403/422/500 responses with server-owned request IDs/no-store and production docs denial. The existing browser health journey uses HTTP fixtures, not a real database-backed authenticated product journey.

Development failures were corrected: the first PostgreSQL migration run found generated unique-constraint name collisions (16 existing/new non-database tests passed, 9 setup errors). Names now include every constrained column. The next run passed 26 tests with one test-only missing import failure; that was fixed, followed by 28 passing backend tests. Final verification adds explicit same-organization wrong-scan artifact/report FK rejection. Intermediate Ruff/mypy findings were fixed. Initial sandbox `sg` could not open its audit interface; the approved outside-sandbox invocation succeeded.

Existing Starlette/httpx and AnyIO deprecation warnings remain. Browser logs may report unavailable local `/health/ready` during the deliberately unavailable health route journey; this is not a database test. No dependency upgrade was needed. Source/schema manual inspection is separate from application test results; no human screen-reader or new visual certification is claimed. Runtime authorization, project permissions, RLS/database grants, secret encryption/storage adapters, target verification, execution, retention/outbox and deliveries await their owning phases.

Final rebuilt-image command:

`sg docker -c 'docker compose -p aegisforge-phase4 -f docker-compose.yml -f docker-compose.test.yml run --rm --build api pytest -q --tb=short'`

**PASS: 29 backend tests (14 unit/security, 15 integration), 9.45 seconds**, including migration roundtrip/drift, event pagination and same-scan provenance rejection. The image was rebuilt from the final source/migration/test files with frozen dependencies; no source mounts were used for this final run. Two pre-existing dependency deprecation warnings remain.

`PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH pnpm --filter @aegisforge/web test-e2e`: **56 passed in 4.4 minutes**, including existing public accessibility/layout/keyboard/motion and lab regressions. Chromium only.

`sg docker -c 'make compose-config'`: development/production configuration and isolation assertions passed; scanner remains opt-in, digest-pinned, networkless and unstarted.

`sg docker -c 'docker compose -p aegisforge-phase4 -f docker-compose.yml -f docker-compose.test.yml down --volumes --remove-orphans'`: removes only the temporary verification stack and its volumes/networks. Development application data is preserved.

Final outcome: Phase 4 complete. No authentication or scan execution was added and no next phase was started. Next prerequisite is explicitly authorized authentication/authorization work.

## Strict Phase 4 review — 2026-09-07

**Verdict: CONDITIONAL PASS after corrections.** Reviewed `git diff 7b71f47^ 7b71f47`, the Phase 4 prompt, AGENTS, SQLAlchemy models, migration 0001, repository/command/error/cursor code, all backend tests and the phase report. No frontend source changed in Phase 4. No missing core entity, new client-controlled tenant dependency, committed real secret, unimplemented production endpoint or fabricated scanner execution was found. Authentication/project roles, RLS and actual execution remain explicit later-phase boundaries.

| ID     | Confirmed finding and reproduction                                                                                                                                                                                  | Resolution                                                                                                                                                                                                                                                                              |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R04-01 | A callback inserted a project then raised. Catching the error without a caller-created savepoint left both the project and a successful IdempotencyRecord available to commit.                                      | CommandService owns a nested transaction around receipt and callback, so pre-write/post-write failures cannot leave success or partial work. Retry after a caught failure is tested.                                                                                                    |
| R04-02 | A session retained an expired receipt in its identity map while another transaction renewed it. SELECT FOR UPDATE returned the cached attributes, invoked the callback again and overwrote the renewed resource ID. | Refresh the locked row with populate_existing and compare expiry to database time after locking. The reproduced stale-cache case now replays the renewed resource without a callback.                                                                                                   |
| R04-03 | Pass rows with apparently complete snapshot fields were accepted against failed, cancelled, timed-out, partial, degraded and draft Scan records. The original CHECK examined only fields on the evaluation.         | Migration 0002 locks/checks the tenant-bound Scan on pass insertion. Tests reject all unsafe parents and mismatched downstream state, accept matching complete scans in all allowed stages, and retain failure evaluation support. This is consistency validation, not a policy engine. |
| R04-04 | If-Match accepted 2147483648 although Target.version is PostgreSQL INTEGER, allowing a valid-looking precondition to reach an out-of-range driver parameter.                                                        | Reject versions outside 1–2147483647 with a safe 400. Unit regression added.                                                                                                                                                                                                            |
| R04-05 | Generated OpenAPI omitted readiness HTTP 503; the shared Health schema also led Swagger to display an alive example for readiness/failure.                                                                          | Explicit 503 Health response plus ready/unavailable examples; schema generation and unit checks verify them. Runtime health behavior is preserved.                                                                                                                                      |
| R04-06 | Stock development docs have low contrast and small controls; see manual measurements below.                                                                                                                         | Non-blocking for the persistence phase. Keep production docs disabled, do not claim accessibility compliance, and require remediation before public exposure of this UI. No frontend redesign in this review.                                                                           |

The first new reproduction command, `sg docker -c 'docker compose -p aegisforge-phase4-review -f docker-compose.yml -f docker-compose.test.yml run --rm --build api pytest -q tests/test_phase4_review.py --tb=short'`, failed **9 tests** before fixes (callback rollback, cached renewal, six unsafe scan cases and version overflow). That was a real failing baseline, despite the original phase suite passing. The first corrected full suite passed **49 tests**; a mismatched-but-otherwise-complete downstream-state regression and stronger latest-revision downgrade/data-marker checks were then added. The version-boundary test was moved to the unit suite. No failed test was skipped or marked xfail.

Verification commands:

| Command                                                                                                                                                              | Actual result                                                                                                                                                                                                                                                                                                    |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sg docker -c 'docker compose -p aegisforge-phase4-review up -d --wait postgres redis'`                                                                              | Isolated PostgreSQL and Redis healthy; distinct project volumes.                                                                                                                                                                                                                                                 |
| `PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH UV_CACHE_DIR=/tmp/aegis-uv-cache make UV=/tmp/aegis-tools/uv check build` | Passed before corrections and after the main fixes: Prettier, ESLint, Ruff/format, TypeScript, strict mypy (14 source files), 20 frontend unit tests, 15 final backend unit/security tests, schema drift, web build, API wheel/sdist. Final documentation-only checks are recorded below.                        |
| `sg docker -c 'docker compose -p aegisforge-phase4-review -f docker-compose.yml -f docker-compose.test.yml run --rm --build api pytest -q --tb=short'`               | Rebuilt-image full suite passed 50 tests (15 unit/security, 35 integration). Disposable databases exercise empty upgrade, latest downgrade preserving rows, guard removal/recreation, full downgrade/re-upgrade, metadata parity, tenant/foreign-key boundaries, idempotency and fail-closed evaluation inserts. |
| `PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH pnpm --filter @aegisforge/web test-e2e`                                   | **56 passed, 3.8 minutes.** Existing public/lab accessibility, responsive layout, keyboard, motion and production exclusion journeys remain green.                                                                                                                                                               |
| `UV_CACHE_DIR=/tmp/aegis-uv-cache /tmp/aegis-tools/uv run --project apps/api python -m aegis_api.schema_docs`                                                        | Regenerated current OpenAPI (including readiness failure/example contracts) and the migration catalog note; generated-file check verifies parity.                                                                                                                                                                |

Manual UI inspection used the actual development/test `/api/v1/docs` served by a temporary localhost API, via the in-app browser. Both collapsed and expanded layouts were inspected at **390, 768, 1280 and 1440px**, with no page-wide horizontal overflow (expanded scroll widths 375/753/1265/1425px with the vertical scrollbar). Tab/Enter reached and operated disclosures; visible focus remained present. No public-site UI changed, and the automated public-site suite separately covers these widths. The live documentation displayed the added readiness 503 response. Generated examples were subsequently made explicitly ready/unavailable and verified by schema tests.

R04-06 measurements from computed styles: GET text white on rgb(97,175,254), **2.31:1** at 14px; OpenAPI link rgb(73,144,226) on white, **3.30:1**; Expand all rgb(175,174,174) on rgb(239,239,239), **1.92:1**. The OpenAPI link measured 14px high, expand controls about 16px, summary controls about 28px, below the project's 44px target preference. At 390px the response table wraps examples heavily and its media selector is narrow, but the page remains navigable. These third-party developer-tool limitations prevent a compliance claim; production `/api/v1/docs` and OpenAPI remain disabled and tested as 404. No screen-reader certification, non-Chromium result or Swagger axe certification is claimed.

Revision 0001 was not edited or replaced. Revision 0002 preserves historical evaluations; it guards new pass insertions against current persisted scan metadata. A future live gate reader must still account for current execution state and deterministic policy, and a future authenticated dependency must validate tenant/project permissions before constructing an internal scope. There are no scan targets contacted, AI calls, messages or report deliveries in this review. Fixtures remain synthetic. Two existing Starlette/httpx and AnyIO deprecation warnings remain; no dependency changes were introduced.

Final post-example verification: the rebuilt-image backend command above passed **50 tests in 24.35 seconds** (two existing deprecation warnings). The final `make UV=/tmp/aegis-tools/uv lint typecheck schema-check` with the documented Node/uv environment prefixes passed, followed by `UV_CACHE_DIR=/tmp/aegis-uv-cache /tmp/aegis-tools/uv run --project apps/api pytest -c apps/api/pyproject.toml apps/api/tests -m 'not integration'` (**15 passed**) and `UV_CACHE_DIR=/tmp/aegis-uv-cache /tmp/aegis-tools/uv build --project apps/api` (wheel/sdist built). No executable changes followed these checks.

`sg docker -c 'make compose-config'` passed development/production/scanner isolation assertions. `sg docker -c 'docker compose -p aegisforge-phase4-review -f docker-compose.yml -f docker-compose.test.yml down --volumes --remove-orphans'` removed only the review project's containers, volumes and networks. The temporary localhost API process was stopped; the browser viewport override was reset and the review tab closed. Other development data was preserved. Final review scope remains Phase 4 only.

## Phase 5 — authentication, organizations, RBAC and onboarding — 2026-09-07

Implemented the explicitly requested phase. No scanner execution, external mail transmission, deployment or next-phase work was performed. No subagents were used. The reference screenshot was unavailable; desktop/mobile screenshots were inspected against the written requirements and existing AegisForge design system.

### Changes and decisions

Added `auth.py`, `auth_models.py`, `organizations.py`, migration `0003`, and `test_auth.py`; updated user verification metadata, API lifespan/routes/settings, Alembic registration and generated schema documents. Added `product/Auth.tsx`, `Workspace.tsx`, `client.ts`, `product.css`, auth browser tests and routes. Updated public registration CTAs, Vite/nginx API proxies, Compose identity configuration, the disposable browser runner/Make target and CI. README, decisions, phase status, API contract, test matrix, `.env.example` and AUTHENTICATION operations are current. Existing dependency locks remain unchanged because no new dependencies were needed.

Opaque access/refresh values are random and hashed at rest. Salted scrypt, user-row serialized session rotation/reset, family replay revocation, single-use recovery, exact-Origin/CSRF protection and Redis rate counters enforce identity boundaries. Tenant membership is checked live; organization locks protect role/deactivation/ownership changes. Existing tenant/project records determine resource visibility and onboarding; only completed, complete baseline scans satisfy the scan step. Active GitHub integration state determines the CI step. Details and limitations are in ADR-023 and AUTHENTICATION.

### Commands and results

The environment uses Node 24 from `/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin` and uv/Compose from `/tmp/aegis-tools`; `UV_CACHE_DIR=/tmp/aegis-uv-cache`. Docker commands used `sg docker` to activate existing group membership. FastAPI TestClient/browser execution and Python build dependency access required approved sandbox escalation.

| Command                                                                                                                                     | Final result                                                                                                                                                                               |
| ------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `PATH=<Node24>:/tmp/aegis-tools:$PATH UV_CACHE_DIR=/tmp/aegis-uv-cache make check build`                                                    | PASS: Prettier, ESLint, Ruff formatting/lint, strict TypeScript/mypy, 20 frontend unit tests, 16 backend unit/security tests, schema drift, Vite production build and API sdist/wheel      |
| `sg docker -c '/tmp/aegis-tools/docker-compose -p aegis-phase5 -f docker-compose.yml -f docker-compose.test.yml run --rm --build api'`      | PASS: 49 integration tests, including 14 Phase 5 cases and 35 existing database/infrastructure/review cases; fresh migrations, downgrade/re-upgrade and metadata parity                    |
| Same isolated Compose runner with current `apps/api/src` and `apps/api/tests` mounted read-only; `pytest -m integration tests/test_auth.py` | PASS: final 15 Phase 5 integration cases, including the added positive baseline/CI progress test. Together with unchanged existing integration cases, 50 distinct integration cases passed |
| `sg docker -c 'PATH=<Node24>:/tmp/aegis-tools:$PATH make test-auth-e2e COMPOSE=/tmp/aegis-tools/docker-compose'`                            | PASS: all 4 real-backend Chromium journeys; fresh isolated API/PostgreSQL/Redis migrations and automatic resource cleanup                                                                  |
| `pnpm --filter @aegisforge/web test-e2e`                                                                                                    | PASS: 56 public/design-system Chromium tests; 4 auth tests deliberately skipped here and passed separately in the dedicated real-backend run                                               |
| `COMPOSE=/tmp/aegis-tools/docker-compose python3 scripts/check_compose.py`                                                                  | PASS: development/production configuration, private infrastructure networks, opt-in digest-pinned disconnected scanner                                                                     |
| Final changed-file formatting, backend Ruff/mypy and Compose checks                                                                         | PASS after final GitHub onboarding filter and runtime setting forwarding                                                                                                                   |

Exact current-source authentication invocation:

```sh
sg docker -c '/tmp/aegis-tools/docker-compose -p aegis-phase5 -f docker-compose.yml -f docker-compose.test.yml run --rm -v /home/akshat/Desktop/aegis-4th-year/apps/api/src:/app/src:ro -v /home/akshat/Desktop/aegis-4th-year/apps/api/tests:/app/tests:ro api pytest -m integration tests/test_auth.py'
```

### Failures corrected during implementation

Initial integration failures were five UUID JSON serialization mistakes in tests, corrected before successful reruns. Existing convention tests were updated for the new OpenAPI version/route set and 28-table metadata. Browser runs caught duplicate sibling keys, indistinguishable sidebar/checklist landmarks, an exact-text selector that included a status glyph, and form filling before a route transition completed. Keys/landmarks were corrected and browser tests now wait for the destination heading. The final isolated auth run passed all four flows. A passwordless-account review also added explicit denial even if the dummy comparison happens to match. Missing filesystem/network capabilities initially stalled TestClient and blocked the Python build backend download; approved execution completed both. An intermediate format gate preceded formatting of the updated E2E test; the completed gate passed. These failures are not counted as passes.

### Visual and security review

Inspected full-page screenshots at 1280px desktop and 390px mobile. Desktop has a compact fixed sidebar, cyan active navigation, organization header, three cards and right checklist. Mobile uses stacked cards/checklist with a keyboard-closeable drawer. Axe reported zero violations on the authenticated onboarding page after landmark correction. Registration/login/logout, protected reload bootstrap, organization creation/switching, live progress refresh, desktop collapse and mobile drawer flows were browser-automated. This is not human assistive-technology or cross-browser certification.

API coverage includes real foreign organization/project/target IDs, all role decisions for mounted organization endpoints, assigned-project reads, immediate deactivation, invite email binding/single use, ownership transfer, reset expiry/single use/all-session revocation, access expiry, secure cookie flags, generic recovery/failure messages, Redis throttling, CSRF and simultaneous refresh replay revoking the winning family. Future scanner/policy/integration mutation routes do not exist; their shared action policy is unit-tested rather than claimed as endpoint-tested.

SMTP delivery was not exercised against an external provider. A configured mail service is required to receive verification, recovery and invite links; unconfigured delivery is recorded without exposing tokens. Durable mail retries, project/target CRUD, scanner execution, policy evaluation and full report workflows remain deferred. Existing Starlette/AnyIO deprecation and Node color-environment warnings remain non-failing.

### Cleanup

The dedicated E2E command removed its uniquely named containers/networks/volumes. The manually started API was stopped, and `sg docker -c '/tmp/aegis-tools/docker-compose -p aegis-phase5 down --volumes --remove-orphans'` removed only the Phase 5 synthetic integration services and volumes. No existing development data was deleted. Screenshot artifacts remain under `/tmp/aegis-phase5-workspace.png` and `/tmp/aegis-phase5-mobile.png`; they are not committed product assets.

Final result: Phase 5 PASS. The complete general browser run finished with **56 passed / 4 intentionally skipped** in 3.7 minutes; the dedicated auth runner had **4 passed** in 40.7 seconds. `UV_CACHE_DIR=/tmp/aegis-uv-cache uv build --project apps/api --offline` successfully rebuilt the final API source as an sdist and wheel. Final formatting/type/Compose checks passed after runtime-setting forwarding and the CI production-origin override. Stop at Phase 5.

## Phase 6 strict review — 2026-09-08

Reviewed the explicit Phase 6 prompt, the working-tree diff against `f7d82a2`, new/untracked implementation files, migration 0004, response schemas, existing/new tests and PHASE6_TEST_REPORT. No ZAP process or next-phase implementation was started.

### Confirmed defects fixed

- OpenAPI sanitization treated API/schema names as metadata: properties named `default`, `description`, `example`, `enum`, `servers` or `x-field`, and default responses, could disappear. The sanitizer now distinguishes named maps, validates the original document after reference/depth preflight, and validates the sanitized result. Malformed original fields cannot become acceptable through redaction. A nested property named `components` cannot hide an external reference from preflight; its regression asserts that the schema validator is never called.
- Archived projects prevented credential revocation and target deactivation. Those actions now remain available with the same tenant, project-membership and role checks. New configuration remains prohibited while archived.
- Failed navigation/refetch could leave the previous target visible. Loaded data and errors are now bound to their request path, and failed loads clear stale data.
- Request buffering retained one object per chunk and replayed with quadratic list removal. It now accumulates the bounded bytes and replays one body. A 10,000-fragment regression verifies this behavior.
- Legacy policy detail could reach an incompatible response schema and fail with 500. It now returns 409; preset initialization creates a current immutable version without rewriting the legacy row.
- The configuration primary-link hover inherited mint text on mint background (axe measured 1.12:1). A scoped hover foreground restores the dark button text.

Added failure-path coverage for timeouts, TLS failures, server errors, missing redirect destinations, downgrade redirects, redirect loops, unsupported content types, compressed responses, oversized fetched documents, malformed original OpenAPI, foreign-target/credential mutations, foreign authorization owners, missing encryption keys and archived-project revocation. Existing SSRF address/rebinding/redirect, RBAC, secret-redaction, policy immutability and migration integration cases remain in the full suite.

### Browser inspection

The real-backend setup test passed all four widths (390, 768, 1280, 1440px) for 13 states: project list, new project, project overview, project settings, policy list, active policy editor, target list, wizard Basics/Scope/Authentication, failed Review, validated Review and target detail. All 52 axe/overflow checks passed. Full-page screenshots and four-width contact sheets were visually inspected; no clipping or horizontal page overflow was observed. Active warnings, masked authentication, wrapped actions, empty states and backend rejection feedback remain visible. Policy detail reuses the inspected editor; a separate detail-route screenshot was not captured.

The journey rejects a loopback URL even under an internal-test policy, keeps registration disabled, resets consent after editing, validates the corrected synthetic fixture, saves an OpenAPI target with encrypted authentication, revokes its credential, edits project settings, and archives/restores the project. No real target was scanned. Captures are `/tmp/phase6-review-{state}-{width}.png`, with contact sheets `/tmp/contact-{state}.png`; these temporary artifacts are not committed baselines.

### Failed/intermediate checks

The first browser run reproduced the contrast defect (4 passed, setup failed); the corrected run passed all 5 in 2.5 minutes. The first combined quality run hit the existing wizard test's five-second timeout during concurrent image building; using zero artificial per-keystroke delay made the focused test and complete 22-test frontend suite pass. Ruff also caught and fixed one new test import-order issue.

One new rollback assertion initially used the shared-session test dependency, which deliberately lacks production request rollback. The corrected test exercises the production session dependency and passes; no production transaction workaround was added. The first legacy-policy fixture attempted an UPDATE and was correctly rejected by the immutability trigger; the corrected fixture inserts a legacy record. A malformed TLS exception in a test double was also corrected. These are test-fixture failures, not evidence of application success or additional production defects.

### Final verification commands and results

The environment uses bundled Node and uv/pnpm tools. `sg docker` activates existing Docker group membership; it does not change socket or system permissions. Test commands requiring subprocess/network permissions ran outside the filesystem sandbox against disposable services.

```sh
PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/tmp/aegis-tools:$PATH UV_CACHE_DIR=/tmp/aegis-uv-cache make check build
sg docker -c '/tmp/aegis-tools/docker-compose -p aegis-phase6-review -f docker-compose.yml -f docker-compose.test.yml run --rm --build api'
sg docker -c '/tmp/aegis-tools/docker-compose -p aegis-phase6-review -f docker-compose.yml -f docker-compose.test.yml run --rm --no-deps -v /home/akshat/Desktop/aegis-4th-year/apps/api/src:/app/src:ro -v /home/akshat/Desktop/aegis-4th-year/apps/api/tests:/app/tests:ro api pytest'
sg docker -c 'PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/tmp/aegis-tools:$PATH COMPOSE=/tmp/aegis-tools/docker-compose make test-auth-e2e'
PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/tmp/aegis-tools:$PATH make test-e2e
COMPOSE=/tmp/aegis-tools/docker-compose python3 scripts/check_compose.py
PATH=/tmp/aegis-tools:$PATH UV_CACHE_DIR=/tmp/aegis-uv-cache uv run --project apps/api ruff check apps/api
PATH=/tmp/aegis-tools:$PATH UV_CACHE_DIR=/tmp/aegis-uv-cache uv run --project apps/api mypy --config-file apps/api/pyproject.toml apps/api/src
PATH=/tmp/aegis-tools:$PATH UV_CACHE_DIR=/tmp/aegis-uv-cache uv build --project apps/api
sg docker -c '/tmp/aegis-tools/docker-compose -p aegis-phase6-review -f docker-compose.yml -f docker-compose.test.yml down --volumes --remove-orphans'
git diff --check
```

`make check build` passed Prettier, ESLint, Ruff check/format, strict TypeScript, mypy (22 source files), 22 frontend tests, the then-current 97 backend unit/security tests, generated-schema drift checks, and web/API package builds. After the final reference-preflight regression, Ruff, mypy and API packaging passed again; the final complete backend run used read-only source/test mounts with locked image dependencies and passed **161 tests in 89.48 seconds: 98 unit/security and 63 integration**. Do not add overlapping local/container counts. Existing Starlette/httpx and AnyIO deprecation warnings remain.

Real-backend Playwright: **5 passed in 2.5 minutes**, including 52 Phase 6 axe/overflow combinations. Compose dev/prod/isolation assertions passed and the scanner configuration remains opt-in with no network or published ports. The browser runner removed its disposable stack automatically. The separate integration review stack was removed with the command above; existing application data was preserved.

### Non-blocking limits and handoff

Configuration lists are capped at 200 records without cursor pagination. Browser coverage is Chromium plus axe and visual inspection; direct screen-reader testing, other engines and remote CI are unclaimed. Local encrypted credentials are development/test only and require a stable configured key; the production managed-secret adapter and OAuth implementation are explicitly future interfaces. Executor-time scope/egress checks, active one-use confirmation and ZAP execution remain requirements of later authorized phases, not capabilities claimed by this configuration phase.

The earlier `git add` attempt failed because protected `.git/index.lock` is read-only. No commit was created, and protected Git metadata/permissions were not changed. This is a handoff limitation, not an application defect. No next phase was started.

### Final verdict

**CONDITIONAL PASS — safe to begin the next explicitly authorized phase.** All confirmed Phase 6 blockers above are fixed and covered by passing regressions.

The general `make test-e2e` run finished with **55 passed, 1 failed, 5 skipped in 5.0 minutes**. The failure was the unchanged component-lab `ui fits 1280` case: its `h1` was not found within five seconds after navigation. The five skipped real-backend cases passed separately above. The exact isolated rerun command was:

```sh
PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/tmp/aegis-tools:$PATH pnpm --filter @aegisforge/web test-e2e --project=labs --grep 'ui fits 1280' --repeat-each=3 --workers=1
```

All **3 repetitions passed in 23.0 seconds**, with each test taking 1.1 seconds. No lab implementation, timeout or assertion was changed. The intermittent load timeout's cause remains unconfirmed and is a non-blocking test limitation; the original full run is not relabeled as green. All 56 distinct general browser cases have passing evidence across the run and targeted reruns. All 119 public route/width axe checks passed in the general run.

Final documentation formatting, backend formatting and `git diff --check` passed. A Docker label-filtered container query returned no integration-review containers after teardown. Review changes are confined to the six defect areas listed above, their unit/integration/browser regressions, CONFIGURATION, PHASE6_TEST_REPORT, PHASE_STATUS and this report. No dependencies, schema migration or next-phase behavior were added by the strict review.

## Phase 7 — 2026-09-08

See [PHASE7_TEST_REPORT](PHASE7_TEST_REPORT.md) for mock-only orchestration verification, exact commands, intermediate failures/corrections, real Celery/SSE browser evidence, process-kill/Redis failure checks, screenshots, cleanup and limitations. No real ZAP or later phase was started.

## Phase 8 — 2026-09-09

See [PHASE8_TEST_REPORT](PHASE8_TEST_REPORT.md) for isolated ZAP verification, exact commands, actual passive/authorized-active/OpenAPI fixture scans, timeout/cancellation/crash/cleanup, denied canary traffic, redaction, immutable PostgreSQL records and the mock browser regression. The report distinguishes the full live run's two DNS-startup failures from the passing affected rerun. No internet scan, deployment or later phase was started.

## Phase 8 strict review — 2026-09-09

### Review scope and confirmed blockers

Reviewed the explicit Phase 8 requirements, current tracked diff and untracked Phase 6–8 implementation files, scanner contracts, dispatch/coordinator authorization, worker admission, Docker/gateway isolation, artifact persistence/migration, tests and PHASE8_TEST_REPORT. Preserved prior uncommitted work. Rechecked current official [Docker guidance](https://www.zaproxy.org/docs/docker/about/), [network API](https://www.zaproxy.org/docs/desktop/addons/network/api/), [spider depth semantics](https://www.zaproxy.org/docs/desktop/addons/spider/options/) and [AJAX API](https://github.com/zaproxy/zap-api-python/blob/main/src/zapv2/ajaxSpider.py).

Confirmed and fixed these Phase 8 blockers:

1. Path exclusions accepted ambiguous repeated slashes, encoded slashes and semicolon traversal forms that servers can normalize differently. The gateway now rejects these forms before any upstream connection. Real HTTP/TLS destination-assertion tests cover the bypass inputs.
2. Rate reservations remained usable after authorization/deadline expiry; a slow request body could also delay sending beyond authorization. The gateway now rechecks its lease/deadline after rate waits and body reads. Tests cover both lease and time expiration, with an assertion that no upstream socket is opened.
3. Rejected transfer/upgrade framing could leave an earlier successful gateway statistics file unchanged. All such failures now persist the failure flag, and statistics use atomic replacement under the budget lock to prevent torn concurrent reads.
4. Recursive directory creation applied mode 0700 only to the leaf. The artifact root, organization and scan directories are now explicitly secured at 0700; object files remain 0600 and write-once.
5. Redaction removed full authorization values but could retain standalone Bearer tokens or decoded Basic passwords. It now redacts credential components and encoded variants. New receipts identify `zap-redaction-v2`, retaining compatibility with historical version 1 receipts.
6. Crawl policies were not faithfully enforced: URL `spider=none` still crawled, zero depth became ZAP's unlimited-depth sentinel, and AJAX ignored the policy depth. Incompatible no-crawl/zero-depth URL policies now fail before startup; both URL crawlers receive positive policy depth. No-crawl OpenAPI import remains supported.
7. Requested active rule IDs were never checked against the installed inventory. Missing rules now fail rather than allowing an apparent successful active stage without the requested rule. The scanner inventory response is Pydantic-validated.

The first seven new regressions reproduced blockers 1–4, two further tests reproduced blocker 5, and four policy tests reproduced blockers 6–7. Two additional slow-body expiry tests cover the corrected send boundary. These 15 added cases plus the earlier 47 scanner cases passed as **62 focused tests**. During the redaction fix, the existing custom-pattern test caught an accidental local-variable overwrite; this was corrected before the passing rerun. No failed reproduction is counted as a pass.

Changes are confined to `zap/gateway.py`, `zap/artifacts.py`, `zap/contracts.py`, `zap/provider.py`, scanner tests and review/setup documentation. No new dependency, schema migration, UI feature or next-phase behavior was introduced. Existing tenant-scoped immutable artifact/dispatch integration remains tested; failed/partial collection still cannot produce a passing gate.

### Commands

From the repository root, with the bundled Node runtime and `/tmp/aegis-tools` on PATH and `UV_CACHE_DIR=/tmp/aegis-uv-cache`:

```sh
make lint typecheck test schema-check build
apps/api/.venv/bin/pytest -c apps/api/pyproject.toml apps/api/tests/test_phase8_review.py apps/api/tests/test_zap.py -q
pnpm --filter @aegisforge/web test --maxWorkers=1
make lint typecheck schema-check build
sg docker -c 'docker build -f apps/api/Dockerfile.scanner -t aegisforge-scanner-worker:phase8 .'
sg docker -c 'python3 scripts/check_compose.py'
sg docker -c 'docker compose -p aegis-phase8-review -f docker-compose.yml -f docker-compose.test.yml run --rm --build api pytest -q'
sg docker -c 'docker compose -p aegis-phase8-review -f docker-compose.yml -f docker-compose.test.yml run --rm -v /home/akshat/Desktop/aegis-4th-year/apps/api/src:/app/src:ro -v /home/akshat/Desktop/aegis-4th-year/apps/api/tests:/app/tests:ro api pytest -q'
sg docker -c 'AEGIS_RUN_ZAP_LIVE=1 apps/api/.venv/bin/pytest -c apps/api/pyproject.toml apps/api/tests/test_zap_live.py -v --tb=short'
sg docker -c 'PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/tmp/aegis-tools:$PATH python3 scripts/test_auth_e2e.py scans.spec.ts --workers=1'
```

The first combined check encountered the deliberately added failing security regressions. After fixes, another combined run stopped on an unchanged configuration unit test's five-second timeout (**24 passed, 1 timed out**); all **25 frontend tests passed** on the one-worker rerun without changing its timeout or assertions. Concurrent machine load is a possible cause, not a proven diagnosis. Static checks and builds were run separately after that interruption. The original combined run is not relabeled green.

### Responsive and accessibility review

The real-backend mock scan browser journey passed **1/1 in 2.7 minutes**. It exercised PostgreSQL/Redis/Celery, SSE replay and reconnect, cancellation and non-passing completion. It performed **36 successful axe/overflow checks across nine states at 390, 768, 1280 and 1440px**. Inspected current screenshots/contact sheets at all four widths, including wizard, consent, final review, running timeline, history and cancellation; no additional layout blocker was found. Screenshot names retain the existing test prefix `/tmp/phase7-review-{state}-{width}.png`; review sheets are `/tmp/phase8-review-ui-{width}.jpg`.

This is Chromium/axe plus visual inspection, not a human screen-reader or other-engine certification. No product UI changed in Phase 8 or this review. Browser orchestration uses the mock provider; actual ZAP and the API/database dispatch/artifact handoff are verified separately. No browser-to-real-ZAP journey or full HTTPS ZAP scan is claimed; the gateway has real loopback TLS scope tests.

### Verified review results

Final full backend: **247 passed, 8 opt-in live skips in 150.00 seconds**, including PostgreSQL/Redis integration, tenant denial, migration/immutability and all 15 new review regressions. The live skips are exercised separately. Earlier full runs passed 232 and then 243 cases before the later policy regressions; these overlapping counts are not added together. The final focused scanner suite passed **62/62**. Two existing upstream Starlette/AnyIO deprecation warnings remain.

Final Prettier/ESLint/Ruff formatting and lint, strict TypeScript/mypy, schema drift, Vite production build, API wheel/source distribution, scanner image build and Compose isolation assertions passed. No timeout/assertion was relaxed. Frontend results and the intermediate timeout are recorded above. The seven-case real ZAP suite passed **7/7 in 492.28 seconds** after the gateway/artifact fixes; it began before the final crawl/rule-policy checks, so those receive an additional targeted run below.

### Resumed AJAX verification

The previous review was interrupted for the user's local preview request. The final AJAX mount rerun had no retained result when review resumed, so it was rerun rather than assumed successful. The prior real active rerun passed after the inventory check. AJAX first exposed a false collection success with zero browser observations; a new regression now requires failure and cleanup in that case. Filtered fixture diagnostics identified read-only Firefox profile storage and non-executable bundled WebDriver storage. Bounded profile/WebDriver mounts were added without relaxing the read-only root, capabilities, network isolation or CPU/memory limits.

On resumption, Ruff/format/mypy and **63 focused scanner tests passed**, the scanner image rebuilt, and the final full backend run passed **248 tests, 8 opt-in skips, 2 existing upstream warnings in 77.88 seconds**. The additional case is the zero-observation AJAX failure regression; no overlapping run counts are added. The mounted-browser AJAX rerun still failed closed with `scanner_discovery_failed` after 196.93 seconds, so AJAX remains under investigation at this checkpoint. No passing AJAX result is claimed here.

The remaining AJAX failure was isolated without disabling Firefox sandboxing or relaxing egress. Firefox reported no writable font cache; `XDG_CACHE_HOME=/tmp/browser-cache` now uses the existing bounded temporary filesystem. The subsequent run intermittently lost Docker control execution. Runtime measurement showed **256 processes at the 256-process ceiling and approximately 888 MiB of a 2 GiB memory limit**, with no Docker OOM event. ZAP's process ceiling is now a bounded **512** to accommodate Firefox and control processes; the gateway stays at 256. CPU/memory limits, dropped capabilities, no-new-privileges, read-only root, private API and network allowlist remain enforced. A resource-observation rerun passed AJAX **1/1 in 84.11 seconds**, proving positive browser observations. Permanent tests assert the cache and process arguments and reject a stopped AJAX spider with zero observations. Temporary diagnostic logging was removed.

The diagnostic-only run was interrupted after its useful evidence was collected. Automatic approval review rejected an initially proposed broad label-filter cleanup because it might include unrelated scanner jobs. Read-only inspection identified the exact remaining gateway `aegis-zap-5da6cf0a-1828-49c4-8582-e8a46efa3fed-gateway` and its two unique networks; only those verified leftovers were then removed successfully. The application containers, account and persistent application data were not touched.

Final resumed commands (the same repository-root environment and Docker group wrapper apply):

```sh
apps/api/.venv/bin/ruff check apps/api
apps/api/.venv/bin/ruff format --check apps/api
apps/api/.venv/bin/mypy --config-file apps/api/pyproject.toml apps/api/src
apps/api/.venv/bin/pytest -c apps/api/pyproject.toml apps/api/tests/test_zap.py apps/api/tests/test_phase8_review.py -q
apps/api/.venv/bin/python -m aegis_api.schema_docs --check
pnpm exec prettier --check .
pnpm --filter @aegisforge/web typecheck
sg docker -c 'docker build -f apps/api/Dockerfile.scanner -t aegisforge-scanner-worker:phase8 .'
sg docker -c 'python3 scripts/check_compose.py'
sg docker -c 'AEGIS_RUN_ZAP_LIVE=1 apps/api/.venv/bin/pytest -c apps/api/pyproject.toml apps/api/tests/test_zap_live.py -k "ajax or network" -v --tb=short'
```

Final resumed Ruff/format/mypy and **63/63 focused tests passed in 8.19 seconds** after the process-ceiling change. Schema drift, Prettier, strict TypeScript and Compose assertions passed. The final worker image built successfully, including installation of the current API package. The earlier Vite/API-distribution builds and browser/25-case frontend results remain recorded above; no frontend code changed during the resumed AJAX work. The 248-case backend run preceded only the final runtime cache/process-argument adjustments, which the focused suite and real execution rerun cover.

### Final strict-review verdict

Credential verification clarification: the local worker's real Fernet decryption, organization/reference binding rejection and authorization replacement arguments were exercised by `test_secrets_worker_scope_and_redaction` using `FakeRuntime`. Local secret encryption/production refusal and credential-component redaction have separate tests. Real Docker scans supplied no credential references: delivery of authentication headers through real ZAP, and the complete persisted-reference-to-authenticated-target journey, remain unverified. The worker currently decrypts local ciphertext directly; the seal/open protocol is not an implemented cloud retrieval adapter. KMS/Secrets Manager, IAM, key rotation/recovery and cloud error handling are absent, not merely pending tests. Local encrypted artifact export/decryption was exercised live; PostgreSQL metadata immutability and tenant denial were exercised separately. S3 and automated retention are absent.

**CONDITIONAL PASS — safe to begin the next explicitly authorized phase.** The final real execution rerun passed **2/2 in 127.80 seconds**: AJAX with positive browser observations, and direct-route/foreign-canary denial plus lost-worker-lease cleanup. Together with the earlier corrected runs, all **eight distinct live scenarios have passing evidence across runs**; this is not a claim that one eight-case run passed. No internet target was scanned. The earlier AJAX investigation checkpoint above is superseded by this result.

All confirmed review blockers are fixed, including scope normalization, deadline/lease enforcement, durable gateway failure statistics, artifact permissions, credential-component redaction, crawl/rule policy enforcement and false AJAX success. Failure, cancellation and partial collection continue to produce no passing gate or fabricated downstream findings.

Exact non-blocking limitations: production credential references still need the managed-secret adapter; local encrypted artifact storage needs operator key provisioning and retention enforcement and has no S3/download lifecycle. Production execution requires a dedicated/rootless daemon. Full browser-to-ZAP and full HTTPS ZAP journeys remain unverified; actual isolated AJAX is verified. Browser review covers Chromium/axe/visual inspection, without a human screen-reader or other-engine certification. The default-parallel frontend timeout has an unconfirmed cause, with all 25 cases passing unchanged in the one-worker rerun. Two upstream backend deprecation warnings remain. Protected read-only Git metadata prevented the previously attempted commit; no permissions were changed and no commit is claimed.

Cleanup: automatic approval review rejected `docker compose ... down --volumes --remove-orphans` because volume/orphan deletion could affect persistent data. The safer `sg docker -c 'docker compose -p aegis-phase8-review -f docker-compose.yml -f docker-compose.test.yml stop'` succeeded; review containers and volumes were preserved. A subsequent `docker ps` returned no running containers, and `ss -ltnp '( sport = :5173 or sport = :5174 or sport = :4173 or sport = :8000 )'` showed no listeners. Application account data remains preserved. No deployment or next-phase work was started.

## Phase 8 Git handoff clarification — 2026-09-09

The earlier commit blocker was the execution sandbox’s read-only rule for `.git`, not incorrect Unix ownership or a stale lock. Explicitly authorized escalated Git staging succeeded without changing filesystem permissions or repository configuration. The commit records the complete verified Phase 6–8 working state because HEAD previously stopped at Phase 5; see [commit inventory](PHASE8_COMMIT_MANIFEST.md) for its exact file scope. Earlier statements that a commit remains blocked are superseded by this handoff once the commit is verified. No Phase 9 work is included.

Secret verification is limited to real local worker decryption with a fake scanner runtime, separate configuration/redaction tests, and unauthenticated live scans. Authenticated real-ZAP delivery and a full saved-reference-to-target journey are not claimed. Cloud secret adapters and cloud artifact lifecycle are unimplemented. See [scanner verification boundary](SCANNER.md) for details.

Fresh pre-commit verification: the focused scanner command initially produced **58 passed, 5 failed** because the workspace sandbox denied socket creation (`PermissionError: Operation not permitted`) before the loopback fixtures could start. The identical command with approved loopback access passed **63/63 in 6.36 seconds**: `apps/api/.venv/bin/pytest -c apps/api/pyproject.toml apps/api/tests/test_zap.py apps/api/tests/test_phase8_review.py -q`. Documentation Prettier and Git whitespace checks passed. No implementation changes were made during this clarification.

## Phase 10 live Gemini follow-up — 2026-09-10

**Live success criterion not met.** A key became available after the earlier no-key check. It was found in the tracked environment template and moved to ignored `.env`; the template was restored without committing or displaying the credential. Runtime model is `gemini-2.5-flash` (Flash, not Pro). Global provider enablement remains off.

The original local database had no retained findings/artifacts. A fresh real passive ZAP **2.17.0** scan ran against the owned, isolated Phase 8 fixture; it returned 32 real alerts. A disposable database was migrated to head and the actual artifact was normalized/persisted. Exactly one finding was selected: `04a5115c-b9d1-4977-bba7-5113648290b0`, scanner rule `10021`, occurrence `75c77578-4a96-4acc-8159-4dac906b3d8b`. Raw encrypted artifact SHA-256: `a65121c99afe05e8040a43dc32f34ae69f4205d19d0caa1a20ae5d94d8a277a5`.

The authenticated, CSRF-protected API enrichment POST made three bounded provider attempts and returned HTTP 200 with **`status=degraded`**, `failure_code=provider_or_validation_exhausted`. HTTP 200 is not generation success. No model text was received. One additional, non-retrying diagnostic call using that same finding's real scanner classification and occurrence ID reached Google and returned **HTTP 400 ClientError**, not 429. Its exact upstream rejection reason was not retained; no cause such as invalid credentials or schema incompatibility is asserted. There were **four provider invocations total, one finding, no batch**. The diagnostic harness initially had a local field-name error, corrected before its provider call. No further live request was made.

Input checks confirmed the provider prompt excluded the configured key, fixture cookie-secret canary and account email. The API retained one degraded analysis, with scanner severity/state/version/normalized data unchanged and no policy evaluation created. **Structured-output validation, evidence citation acceptance and output redaction against real model text remain unverified**, because no model text was returned. Synthetic security tests cannot substitute for that result. The scan was deliberately recorded partial; no passing gate was inferred. Disposable database/Redis/target containers and network were removed; temporary encrypted artifacts and safe result metadata remain under `/tmp/aegis-phase10-live` (outside Git). The original database was not migrated or populated by this harness.

Confirmed/fixed before live execution: 429 had previously shared generic failure retries. It now has a distinct safe exception, exponential 15/30-second backoff with jitter, Retry-After/RetryInfo handling, a 60-second cumulative wait limit, daily-quota detection and distinct persisted exhaustion/deferred codes. SDK retries remain disabled. No upstream message or invalid model output is stored/logged. Tests cover recovery, exhaustion, deferred long waits, daily quota, SDK 429 translation and retained degraded records with unchanged findings.

Actual follow-up verification:

- `apps/api/.venv/bin/ruff check apps/api` and `ruff format --check apps/api`: passed (69 files).
- `apps/api/.venv/bin/mypy --config-file apps/api/pyproject.toml apps/api/src`: passed (39 source files).
- `sg docker -c 'apps/api/.venv/bin/python /tmp/aegis_ai_verify.py'`: **72 passed in 6.62 seconds**, running `pytest -c apps/api/pyproject.toml apps/api/tests/test_ai.py apps/api/tests/test_ai_routes.py -q` against a disposable PostgreSQL database.
- `sg docker -c 'apps/api/.venv/bin/python /tmp/aegis_live_gemini_one.py'`: real scanner/API failure-preservation checks passed; live generation degraded as detailed above.
- `apps/api/.venv/bin/python /tmp/aegis_gemini_diagnose.py` with approved network access: same-finding diagnostic returned HTTP 400.

No frontend changes: prior responsive, accessibility, frontend unit/build and E2E results remain historical, not rerun results for this follow-up. Phase 10 stops here; do not mark live Gemini validation complete.

Final follow-up checks: documentation Prettier and `git diff --check` passed; credential-value checks found no configured key in tracked changes. API source/wheel build passed with `/tmp/aegis-phase10-tools/bin/uv build --offline` from `apps/api` using approved cache access. Earlier build attempts were blocked by a cache lock restriction, then used an incorrect repository-root workspace flag; neither is counted as a passing build. Original PostgreSQL/Redis services started for this check were stopped with containers/volumes preserved. The six-file follow-up is committed using authorized Git escalation without ownership/permission changes; no push or deployment.

## Phase 10 Gemini deadline correction — 2026-09-10

Temporary same-finding diagnostics established the exact HTTP 400 rejection: `Manually set deadline 8s is too short. Minimum allowed deadline is 10s.` (`INVALID_ARGUMENT`). The SDK timeout in `ai.py` is now **15,000 ms** and the enclosing application attempt deadline **16 seconds**, so it cannot cancel the request at the previous nine-second boundary. SDK serialization tests assert the corrected 15-second transport setting. Retry counts, 429 handling, strict schema/citation/URL validation and redaction are unchanged; no diagnostic logging was added to the codebase.

The earlier disposable database was removed, so this rerun reconstructs the AI input from the retained encrypted real ZAP artifact after verifying its SHA-256. The four observations for rule `10021` have three route fingerprints but **one identical AI input**: routes are withheld. The original finding ID `04a5115c-b9d1-4977-bba7-5113648290b0` and evidence ID `75c77578-4a96-4acc-8159-4dac906b3d8b` are reused in an isolated replay database. This verifies the same real classification payload through the authenticated API, not restoration of the deleted original database or identification of its original route. No new target scan or batch enrichment was performed.

The first corrected-timeout request made three provider attempts and retained a degraded version: one real model text reached validation but was rejected. Its specific validation reason was not retained. Scanner values remained unchanged. This intermediate run is not counted as successful live validation.

A second same-input request captured three real responses, all rejected on revalidation with `Invalid IPv6 URL`. Temporary diagnostics proved the raw structured output passed the strict schema; the generic long-token masker transformed the allowed `https://cwe.mitre.org/data/definitions/693.html.` into malformed bracketed host syntax. Confirmed blocker fixed: after masking, any URL containing a redaction marker is withheld entirely as `[REDACTED URL]`. This does not exempt URL contents from privacy checks or relax either validation pass. A permanent regression covers this exact public CWE URL. All three retained real responses then passed offline validation unchanged through the fixed pipeline.

**Final live result: PASS**, at 2026-09-10 16:52 UTC. `sg docker -c 'apps/api/.venv/bin/python /tmp/aegis_gemini_timeout_verified.py'` made one authenticated enrichment POST for the same retained real-finding input, with **one real Gemini attempt** (no mock transport). The API returned HTTP 200, **`status=complete`**, null failure code, analysis ID `8fe5019b-7218-4004-9dc3-10db4cdc4fe3`. Independent `validate_output` on the actual SDK-returned text exactly matched the persisted/API output. Evidence citations matched only the supplied occurrence. The prompt and accepted output contained none of the configured key, fixture secret or account canaries; accepted output passed redaction idempotence and hypothesis-label checks. This demonstrates the deployed masking boundary on real output, not detection of every possible secret/PII class. One completed version was retrieved; scanner severity/state/version/data stayed unchanged and no policy evaluation was created.

There were **seven provider attempts across three same-input API requests during this deadline-fix work** (3 degraded, 3 diagnostic/degraded, 1 complete), not a batch of findings. The final run alone is the one-attempt success. All temporary services were removed. Safe result metadata and validated guidance remain in `/tmp/aegis-phase10-timeout-verified`; diagnostics/rejected texts remain outside Git in private temporary directories. No production account data was changed, no frontend code changed, and no next phase began.

Final checks: **73 focused AI unit/SDK/PostgreSQL integration tests passed in 7.52 seconds** (`pytest -c apps/api/pyproject.toml apps/api/tests/test_ai.py apps/api/tests/test_ai_routes.py -q`, run by the temporary live harness before the live call). Ruff check/format (69 files), strict mypy (39 source files), and API source/wheel build (`uv build --offline` from `apps/api`, approved cache access) passed. Documentation formatting and Git whitespace/secret checks passed before commit. Frontend/responsive/E2E suites were not rerun for these backend-only fixes; earlier review results remain separately documented.

## Phase 12 strict review — 2026-09-11

Reviewed the explicit Phase 12 prompt, implementation commit `cf7d243`, Compose follow-up `2dc6046`, analytics definitions, backend/frontend changes, tests and Phase 12 report. Review changes stay within Phase 12.

Confirmed defects repaired:

- Workspace policy, breadcrumb and onboarding links omitted the organization selector. They now retain it explicitly; browser fixtures contain two organizations and assert scoped links.
- Browser back/forward between registry pages could retain the previous page's records and export action while the new request was pending. The registry now remounts for URL changes; the delayed-response browser regression checks that the old rows disappear during history navigation.
- Adding a note to a resolved finding reset `resolved_at`, silently changing dashboard MTTR. Notes now preserve that timestamp. The real-database finding-review regression asserts it stays unchanged.

Added real PostgreSQL coverage for developer/viewer project access and membership revocation, failed-source exclusion from lifecycle trends, and expired exceptions disappearing when the latest gate activation deactivates the policy. Existing tests exercise unauthenticated/cross-tenant denial, scoped metadata redaction, incomplete scans, undefined ratios/MTTR, timezone boundaries, filter consistency and latest gate selection.

Commands use bundled Node 24 on PATH and the existing API virtualenv. Every Compose invocation uses `-p aegisforge`; no phase-specific project or volume deletion is used.

Initial verification results:

- `docker compose -p aegisforge -f docker-compose.yml -f docker-compose.test.yml run --rm --build api pytest -q -m 'not zap_live'`: **440 passed, 8 opt-in live ZAP tests deselected**, 2 upstream warnings, 145.48 seconds. This baseline predates the review fixes.
- Final source mounted read-only into the same test image: `docker compose -p aegisforge -f docker-compose.yml -f docker-compose.test.yml run --rm -v /home/akshat/Desktop/aegis-4th-year/apps/api/src:/app/src:ro -v /home/akshat/Desktop/aegis-4th-year/apps/api/tests:/app/tests:ro api pytest -q tests/test_analytics.py tests/test_findings.py`: **22 passed**, 21.97 seconds.
- `apps/api/.venv/bin/ruff check apps/api`, `ruff format --check apps/api`, strict `mypy --config-file apps/api/pyproject.toml apps/api/src`, and `python -m aegis_api.schema_docs --check`: **passed** (78 formatted files; 44 typed source files).
- `pnpm --filter @aegisforge/web lint` and `typecheck`: **passed** after the fixes.
- API package build through local Hatchling was unavailable (`ModuleNotFoundError`); containerized `uv build --out-dir /tmp/phase12-review-dist` with the final source mount **passed**, producing wheel and sdist. API and mock-worker Compose image builds **passed**.

The four committed dashboard baselines were visually inspected at 390, 768, 1280 and 1440 widths: compact drawer on mobile/tablet, visible dark sidebar on desktop, cyan active navigation, readable panels and scrollable tables. Final browser comparisons and live-run results follow below.

Initial `docker system df` reclaimable columns: Images **4.155GB (86%)**, Build Cache **8.834GB**. Cache exceeds the requested 5GB threshold: non-blocking housekeeping flag. Suggest `docker builder prune` before the next phase; `docker image prune -a` is optional for unused images. These prune commands are suggestions only; review does not remove images or volumes.

Final frontend checks: **37 unit tests passed in 34.02 seconds**, 9 files. Repository Prettier passed. The first full configured browser run returned **58 passed, 3 failed, 7 opt-in live tests skipped** (6.9 minutes). The developer/viewer assertions reproduced the unscoped links in the previously built bundle; the owner failure was a 67-pixel organization-select difference caused by the longer second fixture organization name. The fixture name was shortened, without updating snapshots. After rebuilding the final code, `pnpm --filter @aegisforge/web exec playwright test dashboard --project=production`: **3 passed in 52.9 seconds**, including all four unchanged snapshots, axe and overflow assertions, two-organization link checks, error/retry, and delayed registry history navigation. The other 58 passing regressions were not rerun after the targeted fixes. Vite production compilation and generated assets passed through the configured Playwright build command. `python3 scripts/check_compose.py` passed development, production, scanner and fixture boundary assertions.

Live run: `AEGIS_AI_PROVIDER=none docker compose -p aegisforge -f docker-compose.yml -f docker-compose.e2e.yml -f docker-compose.phase6-e2e.yml -f docker-compose.phase7-e2e.yml up --build -d --wait api worker`, followed by `AEGIS_E2E_AUTH=1 pnpm --filter @aegisforge/web exec playwright test --project=auth --workers=1`: **6 passed, 1 failed**, 3.1 minutes. Identity, anonymous denial, mobile keyboard navigation, collapse/recovery, dashboard/team/settings and scan/SSE/cancellation passed. Configuration correctly refused credential storage because the existing ignored `.env` lacked its local encryption key. No false success was returned.

The Compose follow-up had removed the disposable encryption key but lacked a preflight. The runner now validates a persistent 32-byte base64 key from captured Compose configuration before any startup/cleanup; no configuration or secret value is printed. A missing local development key was generated once into ignored `.env` (0600), preserving other settings. Existing nonempty keys are never rotated. `python3 scripts/test_compose_runner.py`: **2 tests passed**, covering three missing/invalid-key cases and both success/failure cleanup; this check is included in `make test`. Ruff check/format passed for the two scripts. The affected live configuration journey is rerun through this runner below.

Post-build `docker system df`: reclaimable Images **3.696GB (72%)**, Build Cache **9.125GB** while test containers were running. Cache remains a non-blocking housekeeping flag. Review did not prune storage.

Remaining boundaries: reports/integrations/API keys provide real metadata registries and supported revocation/deactivation, not report generation/downloads, provider setup or key issuance/authentication. Existing resource selectors are capped at 200 records; large-production throughput is unmeasured. Developer/viewer browser navigation uses HTTP fixtures, with real PostgreSQL authorization/revocation tests separately; this is not live multi-role mutation certification. Stale-age indication is implemented on the dashboard, not uniformly across all older product lists. No new live ZAP/Gemini or cross-browser certification is claimed. These prevent an unconditional claim of complete product UX; no later-phase service was added during review.

Final corrected live command: `AEGIS_AI_PROVIDER=none python3 scripts/test_auth_e2e.py configuration.spec.ts --workers=1`: **1 passed (1.4 minutes)**, with credential creation, authorized target setup and archive checks. All seven distinct live scenarios passed across the initial six-pass/one-failure run and this corrected rerun; this is not claimed as a single clean seven-test run. The runner completed `docker compose -p aegisforge ... down` without volume/orphan deletion. Final `docker ps` was empty. Final reclaimable columns: Images **4.824GB (94%)**, Build Cache **9.125GB**. Four local volumes remain retained.

**Verdict: CONDITIONAL PASS** for the implemented Phase 12 dashboard/workspace scope after repairing the four confirmed defects above. Non-blocking limitations are the explicitly listed metadata-only services, 200-record resource selectors, nonuniform older-list stale indicators, separated rather than live multi-role mutation coverage, and unmeasured production-scale/cross-browser behavior. The build-cache housekeeping flag remains: run `docker builder prune` before the next phase; optionally `docker image prune -a` for unused images. No unconditional complete-product or production-readiness claim is made. No deployment, push, external message delivery or next-phase work was performed. Final repository formatting and diff checks passed; the local key is ignored and is not committed.

## Selector pagination correction — 2026-09-12

Confirmed the cap was `limit(200)` without offset, continuation metadata, load-more or search fallback. Corrected the previous review classification. Resource and configuration project/target/policy endpoints now paginate by validated offset with deterministic ID tie-breakers; dashboard project filtering happens before the target page is selected. Shared selector controls append records, preserve existing choices on failure, retry the failed page and reset on scope changes. The project-detail target list also uses the pageable endpoint. Generated OpenAPI and metric/UX documentation were updated. Offset pages are not a cross-request snapshot; the documented concurrency behavior is to reload after inventory changes.

Verification:

- Real PostgreSQL `docker compose -p aegisforge -f docker-compose.yml -f docker-compose.test.yml run --rm` with read-only API source/test mounts, `pytest -q tests/test_selector_pagination.py tests/test_configuration.py tests/test_analytics.py`: **91 passed, 1 failed** in 27.43 seconds. The failure was a new synthetic target fixture missing required scope fields, not an application result. Corrected focused `pytest -q tests/test_selector_pagination.py`: **2 passed in 10.71 seconds**. Covers 201 projects, 201 same-project targets with tied timestamps, 201 policies; pages 200/1/0; matching metadata/full-detail page populations; cross-tenant and viewer project scope; server project filtering; and negative-offset HTTP rejection.
- Initial frontend run: **37 existing tests passed**, 3 new tests failed because a beforeEach callback returned the mock function, which Vitest treated as teardown. After fixing the test setup: `pnpm --filter @aegisforge/web test --maxWorkers=1`: **40 passed**, 10 files, 39.10 seconds. New cases cover selectable record 201, second-page failure/retry retaining earlier choices, exact-200 exhaustion, scope reset and late-response exclusion.
- `pnpm --filter @aegisforge/web exec playwright test dashboard policies --project=production`: **4 passed in 54.5 seconds**. Owner journey selects project 201 and target 201 through actual Load more controls and verifies both aggregate query filters. Existing 390/768/1280/1440 snapshots, axe/overflow checks, developer/viewer dashboard journeys and gate policy journey pass without baseline updates.

- Final frontend suite, including URL-selected records beyond the loaded page and refresh retention: **41 passed in 26.31 seconds**. A test-only unsupported Testing Library `exact` option was caught by typecheck and removed; final TypeScript, ESLint, Ruff lint/format, strict mypy and generated OpenAPI parity passed. The hook was separated from its controls to keep React Fast Refresh lint clean. Final Vite production build passed (1.26 seconds). The project-detail follow-up also passed its 3 focused configuration UI tests (3.62 seconds).
- `AEGIS_AI_PROVIDER=none python3 scripts/test_auth_e2e.py configuration.spec.ts scans.spec.ts --workers=1`: **2 passed in 2.9 minutes**, using actual PostgreSQL/Redis/API and mock worker. Covers project/policy/authorized target/credential/archive setup and scan/SSE/gate/cancellation. The runner used only `-p aegisforge`, then removed test containers/networks while retaining volumes.

The silent selector cap is fixed; record 201 and later pages are now reachable through a documented and tested control. Other previously recorded phase limitations are not reclassified by this correction. Final formatting and diff checks passed. No later phase was started.

## Phase 13 strict review — 2026-09-16

Reviewed the Phase 13 requirements, working-tree diff (including new untracked modules), migration, implementation report and tests. The review remains within Phase 13. Confirmed defects repaired:

- Report artifact metadata could be rewritten after resetting a completed report's state. The database trigger now prevents that reset, preserves published checksum/object/content/redaction metadata even after expiry, and freezes tenant identity. PostgreSQL regressions exercise attempted mutations.
- Report generation checked the latest version before taking the scan lock, allowing stale status publication; expiry did not update the scan's report status. Latest-version selection now happens under the scan lock and both expiry paths synchronize status. The storage-failure regression also confirms failed generation cannot supply a download or ready artifact.
- API-key authentication returned cached authority after committing the usage audit. It now refreshes key/creator authority under the organization lock after that commit. A regression revokes the key at that boundary and requires denial. Redis failures return a redacted 503 and fail closed; the dependency factory has an explicit return type.
- A failed registry refresh unmounted the one-time secret. Issuance controls now survive record-loading failures within the same organization. Notification lists no longer claim an empty history during loading/failure or expose stale page actions.
- Exception notifications ignored `allow_exceptions`; disabled exceptions are now excluded. Destination DNS validation has a deadline. GitHub PR validation now accumulates bounded response chunks instead of assuming a single stream read returns a full JSON document; adapter tests cover split JSON, rejection, redaction and disabled redirects.

Actual backend runs before the interruption: full container `pytest -m "not zap_live" -q` **471 passed, 8 live ZAP tests deselected**, 2 upstream deprecation warnings, 159.15 seconds. Subsequent final-source `pytest tests/test_reporting_access.py -q` **33 passed in 18.04 seconds**, covering the later review fixes. Commands used `sg docker -c 'docker compose -p aegisforge -f docker-compose.yml -f docker-compose.test.yml run --rm ... api pytest ...'` with read-only mounts of `apps/api/src`, `apps/api/tests` and `apps/api/migrations`; the fixture creates and removes its own database, not the development database.

Intermediate verification failures are not passes: the first review lint run rejected synchronous effect state resets; the implementation was corrected. A subsequent frontend run passed 43 tests but failed the new error-state case because its `beforeEach` returned a mock function that Vitest called as cleanup. The hook now explicitly returns nothing. An approval-service usage-limit rejection interrupted process inspection on September 13; work resumed September 16. Final results follow below.

External SMTP/Slack/GitHub/S3 credentials are not used by these tests; transport/storage boundaries use controlled doubles, with authorization and persistence separately exercised against PostgreSQL. No live provider delivery, new target scan, cloud deployment or production-scale certification is claimed. Existing Git metadata is protected read-only; the earlier staging escalation was rejected by automatic approval review. This review does not retry or work around that restriction.

Final quality/build command: `PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH UV_CACHE_DIR=/tmp/aegis-uv-cache make check build UV=/tmp/aegis-tooling/bin/uv` **exit 0**. Prettier, ESLint, Ruff (86 files), strict TypeScript/mypy (49 source files), generated schema parity, two Compose-runner tests, **44 frontend unit tests**, **348 backend unit tests** (8 opt-in live ZAP skips; 130 integration tests excluded from this command), Vite production build and API wheel/sdist all passed. `python3 scripts/check_compose.py` passed development/production configuration and scanner/fixture isolation assertions.

The changed browser workflow passed in **40.0 seconds**. It exercises key issuance/dismissal, a failed registry refresh retaining the one-time secret, report queuing and destination creation with HTTP fixtures. All three changed pages have automated axe and overflow assertions at **390, 768, 1280 and 1440 pixels**. All twelve resulting screenshots were visually inspected: readable forms, wrapping scope/event controls, mobile/tablet navigation drawer, desktop sidebar, and locally scrollable narrow registry tables. No clipping or overlap in the changed forms was found. Screenshots were retained in `/tmp/phase13-review-visuals` before subsequent browser runs could clear test results. This is Chromium coverage, not cross-browser certification.

Final real-database regression: the same source-mounted Compose command with `pytest -m integration -q` **130 passed, 356 deselected**, 2 upstream deprecation warnings, **151.47 seconds**. Together with the final unit run this covers all **478 non-live API tests** on the final sources.

The full `pnpm --filter @aegisforge/web test-e2e` command received SIGTERM (exit 143) after recording 50 passes, one timeout and seven opt-in skips; it is not a passing full-suite command. The timeout was the unchanged 1280px public documentation touch-target locator, which passed in 3.9 seconds in the recovery batch without changing assertions or application code. One attempted rerun could not start because the interrupted command left its two Vite test servers on ports 4173/5174; their command lines were verified and only those processes were stopped. The bounded recovery batch covers unfinished public-page/retro-lab scenarios as well as that failure.

Browser recovery command: `pnpm --filter @aegisforge/web exec playwright test marketing-targets.spec.ts marketing-review.spec.ts retro-labs.spec.ts --grep '1280|1440|1920|1024|case variants|keyboard footer|normal pinned|mobile story'`: **17 passed in 2.7 minutes, exit 0**. The union of successful named scenarios across the interrupted run and this recovery is **all 62 non-live browser tests**. This is split-run coverage, not a clean single full-suite run; no baseline or timeout assertion was loosened to resolve the public-page failure.

Live command: `PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH AEGIS_AI_PROVIDER=none AEGIS_REPORTING_ENABLED=false sg docker -c 'python3 scripts/test_auth_e2e.py --workers=1'`: **7 passed in 3.3 minutes, exit 0**. Actual PostgreSQL/Redis/API/mock-worker journeys cover registration/refresh/logout, anonymous denial, mobile keyboard navigation, dashboard/team/settings, authorized project/target/credential setup and scan/SSE/replay/gate/cancellation. API and worker images rebuilt successfully. Reporting/notification background dispatch was disabled for these identity/scan regressions; Phase 13 jobs are covered by the database/adapter tests above, not claimed as live external deliveries. The runner completed `docker compose -p aegisforge ... down` without volume deletion.

Final `sg docker -c 'docker system df'` RECLAIMABLE columns: **Images 5.469GB (95%)**, **Build Cache 1.732GB**. Images exceed 5GB: **non-blocking housekeeping flag**, suggest `docker image prune -a` before the next phase; `docker builder prune` is optional cache housekeeping. Neither prune command was executed. Docker reports zero containers and five retained volumes.

**Verdict: CONDITIONAL PASS.** Confirmed Phase 13 blockers are repaired and the required verification is complete with the split-run browser history above. Non-blocking limitations: no live external notification/S3 account validation, Chromium-only browser coverage, unmeasured production throughput, and the disclosed interrupted full-suite command (all named scenarios subsequently covered). Git staging/commit remains blocked by protected read-only metadata and the earlier automatic-review rejection; changes remain in the working tree. No push, deployment, external message, volume deletion or next-phase implementation was performed. Phase 14 requires a separate explicit prompt.

## Phase 13 live security follow-up — 2026-09-18

None of the seven earlier live identity/configuration/scan journeys exercised webhook HMAC delivery, malicious notification-destination rejection, or browser issuance followed by API-key-only authentication. Those earlier counts must not be interpreted as coverage of these three flows. The following additional journeys now provide that coverage.

Command (bundled Node/pnpm on PATH): `sg docker -c 'apps/api/.venv/bin/python scripts/phase13_live/run.py'` — **exit 0, all three journeys passed**. Reproducible harness and fixture boundaries: [scripts/phase13_live/README.md](../scripts/phase13_live/README.md). Final log: `/tmp/phase13-live-security-verified.log`.

| Requested journey                                     | Actual live evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Real webhook delivery and HMAC verification           | Authenticated HTTP destination creation returned 201. An explicitly synthetic failed-scan record triggered the unmodified background fanout/queue/delivery worker. A separate TLS server received the actual POST and independently verified timestamp freshness and HMAC-SHA256 over its exact raw bytes before returning 204. The delivery API then reported `sent`. A negative-control request with an invalid signature returned 401. The payload excluded the synthetic response-body canary and signing secret.                                                                                                                               |
| SSRF rejection through the API                        | Seven authenticated, CSRF-protected HTTP POSTs returned 422/`destination_invalid`: IPv4 loopback, metadata IP, IPv6 loopback, IPv4-mapped loopback, a hostname resolving to loopback, plaintext HTTP, and a disallowed port. A real listing request confirmed that none persisted. These requests went through the running API, not direct calls to a validation function.                                                                                                                                                                                                                                                                          |
| One-time API-key display and hash-only authentication | Chromium submitted the actual key form, verified its one-time secret field, dismissed it and reloaded; the secret was no longer available in the UI or listing response. A fresh HTTP client with no cookies and only the key bearer credential received 200 from `/api/public/v1/projects`. Database inspection verified the SHA-256 digest, absence of any secret column and populated `last_used_at`. Replacing only the stored hash made the identical credential return 401; restoring the hash restored 200. The ungranted findings scope returned 403; real revocation then caused 401. Secrets were not printed or captured in screenshots. |

This is **real local network end-to-end verification**, with actual Chromium, Uvicorn, PostgreSQL, Redis, DNS resolution, TLS, HTTP transport and the notification coordinator. It is not a public internet/provider certification. The receiver uses a fresh private CA and a public-classified address on an internal-only Docker fixture network; no traffic is routed to the real public subnet. There were no production dependency overrides, validation exemptions, monkeypatches or mocked HTTP responses. The event is synthetic test data, not a real target scan. Production application code did not change during this follow-up.

Intermediate attempts are disclosed: the initial harness assumed an image that had been removed and failed before journeys began. The harness now builds the explicit test image and never tries to pull it from a registry. Two subsequent runs passed the SSRF requests but timed out on delivery; diagnostics recorded two failed durable attempts and a receiver-side disconnect. Correcting the fixture receiver UID to match its host-owned acknowledgement directory resolved this without changing application transport or validation. Only the final complete run is counted as all-three PASS.

Ruff lint/format, Node syntax checking, Prettier and Git whitespace checks passed for the new harness/documentation. Cleanup stopped and removed the test API/receiver/Redis/PostgreSQL containers and fixture networks, dropped only the randomly named test database, and deleted temporary certificates/secrets. Existing Docker volumes were retained. Existing read-only Git metadata still prevents committing; no workaround or next-phase work was attempted.

## Simulated GitHub payload verification — 2026-09-18

Added reusable test-only GitHub payload generation in `apps/api/tests/github_webhook_fixture.py` and a loopback HTTP receiver suite in `apps/api/tests/test_github_webhook_fixture.py`. GitHub signs the raw request body with HMAC-SHA256 and sends the `sha256=` hex digest in `X-Hub-Signature-256`; it does not use the AegisForge generic webhook timestamp prefix. The verifier is anchored to [GitHub's published test vector](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries), and local fixtures generate random ephemeral signing secrets.

`apps/api/.venv/bin/pytest -c apps/api/pyproject.toml apps/api/tests/test_github_webhook_fixture.py -q`: **8 passed in 3.98 seconds, zero skips**. Cases: published signature vector; signed simulated `pull_request` delivery including UTF-8 text; signed simulated failed `workflow_run` completion; and five HTTP 403 rejection cases (tampered conclusion, wrong secret, missing signature, SHA-1 and AegisForge's timestamp-prefixed scheme). Accepted deliveries return 204 from the test receiver; rejected deliveries are never processed. Ruff lint/format, documentation formatting and Git whitespace checks passed.

There is no live GitHub repository available. These tests verify **simulated GitHub payloads**, not a live GitHub repository, a real Actions run, or an AegisForge incoming webhook endpoint. Incoming webhook handling and Actions execution are not part of the implemented Phase 13 adapter. No production route, application behavior, dependency or workflow changed; the tests run normally rather than being skipped for missing GitHub access.
