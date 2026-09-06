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
