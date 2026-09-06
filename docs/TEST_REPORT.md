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
