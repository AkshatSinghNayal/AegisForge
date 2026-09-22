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

## ADR-021: Phase 4 database foundation and API conventions

The explicit Phase 4 prompt replaces the provisional target CRUD phase with persistence before authentication/execution. Implement the 22 requested entities and IdempotencyRecord only, using existing locked dependencies. See [persistence architecture](architecture/PERSISTENCE.md) and the generated schema catalog. Global identity/session boundaries are explicit; tenant composite FKs and immutable identity/history triggers protect retained provenance. Relational fields/arrays carry domain state; JSONB is reserved for versioned snapshots/external advisory output. No soft deletion or fake business endpoints.

Internal tenant-scoped repositories, timestamp/enum response schemas, signed stable cursors, sanitized errors, durable transactional idempotency and version preconditions establish reusable conventions. They do not authenticate callers or execute scans/reports/webhooks. ETag comparisons apply to mutable targets; policy edits require a new immutable version. Restrict parent deletion and reserve explicit retention deletion; RLS and restricted production roles await identity/deployment. Single-project API keys/destinations avoid unchecked project-ID arrays. Existing env variables and lockfiles remain sufficient; no cursor key is needed before routes are mounted. Generate current OpenAPI and separate convention schemas, and enforce generation drift in the quality gate. No next phase is authorized.

## ADR-022: Phase 4 strict review corrections

On 2026-09-07, reproduce and fix Phase 4 false-success paths without adding authentication or execution. Commands own an internal savepoint so a caught callback exception cannot retain partial writes or a success receipt. Locked receipts refresh ORM state and read database time after locking, preventing cached expired rows from replaying work after renewal. If-Match accepts only the range supported by the persisted INTEGER version. Document readiness 503 in generated OpenAPI.

Keep applied migration 0001 unchanged. Revision 0002 adds a tenant-bound, row-locking insertion guard for passing evaluations: their state/completeness/enrichment snapshot must match the persisted scan and satisfy existing complete/downstream conditions. This validates consistency only; the deterministic policy engine and live gate reader remain future work. Latest-revision downgrade preserves foundation tables and data, while full downgrade/re-upgrade is also tested.

The stock development-only Swagger UI remains non-blocking for the persistence phase: keyboard disclosures and the requested responsive widths work, but measured badge/link/control contrast and small controls prevent an accessibility-compliance claim. Production docs stay disabled. No frontend redesign, dependency update or next-phase feature is included in this strict review.

## ADR-023: Phase 5 identity, organization authorization and real onboarding

The explicit Phase 5 prompt replaces provisional scanner orchestration with authentication, organizations, RBAC and onboarding. Reuse existing locked dependencies, SQLAlchemy records and the React design system. Add migration 0003 for access credentials, identity tokens, invitations, global identity audits, delivery status and the user's verification timestamp. No prior migration is rewritten. Global identity records cannot be tenant scoped before registration; organization invites and membership events retain tenant scope.

Use random opaque access credentials with short database-checked expiry and hashed storage. This gives immediate family/all-session revocation without a new JWT library or signing secret. Salted scrypt uses the standard library. User-row serialization protects session/reset races; organization-row serialization protects ownership and membership changes. Restrict admins from managing other admins/owners. Only explicit owner transfer changes ownership. Organization DELETE deactivates while retaining evidence references.

Require exact Origin plus CSRF cookie/header matching for every browser write. Cookies are host-only, HttpOnly, SameSite Strict and Secure in production. Frontend credentials are memory-only, refresh is single-flight with Web Locks across tabs, and external response schemas are validated with Zod. Tokens in mail links use fragments and are removed from history. SMTP delivery records contain no bodies or tokens and record unavailable/failed delivery honestly; durable mail retries remain deferred.

Implement the four role policies and mounted resource-summary reads over actual tenant/project records. Do not invent future policy/scanner write endpoints. Onboarding counts only persisted permitted state; incomplete scans do not complete a step. Guide links remain usable while creation/execution phases are deferred. The screenshot was not present, so the shell follows the explicit written visual requirements. Repository scope excludes Sites deployment or re-scaffolding. Stop after Phase 5.

## ADR-024: Phase 6 configuration and validation boundary

The explicit Phase 6 prompt supersedes provisional evidence-normalization numbering. Extend the existing tenant-scoped project, target, secret-reference and policy records with migration 0004; retain all prior migrations and immutable policy triggers. Reuse Phase 5 project/member RBAC: owner/admin project and policy administration, assigned developer target changes, assigned viewer reads. Archive preserves evidence; all policy edits append versions. No scanner or gate execution is introduced.

Use aiohttp's custom resolver boundary to pin validated addresses while retaining normal hostname TLS verification, with new validation at every redirect hop and no environment proxy/cookie/credential forwarding ([official client documentation](https://docs.aiohttp.org/en/stable/client_advanced.html)). Private RFC1918/ULA access requires an administrator policy/declaration and administrator target registration; special/metadata addresses remain denied. Runtime worker isolation and per-request enforcement are mandatory future execution work.

Bound JSON request/upload bytes before parsing; parse UTF-8 JSON/YAML without anchors/aliases/tags/external references, validate supported OpenAPI schemas and store only sanitized specifications. Use the provider protocol with local organization/reference-bound [Fernet authenticated encryption](https://cryptography.io/en/stable/fernet/); keep the key outside source control and refuse local-provider production use. OAuth and AWS managed providers are interfaces/future work, not simulated functionality. Dependencies resolve stable releases in uv.lock. Details and deliberate compatibility restrictions are in CONFIGURATION.md.

## ADR-024 — Phase 7 mock orchestration and broker-only workers (2026-09-08)

The explicit Phase 7 prompt supersedes provisional numbering. PostgreSQL scan checkpoints serve as the transactional outbox, with row-locked sequence allocation and fenced stage-result application. API-side coordinators own persistence and reauthorization; isolated Celery workers retain broker-only connectivity and receive no target or secret data. This preserves the existing network boundary without granting scanner workers database access. Redis per-job deduplication and per-scan admission supplement durable fences. SSE reads PostgreSQL and never depends on Redis for replay.

Only the network-free mock adapter exists. Finished demo scans retain partial/mock/failed component statuses and an effective fail gate; synthetic fixture metadata stays on the demo scan rather than fabricating production evidence, evaluations or reports. Real provider execution and egress enforcement remain a separately authorized phase. See SCAN_ORCHESTRATION.md for protocol, recovery bounds and limitations.

## ADR-025: Phase 8 isolated ZAP and immutable raw evidence

The explicit Phase 8 scanner prompt supersedes the provisional gate/integration phase. Keep mock stages and broker-only worker networking; add a separate `zap` queue and `ScannerProvider` contract. API coordinators seal tenant/job/fence/version-bound execution envelopes and continue current authorization checks. Only workers resolve encrypted credential references. Real jobs span discovery through collection under one fence; sanitized progress advances the persisted state and SSE without dispatching new jobs. Collection completion stays partial and cannot pass a gate. No normalization, Gemini, evaluation or report implementation is included.

Use the existing release/digest-pinned official ZAP container, loopback-only key-protected management API and container-exec transport. A fresh internal network connects ZAP only to a separate IP-pinned HTTP/TLS gateway, which checks origin/path/method/rate/request/deadline limits for every request. The gateway has no API/broker/database connection. Its independent ten-second heartbeat cutoff denies traffic after worker loss; hard deadlines and a separate reaper reclaim expired resources. Enforce CPU/memory/process/tmpfs limits at container creation. Serialize real jobs globally; never automatically replay active execution. Default empty allowlist and unconditional internet-active denial are independent of tenant authorization.

Reuse RawScanArtifact and add migration 0006 to reject all artifact UPDATEs, including provenance hashes; retain tenant-safe FKs. Store complete bounded raw alerts/messages as encrypted write-once local objects, with conservative redacted derivatives and hash/size/version metadata in PostgreSQL. Retention deletion, production managed secrets and S3 remain explicit operational boundaries. TLS interception means certificate-level observations are not direct target TLS measurements. See SCANNER.md for the official documentation sources, deployment boundaries and training fixture.

Phase 8 strict review hardens that execution boundary: reject ambiguous normalized paths; recheck gateway leases/deadlines after waits and request-body reads; atomically persist failure statistics; secure every artifact directory; and emit `zap-redaction-v2` derivatives that also redact credential components. URL policies with no crawl or zero depth are incompatible and fail before startup, because ZAP interprets zero as unlimited. AJAX receives the same positive policy depth. Active rule IDs must exist in the installed inventory. No downstream phase or production secret adapter is added by this review.

The AJAX startup review also requires real browser observations before collection can succeed. Firefox uses a bounded writable profile mount and font-cache path; bundled WebDriver executables have their own bounded executable tmpfs. Measured saturation of ZAP's former 256-process ceiling prevented control commands despite memory use below 1 GiB, so its bounded ceiling is 512; gateway processes remain limited to 256. No capability, root-filesystem, Firefox sandbox or egress restriction is removed.

## Phase 9 — evidence-preserving normalization

Use `zap-normalizer-v1` and `zap-fingerprint-v1` with the documented canonical JSON/SHA-256 contract in [FINDING_NORMALIZATION](FINDING_NORMALIZATION.md). Normalize inside the isolated worker after durable raw export; persist every observation separately and retain source pointers, classification, masked excerpts and redaction metadata. Never infer reviewer false-positive state from scanner confidence.

Comparability is conservative: exact frozen configuration, policy identity, scan mode and algorithm versions. Complete comparable evidence alone can establish absence; dispositions persist, and version-checked reviewer changes generate immutable history and audit events. AI/policy tabs reflect stored availability. No new dependencies or environment variables; migration 0007 refuses downgrades that would discard Phase 9 evidence.

## Phase 10 — advisory schema-constrained AI (2026-09-10)

- Use the official Google Gen AI Python SDK, locked at 2.22.0, behind `AIProvider`, with deterministic explicitly labeled local/test mock. Default off; no optional large local model or adapter bundled.
- Classification-only input minimizes disclosure: no free target/scanner text, headers, bodies, URLs or reviewer notes. This is a deliberate conservative limit on guidance specificity. Cite the exact supplied occurrence and disclose the evidence limitation.
- Independent strict Pydantic validation, bounded output/arrays, exact documentation URL allowlist, inert React rendering, server-applied hypothesis labels and output/feedback masking enforce the advisory boundary. AI has no evidence/policy mutation capability.
- Explicit on-demand generation, three bounded attempts with jitter, generic degraded failures and one-minute per-finding cooldown. No automatic scan-time provider costs or background AI queue in this phase.
- Migration 0008 retains immutable regeneration versions and separate immutable tenant-scoped feedback. Feedback is never automatically trained on or sent to providers. See [AI guidance](AI_GUIDANCE.md) and [verification](PHASE10_TEST_REPORT.md).

## Phase 10 strict review corrections — 2026-09-10

Output validation advances to `guidance-v2`, while the unchanged input prompt remains `guidance-v1`. Redaction uses targeted complete-value masking before truncation rather than the scanner artifact helper, so security guidance is not erased and email suffixes cannot leak at its former 1,024-character boundary. Blank fields, duplicate JSON keys/citations and overlong labeled hypotheses fail closed. Gemini must report one completed STOP candidate. Typed API response models publish the structured contract; the underlying analysis query is typed. Citation navigation restores keyboard focus and a failed feedback save clears stale success text. See the current [strict review report](TEST_REPORT.md).

## Phase 11 — deterministic project policies (2026-09-11)

- Keep scanner execution policies separate from project gate-policy versions. Freeze the active gate and environment into scan configuration; bind active confirmation to its identity. Gate-only changes preserve comparison families.
- Use a closed structured `gate-v1` schema and pure `deterministic-v1` evaluator. Count distinct findings, retain all matching occurrences, AND conditions/OR lists, and order outcomes fail > warn > pass after an overriding incomplete/fail-closed evidence guard.
- Remove the old enrichment-complete dependency from passing gates. Enrichment status and AI output never affect decision inputs or digests. Demo evidence and incomplete scans cannot pass at either the engine or database boundary.
- Store exceptions in immutable policy versions with exact project-finding scope, active member owner, reason, server-recorded admin approval and bounded lifetime. Current accepted-risk state is required; expiry is evaluated at the captured input time.
- Retain every re-evaluation as a new immutable row, including identical digest/result replays. Append activation history; serialize publication and activation using existing organization/project locks. No reports or next-phase work is authorized.

## Phase 12 — analytics and authenticated workspace

Dashboard aggregates run as one scoped PostgreSQL statement so cards/charts/table rows share an MVCC snapshot. Time windows are aware, half-open and bounded to 366 days; daily buckets use an IANA display timezone. Undefined ratios/means return null, incomplete scans never become clean results, and latest retained evaluations count once per complete scan. Current-state inventory and observation-frequency trends are intentionally distinct; [metric definitions](ANALYTICS.md) specify each population.

The existing report/integration/API-key tables gain safe paginated metadata registries and authorized revocation/deactivation, without fabricating report artifacts or provider connections. CSV exports are page-scoped safe columns with formula neutralization. No schema or runtime configuration change. Later-phase generation/provider/key authentication work is not implied by navigation entries.

## Phase 13 — reports, delivery and machine access (2026-09-13)

- Generate from immutable allowlisted snapshots. Retain IDs/classifications/provenance and advisory AI labels, withhold free-form evidence and prose, and force incomplete/demo/unsuccessful scan reports to a nonpassing result. Regeneration inserts a new version; migration 0010 enforces version uniqueness and snapshot immutability.
- Run durable report/notification jobs on the API side with database row claims, leaving the isolated scanner worker without database or delivery credentials. Use off-thread rendering/storage, fixed safe failures, at-least-once notification delivery and explicit dead-letter/manual retry semantics.
- Use write-once private local objects for development and private SSE-KMS S3 objects for production. Short-lived HMAC/SigV4 URLs are bearer capabilities after authorization; expiry caps download access and storage cleanup, while snapshots remain auditable.
- Encrypt notification address/credentials with a dedicated tenant/destination-bound Fernet key. Resolve and pin public DNS results on every HTTP connection, forbid redirects/proxies/private endpoints, sign generic payload bytes and validate GitHub PR metadata before posting. Payloads contain fixed text and internal links only.
- Issue high-entropy organization keys once, store only SHA-256 and metadata, apply current creator membership, scopes, shared Redis quotas and usage audit. `/api/public/v1` is API-key-only; existing browser session/CSRF routes remain separate. Reuse scan authorization and confirmation logic; namespace required scan idempotency by credential ID.
- Adapters are implemented and tested with controlled transports. Live third-party delivery and AWS access require deployment credentials and explicit destination authorization; no external messages or cloud objects were created during implementation.

## Phase 14 — reproducible CI and signed repository mappings

- Reuse organization-key authentication, deterministic retained evaluations, scan authorization and transactional outbox. The CI contract resolves and checks exact project/target/environment and scanner/gate policy versions. Unattended automation supports passive/baseline policies; active scanning retains its explicit one-use confirmation path.
- A dependency-free Python runner uses bounded HTTPS requests without redirects/proxies, stable credential-scoped idempotency, terminal polling, fail-closed exits and bounded cancellation. Output is an allowlist of enums, UUIDs, counts and authenticated links. AI text and scanner evidence never enter Actions artifacts, logs or comments.
- Pin Actions to verified upstream commits, check out only a reviewed script SHA, restrict supported triggers, separate comment permissions and serialize comment writers. Same-repository PRs still require trusted workflow review/environment protection. A bot-owned hidden marker is updated in place; ambiguous comment creation is not retried blindly.
- Migration 0011 adds tenant-safe mapping and delivery tables. Encrypt one-time webhook secrets with the existing notification encryption key and purpose/tenant/mapping binding. Verify exact-byte HMAC and UUID delivery headers; allow only configured push/PR events and ping. Resolve registered target UUIDs only. Organization locks and durable unique receipts make enqueue atomic and deduplicate both delivery IDs and payload replays.
- Setup connection tests explicitly distinguish local readiness from signed inbound ping connectivity. Retain safe delivery metadata; replace disabled mappings to update versions or rotate secrets. No live GitHub messages were sent. See [GITHUB_ACTIONS](GITHUB_ACTIONS.md) for contracts and operational limits. Stop after Phase 14.
