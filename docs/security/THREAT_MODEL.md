# Threat model

## Assets and trust boundaries

Assets: account/session secrets, organization isolation, target authorization, HTTP evidence, findings/provenance, policy versions and gate integrity, report bytes, integration credentials, audit history, worker capacity and cloud infrastructure.

Boundaries: browser/API; API/tenant database; queue/worker; runner/ZAP/target network; untrusted evidence/normalizer; redacted evidence/Gemini; report generator/object store/browser; GitHub/webhook receiver; worker/outbound notification destination; operator/tenant data. Threat actors include malicious tenants, compromised targets/specifications, compromised integrations, malicious external senders and compromised workers/providers.

## Threats, controls and residual risks

| ID | Threat and boundary | Required controls | Residual risk and verification |
| --- | --- | --- | --- |
| T01 | SSRF through target URLs, DNS rebinding, redirects, OpenAPI refs or notification URLs | HTTP(S) only; normalize names/IPs; deny loopback/private/link-local/reserved/multicast/metadata including IPv6 and mapped forms; validate every resolution/redirect; enforce connections through egress proxy bound to allowed addresses; bound imports and prohibit remote refs by default | Public hosts can proxy internal data; target ownership and network isolation still required. R04/R05/R15 |
| T02 | Unauthorized or over-broad scanning | Valid ownership/authorization evidence, expiry, scope enforcement on every request and redirect; active opt-in one-use or bounded schedule grant; permission recheck before execution; quotas | Ownership can change or authorized app can be damaged; authorization renewal, request limits and cancellation reduce risk. R05/R06 |
| T03 | Prompt injection in HTTP content/scanner output | Treat all evidence as data; minimized redaction, constrained prompt, schema validation, allowlisted evidence IDs, no AI tools, no policy inputs from generated output | Model can still give misleading advice; label advisory, retain source and developer verification. R09/R10 |
| T04 | Secret leakage across logs, prompts, reports, telemetry or PRs | Reference-based credentials, encryption, redaction before egress, header/query/body filters, size limits, secret-canary tests; restricted raw store; no full sensitive bodies outside raw boundary | Novel secret formats evade filters; minimize collected content and retention, block uncertain payload egress. R08/R10/R12/R15 |
| T05 | Cross-tenant IDOR, job confusion, object-store leak | Membership/project checks, org-scoped repositories, composite FKs, RLS, authenticated task context, tenant-scoped object authorization, key scope checks | Operator/database compromise remains; least privilege and audited support path. R02/R17 |
| T06 | Malicious evidence/reports causing XSS, PDF injection, traversal or remote fetch | Render escaped text, no untrusted HTML, schema/size limits, fixed PDF templates, no remote resource resolution, safe filenames, attachment/CSP/nosniff headers, authenticated downloads | PDF viewer vulnerabilities remain; avoid embedded active content and attachments. R08/R12 |
| T07 | Spoofed/replayed GitHub webhook or forged check result | Raw-body HMAC validation before processing, constant-time comparison, secret rotation, delivery-ID dedup, freshness where signed timestamps exist, project/install binding, outbox idempotency | Compromised GitHub installation can send valid events; least privilege and revoke integration. Do not invent a GitHub signed timestamp. R14 |
| T08 | Worker/scanner compromise from hostile targets | Disposable non-root pinned containers, seccomp/capability drop, read-only filesystem with bounded scratch, no host Docker socket, CPU/RAM/time/request limits, target-only egress, separate worker identities/queues | Container/kernel escape and scanner bugs remain; patch/pin/review and isolated hosts for production. R07/R18 |
| T09 | Session theft, CSRF, credential stuffing or refresh replay | Argon2id, short access TTL, HttpOnly/Secure/SameSite, CSRF+Origin, explicit CORS allowlist, refresh family rotation/reuse revocation, rate limits, generic recovery responses | XSS can act through an active session; CSP and dependency review needed. R01/R20 |
| T10 | Queue replay, duplicate active probes, stuck jobs or cancellation races | Transactional outbox, idempotency digests, leases/fences, CAS state transitions, deterministic terminal precedence, runner TTL reaper | Network partition may delay shutdown; egress grant TTL bounds it. R06/R07/R21 |
| T11 | Gate tampering, AI outage appearing clean, partial scan resolution | Immutable versioned rules, scanner-only severity, fail on incomplete execution, degraded enrichment at least warn, complete comparable scans for resolution | Misconfigured thresholds may understate risk; audit policies and expose reason codes. R11/R13 |
| T12 | Notification exfiltration and outbound webhook abuse | Owner/admin destination permission, explicit test-send, secret refs, allowlisted redacted fields, SSRF enforcement, bounded retries and idempotency | A legitimate destination can retain forwarded summaries; minimize data and document delivery. R15 |
| T13 | Abuse/DoS and cloud cost amplification | Tenant quotas, fair queue limits, bounded spec/response sizes, concurrency/crawl caps, AI budgets, schedule/grant expiry | Legitimate complex scans can exhaust budgets; show partial/timeout rather than false success. R07/R18 |
| T14 | Retention, backup resurrection and unauthorized raw retrieval | Separate raw permission, encrypted storage, lifecycle/purge jobs, expiry UI, deletion tombstone replay on restore | Backups retain deleted bytes up to 35 days; disclose and enforce horizon. R17 |
| T15 | Dependency/supply-chain and operator privilege | Lockfiles, pinned scanner digest, vulnerability review, least privilege IAM, secret manager, authenticated health surfaces, restore/runbook exercises | Upstream zero-days and privileged insiders remain; monitor and patch. R18/R19 |

## Release gates

No target scan until authorization, SSRF/network boundary and active-confirmation tests pass. No external AI/delivery until secret-canary and evidence-minimization tests pass. No multi-user release until cross-tenant API/job/download tests pass. No CI gate release until incomplete/outage policy truth tables pass. No production deployment until isolated worker compromise and backup/purge exercises pass.

This model records planned controls. It is not evidence that controls are already implemented or that security testing is complete.
