# AegisForge

DevSecOps Vulnerability Intelligence Engine for authorized web applications and REST APIs.

Phase 1 supplies a React service-health view, a FastAPI health API, a Celery worker foundation, and local PostgreSQL/Redis infrastructure. Phase 4 adds the PostgreSQL domain schema and internal API conventions. Scanning, identity and AI execution belong to later phases. Phase 3 adds the complete public marketing website. Local quality checks, browser tests and production package builds pass; live development/production container health, all three real-service integration tests and repeated migrations passed on 2026-09-06. See the [verification record](docs/PHASE_STATUS.md).

## Design and motion laboratories

Phase 2 adds an original wordmark, semantic dark tokens, accessible primitives and responsive shells. Run `pnpm --filter @aegisforge/web dev` and visit `/dev/ui` or `/dev/motion`. These routes are excluded from production. See [component and motion usage](docs/DESIGN_SYSTEM.md). No backend features or full product pages were added.

## Public website (Phase 3)

Run `pnpm --filter @aegisforge/web dev` and open `/`. Public routes cover the platform, five features, project packaging, searchable documentation and security/privacy/terms. The home story pins on desktop with GSAP scrub 0.8; mobile and reduced-motion preferences show all four steps in normal flow. Public navigation alone owns Lenis. The original cockpit is HTML/CSS and visibly illustrative; no findings, metrics, customers or connected integrations are fabricated.

“Create a workspace” opens the local setup guide because registration is not implemented. The health utility remains at `/status`. Set `VITE_SITE_URL` to the actual deployment origin and `VITE_SECURITY_CONTACT` to a verified public email before publication. Both are validated public build settings; Compose forwards them into development and production build arguments. Build output includes per-route HTML metadata, sitemap, robots and JSON-LD; the localhost default disallows indexing. The content is client-rendered with a no-JavaScript notice. System fonts require no font download/preload; there are no raster images to load or resize. Routes are lazy-loaded and GSAP loads with the home story.

The Phase 3 review cleared the Phase 1 live Docker gate; the retroactive Phase 0–2 audit independently repeated it from a clean export and removed its isolated stack afterward. Phase 2 form-label and clipboard defects were fixed. The subsequent authorized touch-target fix expands the flagged footer, outcome and docs masthead link hit areas to at least 44px without enlarging text; dedicated browser regressions cover all seven widths. No public deployment was performed. See the [final review report](docs/TEST_REPORT.md) and [phase status](docs/PHASE_STATUS.md).

## Database foundation (Phase 4)

`make migrate` applies revision `0001`: all 22 requested entities plus durable idempotency records. UUIDs, timezone-aware timestamps, tenant composite foreign keys, immutable-history triggers and query indexes live in PostgreSQL. Internal repositories require a tenant scope; future authenticated dependencies must resolve it and enforce roles/project membership. No authentication, scan/report creation routes, secret storage, webhook receiver or delivery worker ships in this phase.

Run `make schema-docs` to regenerate [OpenAPI](docs/generated/openapi.json), [convention schemas](docs/generated/conventions.schema.json) and the [database catalog](docs/generated/database-schema.md). `make schema-check` detects drift. `make test-integration` requires the isolated test profile and database-create permission: it provisions a uniquely named disposable database, tests upgrade/downgrade/re-upgrade and two-organization isolation, then drops only that database. Never run manual downgrades against retained data; revision 0001 downgrade removes the foundation.

See [persistence usage and limits](docs/architecture/PERSISTENCE.md). All factories are synthetic and no seed command inserts data automatically.

## Quick start

Prerequisites: Node.js 24 LTS, pnpm 11.19.0, uv 0.12.10, Python 3.12 (uv can download it), Make, and Docker Engine with Compose 2.24.4+ (tested configuration with Compose 5.5.1). Install Docker and uv using their official installers for your OS. No system package installation is performed by `make setup`.

From the repository root:

```sh
npm install -g pnpm@11.19.0
make setup
make compose-config
make dev
make migrate
```

`make setup` preserves an existing `.env`; otherwise it generates random local PostgreSQL/Redis passwords in a mode-0600 ignored file from `.env.example`. It installs frozen pnpm/uv dependencies and Chromium. On Linux, if Chromium reports missing OS libraries, run `pnpm --filter @aegisforge/web exec playwright install --with-deps chromium` with the necessary system permissions.

Open [local service health](http://localhost:5173/status). Its refresh button calls the API through Vite's same-origin proxy. The page reports dependency failure honestly. The API exposes only `GET /health/live` (process alive, HTTP 200) and `GET /health/ready` (bounded PostgreSQL `SELECT 1` and Redis `PING`, HTTP 200 or 503). Both return a server-generated `X-Request-ID`; readiness does not expose dependency credentials or exception messages. Development/test expose `/api/v1/docs` and `/api/v1/openapi.json`; production disables both. Business endpoints remain unavailable.

```sh
curl --fail http://localhost:8000/health/live
curl --fail http://localhost:8000/health/ready
pnpm check
make build
make test-e2e
make test-integration
make down
```

`pnpm check` is the root frontend/backend formatter, lint, strict-type and unit/security test gate. Integration tests require real Compose services and are run explicitly; unit tests inject dependency availability and failure. The Playwright test uses controlled HTTP fixtures to check ready/unavailable rendering and keyboard refresh. It does not claim a real database-backed browser journey. CI additionally starts Compose, runs real dependency tests, repeats migrations, builds production images, and checks the production proxy.

## Commands and development

| Command                 | Behavior                                                                          |
| ----------------------- | --------------------------------------------------------------------------------- |
| `make setup`            | Preserve/create local env, frozen install, install browser                        |
| `make dev`              | Build and start healthy local services in background                              |
| `make down`             | Stop containers; retain named data volumes                                        |
| `make lint`             | Prettier, ESLint, Ruff lint and format check                                      |
| `make typecheck`        | Strict TypeScript and mypy                                                        |
| `make test`             | Frontend and backend unit/security tests                                          |
| `make test-e2e`         | Production health/exclusion and dev lab Chromium tests                            |
| `make test-integration` | Disposable test image; actual PostgreSQL/Redis readiness tests                    |
| `make migrate`          | Alembic upgrade to head; applies Phase 4 revision 0001                            |
| `make seed-demo`        | Explain that no demo seed is implemented; no mutation                             |
| `make clean-generated`  | Remove only enumerated build/test caches; preserve .env, dependencies and volumes |
| `make build`            | Web distribution plus API sdist/wheel                                             |
| `make compose-config`   | Validate dev/prod/scanner Compose and network/port invariants                     |
| `pnpm format`           | Format source and current phase docs                                              |

The web container mounts `apps/web/src` read-only for Vite hot reload. Rebuild after dependency/configuration changes. API and worker use built source; rerun `make dev` after backend changes. The API Dockerfile and worker Dockerfile use non-root users. The worker registers no product tasks and receives no database credentials. Separate internal broker networks connect each process to Redis without connecting worker directly to API or PostgreSQL. This is a local topology, not Phase 5's execution-time scope/egress security boundary.

Settings use the `AEGIS_` prefix and validated `dev`, `test`, `prod` profiles. All profiles require explicit connection URLs; production rejects DEBUG logging. Host-run API development needs real `AEGIS_DATABASE_URL` and `AEGIS_REDIS_URL` values; the Compose-only database and broker do not publish host ports. `.env` is not copied into images. `VITE_` values are public build-time browser configuration and must never contain secrets; the default empty API base uses the same-origin proxy. Lenis runs only in public marketing/laboratory layouts and is absent from `/status` and application layouts.

## Production-shaped local configuration

```sh
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d --wait
curl --fail http://localhost:8080/health/ready
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
```

This override serves compiled assets through unprivileged Nginx and removes the API host port and source mount. PostgreSQL, Redis and the worker publish no host ports in either configuration. Web bindings are loopback-only. It is a local production-build check; TLS, managed secrets, AWS, backups and deployment hardening belong to Phase 11. Do not publish `docker compose config` output because interpolated environment values include local credentials; the supplied validation command keeps that output in memory.

ZAP 2.17.0 is digest-pinned behind the `scanner` profile, with no network and no API/host port. It is an idle image foundation with a process health check, not a running scanner. Do not enable target scanning in this phase. Named volumes retain PostgreSQL, Redis and future ZAP workspace data across `down`; cleanup never deletes these volumes.

## Documentation

- [Working agreement](AGENTS.md)
- [Build plan and dependencies](docs/BUILD_PLAN.md)
- [Phase status and verification](docs/PHASE_STATUS.md)
- [Architecture decisions](docs/DECISIONS.md)
- [System context](docs/architecture/CONTEXT.md)
- [Containers and scan sequence](docs/architecture/CONTAINERS.md)
- [Data model and retention](docs/architecture/DATA_MODEL.md)
- [Scan state machine](docs/architecture/SCAN_STATE_MACHINE.md)
- [Threat model](docs/security/THREAT_MODEL.md)
- [API contract](docs/API_CONTRACT.md)
- [Test matrix](docs/TEST_MATRIX.md)

## Repository scope

`apps/web` owns frontend configuration, source and browser tests; `apps/api` owns the uv project, settings, logging, dependency probes, Alembic runner and tests. `infra` holds the local proxy configuration; `scripts` contains environment setup and configuration/cleanup helpers. Shared packages are deferred until they have real contents. CI is the automatic quality gate; local Git hooks are not installed or modified.

The architecture baseline and original remote README history are preserved. No later phase starts automatically.

Prometheus and Grafana also start with Compose, using persistent named volumes and a dedicated internal network with no published ports in either configuration. Grafana automatically provisions its Prometheus datasource; scrape targets, dashboards and alerts remain deferred to Phases 16/17. See [containers](docs/architecture/CONTAINERS.md#observability-scaffold).
