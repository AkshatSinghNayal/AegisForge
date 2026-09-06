# Build plan

## Execution contract

These phase numbers are the proposed complete sequence because the supplied pack defines Phase 0 but does not provide later phase prompts. Future explicit phase prompts may revise this plan through an ADR. Execute one phase at a time, verify acceptance, update status, and commit before advancing. No deployment, target scanning or external message transmission is authorized merely by this roadmap.

## Phases and dependencies

| Phase | Deliverable and exit criteria                                                                                                                                                                                | Dependencies                            |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------- |
| 0     | Discovery, architecture, API contract, threat model, traceable tests; no production code                                                                                                                     | Master Context, synopsis, UI references |
| 1     | Monorepo/tooling: React/TS/Vite, FastAPI, pnpm/uv lockfiles, Compose PostgreSQL/Redis, migration/test runners, CI, health skeleton, .env.example; clean install/check/build                                  | 0                                       |
| 2     | Original design system, accessible primitives/shells, development-only UI and motion labs; public-only Lenis, GSAP story, reduced motion, responsive/accessibility/screenshot tests (explicit Phase 2 scope) | 1                                       |
| 3     | Complete public marketing website, four-step desktop scrollytelling/mobile fallback, feature/docs/legal routes, static SEO metadata and browser acceptance (explicit Phase 3 scope)                          | 1, 2                                    |
| 4     | Database foundation: 22 core entities, tenant constraints, migrations, API conventions, factories and isolation tests (explicit Phase 4 scope)                                                               | 3                                       |
| 5     | Isolated worker/ZAP orchestration, jobs, cancellation, timeouts, schedules, confirmation and target validation; real authorized fixture scans and recovery tests                                             | 4                                       |
| 6     | Evidence ingestion/redaction, normalization, fingerprinting, occurrences, lifecycle and scan results/history; partial-scan and tenant tests                                                                  | 5                                       |
| 7     | Gemini provider, disabled/mock adapter, optional local adapter, schema/evidence validation, analysis/retry UI; outage and prompt-injection tests                                                             | 6                                       |
| 8     | Deterministic versioned gates, API keys, GitHub Actions/webhooks, authenticated pipeline result; gate and replay tests                                                                                       | 6, 7                                    |
| 9     | Dashboard, trends, coverage, recurrence and MTTR; PDF/JSON reports, local/S3 storage, verified downloads; analytics/report tests                                                                             | 6, 7, 8                                 |
| 10    | SMTP/Slack/generic webhook/PR deliveries, retry outbox, settings, team/admin/audit management; delivery and privilege tests                                                                                  | 3, 8, 9                                 |
| 11    | Production AWS profile: EC2/RDS/ElastiCache/S3/CloudWatch, optional ALB, IaC, backup/restore, secret management and worker egress isolation; staging exercises                                               | 5, 9, 10                                |
| 12    | Full regression/security/accessibility/performance review, operational runbooks, API/user docs, explicit demo seeding, academic evaluation and final handoff                                                 | 1-11                                    |

The explicit Phase 4 prompt supersedes the provisional target-management phase and implements persistence before authentication. Target CRUD/import/ownership services remain deferred. The explicit Phase 3 prompt supersedes the provisional identity phase. Identity, rotating sessions, organizations and authenticated product shell remain the next architectural prerequisite before targets; their phase number awaits the next explicit prompt. No next phase is automatically authorized.

Public routes: `/`, `/platform`, `/features/web-scanning`, `/features/api-scanning`, `/features/ai-analysis`, `/features/ci-cd`, `/features/reports`, `/pricing`, `/docs`, `/docs/getting-started`, `/docs/architecture`, `/docs/authorization`, `/docs/policies`, `/docs/integrations`, `/security`, `/privacy`, `/terms`.

Authentication routes: `/auth/sign-in`, `/auth/sign-up`, `/auth/forgot-password`, `/auth/reset-password`.

Product routes: `/app/getting-started`, `/app/dashboard`, `/app/projects`, `/app/projects/:projectId`, `/app/projects/:projectId/settings`, `/app/targets`, `/app/targets/new`, `/app/targets/:targetId`, `/app/scans`, `/app/scans/new`, `/app/scans/:scanId`, `/app/findings`, `/app/findings/:findingId`, `/app/reports`, `/app/reports/:reportId`, `/app/integrations`, `/app/api-keys`, `/app/team`, `/app/audit-log`, `/app/settings/profile`, `/app/settings/organization`, `/app/settings/security`.

Admin routes: `/admin/users`, `/admin/policies`, `/admin/system`. These are organization-admin surfaces, not implicit cross-tenant superuser access. Operator health access is separately authenticated.

Each route ships with working behavior in its owning phase; do not introduce placeholder routes for future phases. Getting-started progress derives from persisted prerequisites. Any illustrative marketing metrics are explicitly examples, never claimed measurements.

## Synopsis module traceability

| Synopsis module                           | Phases                          | Requirement/test IDs |
| ----------------------------------------- | ------------------------------- | -------------------- |
| 7.1 Authentication and project management | Identity prerequisite (TBD), 4  | R01, R02, R03        |
| 7.2 Target configuration                  | 4                               | R04, R05             |
| 7.3 Vulnerability scanning                | 5, 6                            | R06, R07, R08        |
| 7.4 AI analysis                           | 7                               | R09, R10             |
| 7.5 Scan history and reports              | 6, 9                            | R08, R11, R12        |
| 7.6 CI/CD integration                     | 8, 10                           | R13, R14, R15        |
| 7.7 Dashboard and analytics               | 9                               | R16                  |
| 7.8 Cloud deployment and storage          | 11                              | R17, R18             |
| 7.9 Administration                        | Identity prerequisite (TBD), 10 | R02, R19             |

## Phase-wide definition of done

A phase requires its acceptance tests plus formatting, lint, strict types, unit/integration tests and relevant production build. Run E2E tests for changed journeys, tenant/security tests for changed boundaries, migrations against fresh and upgraded databases, and update documentation/configuration. A failed or unavailable required check blocks the corresponding release claim. Phase 1 supplies executable checks; see PHASE_STATUS for actual results and remaining infrastructure gates.

Implemented layout: `apps/web`, `apps/api`, `infra`, `docs`, `scripts` and `.github/workflows`. Shared client/config/token packages and `scanner` are planned extractions when consumers or execution exist; they are not present in the foundation. Tokens and ESLint configuration currently live in `apps/web`.
