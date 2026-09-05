# Containers and execution boundaries

| Container/system | Responsibility | Trust, communication and failure behavior |
| --- | --- | --- |
| Web | React public site and authenticated application | Same-origin HTTPS API; no provider/storage secrets; display evidence separately from generated advice |
| API | FastAPI authentication, RBAC, validation, resources, orchestration commands | PostgreSQL transactions and outbox; never execute ZAP in request process; bounded request sizes |
| Worker | Celery scan orchestration, normalization, enrichment, reports, deliveries | Separate queues/identities for scan and notification work; leases and fencing; no broad host access |
| Scanner runner | Narrow per-scan container provisioning | Runs pinned ZAP, enforces CPU/RAM/deadline/network scope, exposes no arbitrary execution or Docker socket |
| ZAP | Spider/passive/authorized active scanning | Disposable non-root restricted container; target-only egress, no API/database/metadata access; resource limits |
| PostgreSQL | Authoritative tenant records, state/events, outbox and policy versions | Tenant-safe constraints, transaction/CAS transitions, backups; queue loss must not lose scans |
| Redis | Celery transport, transient locks and rate limits | Private authenticated transport; no scanner evidence or durable truth; recover from database/outbox |
| Filesystem / S3 | Encrypted evidence and generated report bytes | Separate restricted raw and redacted/report namespaces; tenant-scoped metadata, private buckets, lifecycle deletion |
| Gemini | Schema-constrained advisory analysis | Redacted minimal input; timeouts/retry budget; provider status separate from findings; no gate authority |
| GitHub Actions | Build/test target, submit scan, await gate | Scoped API key or integration credential; signed webhooks deduplicated; required checks configured in repository |
| Notifications | SMTP, Slack, generic webhook, GitHub PR delivery | Transactional outbox, sanitized minimal summaries, SSRF protection, delivery retry/dead-letter status |
| Production platform | EC2 workloads, RDS PostgreSQL, ElastiCache Redis, S3, CloudWatch, optional ALB | Private data services, least privilege IAM, TLS, separate scanner network and secret manager; restore exercises |

## Deployment and orchestration rules

Local Compose provides API, web, worker, PostgreSQL and Redis; the restricted runner is distinct from the API. Development storage uses filesystem through the same interface as private S3. Mock/disabled AI is supported locally and visibly indicated. Production rejects mock mode. CloudWatch receives structured metadata, not raw findings, bodies or secrets.

Create scan plus outbox message atomically. Dispatcher publishes at least once; worker claims a scan using a lease and fencing token. PostgreSQL records every transition and ordered event before client notification. Delivery and report side effects have unique job keys. Queue consumers reconstruct progress after restart; no blind replay of active probes. If scanner continuity or evidence completeness cannot be established, fail the run and create a separately authorized retry scan.

## Scan sequence

```mermaid
sequenceDiagram
    actor User
    participant Web
    participant API
    participant DB as PostgreSQL
    participant Queue as Redis and outbox
    participant Worker
    participant ZAP as Isolated ZAP
    participant Target as Authorized target
    participant AI as Gemini
    participant Store as Private storage
    User->>Web: Configure target and authorize scope
    opt Active scan requested
        User->>Web: Explicitly confirm active configuration
        Web->>API: Create version-bound confirmation
    end
    Web->>API: Create scan with idempotency key
    API->>DB: Validate membership and authorization, save draft
    Web->>API: Start scan
    API->>DB: Consume confirmation if active, queue scan and outbox
    DB-->>Queue: Publish pending job through dispatcher
    Queue->>Worker: Deliver scan ID and organization ID
    Worker->>DB: Claim lease and validate current authorization
    Worker->>ZAP: Provision bounded scan context
    ZAP->>Target: Crawl and passive observation
    opt Active policy and valid confirmation
        ZAP->>Target: Authorized bounded active probes
    end
    Target-->>ZAP: HTTP observations
    ZAP-->>Worker: Artifacts and coverage manifest
    Worker->>Store: Encrypt restricted raw, write redacted derivative
    Worker->>DB: Save normalized findings and evidence references
    Worker->>AI: Redacted evidence and constrained schema
    alt Valid analysis
        AI-->>Worker: Evidence-linked advisory JSON
        Worker->>DB: Save validated AI analysis
    else Outage or invalid output
        Worker->>DB: Mark enrichment degraded, preserve findings
    end
    Worker->>DB: Evaluate deterministic versioned policy
    Note over Worker,DB: Incomplete scan fails, degraded AI never passes
    Worker->>Store: Generate redacted reports
    Worker->>DB: Persist report status and terminal scan event
    Web->>API: Read scan and ordered events
    API-->>Web: Findings, completeness, guidance and gate
```

Failure transitions, component retry exhaustion, cancellation and fencing are specified in SCAN_STATE_MACHINE. This diagram illustrates a successful scanner path with enrichment degradation; it does not imply scanner failures proceed as clean scans.
