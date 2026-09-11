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
| 5     | Authentication, rotating sessions, organizations, RBAC, onboarding, authenticated shell and security/browser tests (explicit Phase 5 scope)                                                                  | 4                                       |
| 6     | Projects, authorized URL/OpenAPI targets, encrypted local secret references, immutable scan policies, four-step wizard and security/browser tests (explicit Phase 6 scope)                                   | 4, 5                                    |
| 7     | Mock-only scan lifecycle, durable Celery dispatch, authorization/idempotency, cancellation/deadlines/retries, ordered SSE, list/wizard/live UI and failure tests (explicit Phase 7 scope)                    | 6                                       |
| 8     | Deterministic versioned gates, API keys, GitHub Actions/webhooks, authenticated pipeline result; gate and replay tests                                                                                       | 6, 7                                    |
| 9     | Dashboard, trends, coverage, recurrence and MTTR; PDF/JSON reports, local/S3 storage, verified downloads; analytics/report tests                                                                             | 6, 7, 8                                 |
| 10    | SMTP/Slack/generic webhook/PR deliveries, retry outbox, settings, team/admin/audit management; delivery and privilege tests                                                                                  | 3, 8, 9                                 |
| 11    | Production AWS profile: EC2/RDS/ElastiCache/S3/CloudWatch, optional ALB, IaC, backup/restore, secret management and worker egress isolation; staging exercises                                               | 5, 9, 10                                |
| 12    | Full regression/security/accessibility/performance review, operational runbooks, API/user docs, explicit demo seeding, academic evaluation and final handoff                                                 | 1-11                                    |

The explicit Phase 4 prompt supersedes the provisional target-management phase and implements persistence before authentication. Target CRUD/import/ownership services are implemented under the explicit Phase 6 scope. The explicit Phase 3 prompt supersedes the provisional identity phase. The explicit Phase 5 prompt implements identity, rotating sessions, organizations, RBAC and the authenticated shell. Phase 6 now implements projects, targets, credentials and versioned policies; Phase 7 implements mock-only orchestration; real ZAP integration and Gemini require later explicit prompts; remaining provisional numbering is not execution authorization. No next phase is automatically authorized.

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

## Explicit Phase 6 scope

Projects/settings/member assignments/archive, URL and OpenAPI target setup, local encrypted secret references, immutable policy revisions, four-step wizard and security/browser tests. See CONFIGURATION.md. This supersedes the provisional Phase 6 normalization entry; that work and scanner execution remain deferred until explicitly requested. Stop after verification and documentation.

## Explicit Phase 7 scope

Idempotent scan creation, immutable-version/authorization/quota checks, one-use active grants, durable staged Celery dispatch, state transitions/events, cancellation/deadlines, bounded safe retries, duplicate worker protection, SSE replay and the scan list/wizard/live UI. Only a deterministic, explicitly enabled, network-free mock provider is implemented. Real ZAP and downstream security processing remain deferred. Stop after Phase 7.

## Explicit Phase 8 scope

The user's Phase 8 prompt replaces provisional gates/integrations with isolated OWASP ZAP execution: provider interface, mock preservation, worker-only secret resolution, fresh DNS checks, constrained gateway/container jobs, scoped URL/OpenAPI discovery, passive/explicitly authorized active scanning, bounded progress, immutable encrypted artifacts, resource cleanup and isolated training tests. Migration 0006 freezes raw-artifact provenance. Downstream normalization, AI, gates, reporting and deployment remain deferred. Stop after Phase 8; no later phase is automatically authorized.

## Explicit Phase 9 scope

The Phase 9 prompt authorizes evidence-preserving ZAP normalization, versioned stable finding identity, per-observation provenance, comparable-scan lifecycle derivation, RBAC/CSRF-protected review, findings/filter/detail/comparison UI and corresponding tests. [FINDING_NORMALIZATION](FINDING_NORMALIZATION.md) is the implementation contract. AI execution, deterministic gate evaluation, reporting and subsequent phases remain deferred. Stop after Phase 9.

## Explicit Phase 10 scope

The Phase 10 prompt authorizes schema-constrained advisory AI providers, minimal safe inputs, strict evidence-linked outputs, bounded failure handling, AI Guidance UI, retained regeneration versions and explicit reviewer feedback. [AI_GUIDANCE](AI_GUIDANCE.md) is the implementation contract. Generation is on demand and disabled by default. No policy engine, report generation or subsequent phase is started. Stop after Phase 10.

## Phase 11 prompt override

The explicit Phase 11 prompt authorizes versioned deterministic project gate policies, accepted-risk exceptions, baseline-aware thresholds, immutable evaluations, preview/detail UI, admin publication/activation and developer read access. It supersedes the provisional phase numbering above. See [POLICY_ENGINE](POLICY_ENGINE.md). Reporting, integration and deployment remain deferred. Stop after Phase 11.
