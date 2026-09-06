# Architecture decisions

All entries accepted for the Phase 0 baseline on 2026-09-05. They describe intended implementation, not existing capabilities.

## ADR-001: Organizations and project authorization

Context: multiple teams share infrastructure. Decision: owner/admin/developer/viewer organization memberships; every tenant record has organization_id, timestamps and tenant-aware indexes/FKs. Owners/admins administer the organization, developers mutate assigned projects, viewers read assigned projects. Owner transfer/removal is transactional and cannot leave an organization without an owner. Consequence: every lookup, job and artifact download requires tenant and project authorization. Platform operators do not inherit tenant content access.

## ADR-002: Browser sessions

Decision: short-lived signed access JWTs (initial TTL 10 minutes); refresh tokens are random rotating secrets, hashed at rest in revocable session families (7-day idle, 30-day absolute expiry). Use Secure, HttpOnly, SameSite=Lax cookies under a same-origin reverse proxy; `__Host-` cookies in production. Validate CSRF token plus Origin for writes. Refresh reuse revokes the family. No long-lived tokens in localStorage. HTTP localhost may use explicitly development-only non-Secure cookies. Cross-site deployments require explicit cookie/CORS/CSRF review rather than silently relaxing defaults. Argon2id hashes passwords. Membership/revocation is checked server-side, not trusted solely from a stale JWT.

## ADR-003: Stack and persistent storage

Decision: React/TypeScript/Vite/Tailwind with the frontend libraries in the Master Context; Python 3.12+, FastAPI/Pydantic v2/SQLAlchemy 2/Alembic; PostgreSQL in development and production, Redis/Celery for orchestration. PostgreSQL is the source of truth; Redis is disposable transport/cache. This supersedes the synopsis's Flask, SQLite and MongoDB alternatives. Stable dependency versions are resolved in Phase 1, with lockfiles; no unverified versions are invented in Phase 0.

## ADR-004: Independent evidence, guidance and decisions

Decision: raw artifact, normalized occurrence/finding, AIAnalysis and PolicyEvaluation are distinct records. Evidence hashes, transformation versions and references preserve provenance. Gemini is advisory and schema/evidence validated. The policy engine consumes scanner severity, completeness and approved risk dispositions, never generated severity or confidence. AI outage causes degraded enrichment and at least `warn` (or `fail` under a fail-closed policy), never `pass`. Security failures take precedence over enrichment warnings.

## ADR-005: Isolated scan execution

Decision: API enqueues jobs; workers orchestrate per-scan isolated, version-pinned ZAP containers. No privileged Docker socket in the API or ordinary worker. A narrowly scoped runner provisions workloads with limits. Worker/scanner egress is restricted to current authorized target scope; no cloud metadata or application/control-plane network access. Retries are idempotent, leases/fencing prevent duplicate side effects, database events define state.

## ADR-006: Authorized target scope and active confirmation

Decision: require authorization method, actor, evidence reference, scope and expiry for all scans. Public DNS/HTTPS ownership challenge is the default; approved documented authorization is an audited admin alternative. URL possession alone is insufficient. Active mode additionally requires a one-use confirmation, valid 15 minutes, bound to user, organization, target/configuration/policy version and expiry. Scheduled active scans require an explicitly confirmed bounded schedule grant, maximum 30 days, with a maximum run count and revalidation each run. Changes or revoked authorization invalidate grants. Private-network scanning is excluded from the default MVP runner; a future isolated private runner requires a separate design.

## ADR-007: UI and honest product claims

Decision: separate public marketing and authenticated `/app` layouts; organization-admin `/admin` routes remain tenant-scoped. Original AegisForge visual identity using the prompt pack's tokens and typography. Public-only Lenis and GSAP scrollytelling; component transitions and reduced-motion fallback. Generated guidance, demo data, incomplete coverage and unavailable enrichment are visible. No autonomous code modification is in baseline scope; remediation is advice with verification guidance.

## ADR-008: Artifacts, privacy and reports

Decision: encrypted restricted raw evidence is retained briefly; redacted evidence derivatives serve UI/AI/reports. Secrets are references to a secret store, never ordinary target JSON. ReportLab generates PDF without fetching untrusted resources; JSON uses validated schemas. Local filesystem storage is allowed in development behind authenticated downloads; production uses private S3 and short-lived scoped downloads. Apply the retention schedule in DATA_MODEL, including backups. Reports support audit review, not a claim of certified compliance.

## ADR-009: AI providers and outages

Decision: a single provider interface supports official Gemini structured output, a disabled provider, a clearly labeled local/test mock and an optional disabled-by-default local fallback. Minimized redacted evidence only; no arbitrary tools/network access for the model. Provider errors do not lose findings. Failed analysis is recorded and retryable; prior policy evaluations remain immutable. A new enrichment result may create a new policy evaluation but cannot rewrite a previous result.

## ADR-010: Delivery and integration trust

Decision: GitHub webhook signatures, replay windows and installation/project binding; least-privilege API keys hashed at rest. Notifications use a transactional outbox with sanitized templates and destination-specific authorization. Outbound webhooks enforce SSRF controls. GitHub branch protection must require the check; a failed check alone cannot guarantee deployment is blocked. Configuration of destinations does not authorize sending real messages in a development task.

## ADR-011: State, completeness and recovery

Decision: use the explicit SCAN_STATE_MACHINE, one enum for processing state, separate completeness/enrichment fields. `completed` means processing ended, never inherently clean. Incomplete evidence yields a failing gate. Exhausted analysis/report retries degrade their component status, while scanner/normalization failures terminate the scan. Cancellation, timeout and worker recovery use transactional compare-and-swap and fencing.

## ADR-012: Phase boundaries and repository discovery

Decision: Phase 0 adds only Markdown documentation. No environment scaffold or dependency manifest until Phase 1. The observed workspace contains empty read-only `.git`, `.agents`, `.codex` directories and no existing source/configuration; `git status` returns exit 128. Preserve protected metadata and report the inability to commit. Later phase numbering in BUILD_PLAN is proposed and can be revised by the user's phase prompts.

## ADR-013: Repository connected after Phase 0

On 2026-09-05 the user supplied `git@github.com:AkshatSinghNayal/AegisForge.git` and authorized setup. SSH read access succeeded. Preserve the remote initial commit `19ed322` (title-only README), attach local `main` to it, and track `origin/main`. Retain the expanded local README and all Phase 0 documents. The Git blocker in ADR-012 is resolved; its discovery record remains historical.

## ADR-014: Phase 1 executable foundation

The explicit Phase 1 prompt authorizes only monorepo/local tooling. Resolve stable packages and commit pnpm and uv locks. Node 24, pnpm 11.19.0, Python 3.12 and uv 0.12.10 are the supported toolchain. TypeScript 6.0.3 stays inside typescript-eslint 8.69.0's supported `<6.1` range; the registry's newer TypeScript 7 is incompatible. React 19.2.8, Vite 8.2.2, Vitest 5.0.0, FastAPI 0.141.1 and SQLAlchemy 2.0.52 were resolved; lockfiles are authoritative. Official image registries confirmed all selected image tags. [ZAP's official version manifest](https://raw.githubusercontent.com/zaproxy/zap-admin/master/ZapVersions.xml) identifies stable 2.17.0; the image is additionally pinned to its registry manifest digest.

The root is a functional service-health utility, not a placeholder product page. Only two API health routes are enabled. Real PostgreSQL/Redis probes are bounded; failure produces HTTP 503 without exceptions or credentials. Server-generated request IDs avoid trusting caller headers. JSON logs allowlist event/status/ID/timestamp/level; arbitrary third-party messages and exception text are omitted to keep health logging free of secrets.

Use a production override file (Compose `!reset`/`!override`, requiring 2.24.4+) rather than duplicate development/production services. Database and broker never publish host ports. Worker has a separate internal broker network and receives no database credentials. Redis bridges the two broker networks as a service, not a router. Worker/scanner cannot share API or database networks; the idle, disabled-by-profile ZAP service has `network_mode: none`. Per-scan authorization, runtime target egress enforcement and the runner remain Phase 5 work.

Environment setup generates ignored local credentials once and does not overwrite existing files. No Phase 1 tables exist; Alembic has no domain revision and `seed-demo` explicitly makes no changes. CI owns automatic checks; no hooks are installed into protected Git metadata. Real container startup/migration/image builds remain a required verification gate when a Docker daemon is available. Passing package builds or Compose rendering do not substitute for that gate.

## ADR-015: Phase 2 design system and motion laboratory

The explicit Phase 2 prompt supersedes the provisional roadmap's full public-site scope. Deliver only original tokens/wordmark, accessible primitives, public/application shell specimens and development-only UI/motion laboratories. No backend changes or full marketing/authenticated pages. Phase 1's missing live Docker verification remains an independent unresolved gate; the user explicitly authorized frontend Phase 2. Native semantic controls, dialog and popover provide browser accessibility behavior, with explicit modal focus wrapping. System fonts avoid network/font-shift dependencies. Existing pinned GSAP/Lenis are reused; only axe Playwright is added as a pinned development test dependency. Compile-time DEV guards omit lab imports/routes from production. PublicLayout alone owns Lenis, matchMedia/context owns GSAP cleanup, and reduced motion renders full normal-flow content. See DESIGN_SYSTEM for the component contracts and test limitations.

## ADR-016: Phase 3 public website and honest availability

The user's Phase 3 prompt replaces the provisional identity scope with the public website. Reuse the React/Vite design system and pinned GSAP/Lenis dependencies; no new libraries, backend features, domain migrations, authentication, billing or hosting deployment. The repository phase contract governs delivery; Sites guidance does not authorize a separate deployment or re-scaffold.

Original mint/cyan technical panels frame HTML/CSS cockpit specimens. Desktop uses four crossfading/translated panels over 320vh with scrub 0.8, without snapping; mobile below 1024px, desktop viewports shorter than 760px and reduced motion use normal stacked flow. GSAP matchMedia owns cleanup, and public layout owns Lenis. No supplied video is present, so the written rhythm is implemented without claiming a visual reference match.

Workspace CTAs lead to substantive local setup documentation and disclose unavailable registration. Feature/integration descriptions distinguish the planned architecture from the current health-only backend. Pricing is example project packaging with no purchase flow. Legal notices describe this release, not an operational scanning service.

`VITE_SITE_URL` and `VITE_SECURITY_CONTACT` are validated public build configuration. Localhost remains the default and emits disallow-all robots. Build-generated per-route HTML provides metadata before JavaScript, with client metadata on navigation; page bodies remain client-rendered. Use system fonts without network font loading. No raster product screenshots or external images are needed, so image optimization/font preload do not apply. No Lighthouse score is claimed. Preserve `/status` as the functional health route and development-only labs.

## ADR-017: Strict Phase 3 review and completed infrastructure gate

The Phase 3 review corrects only confirmed defects: case-normalized public routing/canonicals, navigation focus, accessible nonvisual story content, mobile reveals, shared build/browser configuration validation and the setup-guide command. Build diagnostics identify invalid setting names without echoing inputs. The public environment schema is shared with the Node 24 SEO generator. No dependencies, domain schema or next-phase features were added.

On 2026-09-06 the user supplied working Docker and authorized the full local gate. Existing user group membership was activated with `sg docker` for the older agent process. An isolated review project passed development/production service health, all live integration tests, repeated migrations and production proxy checks, then was removed with its volumes/networks. Earlier ADR references to unavailable Docker verification are historical and superseded by TEST_REPORT.

## ADR-018: Retroactive Phase 0–2 audit

On 2026-09-06, audit the original phase prompts against commits `f17cb78`, `0c3ea57`, `b9c70db` and current `888ae88`, including Phase 3 consumers. Preserve deferred domain architecture and the Phase 3 implementation. Correct Phase 0 roadmap/traceability and Phase 2 health-route documentation drift. Shared form controls honor caller IDs for label association; CopyButton reports missing Clipboard API as unavailable. Both defects were reproduced in failing tests before correction. Add permanent seven-width lab target/focus/axe checks; no dependency or domain schema changes.

A clean `git archive HEAD` export passed frozen setup and quality/build checks; fresh isolated Docker services passed development/production health, real dependency integration tests, repeated migrations and an unmocked production browser readiness journey. A temporary no-op revision in that export exercised generation/upgrade/downgrade; it is not a product migration. The original Phase 3 accessibility smoke result does not establish universal 44px targets: direct measurements found shorter Phase 3 footer, outcome and docs-masthead links. Record those as outside-scope limitations without changing Phase 3. See TEST_REPORT for actual final commands and verdicts. No next phase is authorized.

## ADR-019: Public link touch-target correction

The user explicitly authorized fixing R012-04 after the retroactive review. Keep existing type sizes, colors and destinations. Use flex-aligned link boxes with minimum 44px height/width and vertical padding for footer links, home outcome links and the docs masthead. Footer padding replaces external margins so spacing belongs to the clickable anchor. Add browser assertions on actual rendered bounding boxes at all seven required widths, with nonempty/count checks to prevent missing selectors from passing. Existing full public axe and overflow checks remain the accessibility gate. No backend, dependency, runtime configuration or next-phase changes.

## ADR-020: Observability infrastructure scaffold

Add pinned Prometheus 3.14.0 and Grafana 13.2.1 services using official images, a dedicated internal observability network, no host ports, read-only configuration mounts and named persistent volumes. Prometheus starts with an empty scrape list. Grafana provisions a stable default datasource UID at `http://prometheus:9090`. No targets, dashboards or alerts are introduced; Phases 16/17 remain deferred. Versions were resolved from the [Prometheus downloads](https://prometheus.io/download/) and [Grafana downloads](https://grafana.com/grafana/download?platform=docker) pages. No application/schema changes or new runtime variables are needed.
