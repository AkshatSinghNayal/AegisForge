# Isolated OWASP ZAP execution — Phase 8

Use scanners only against systems you own or are explicitly authorized to test. Active scans can modify application data. An administrator allowlist, current target authorization, an immutable active policy and the existing single-use confirmation are all required. **Internet active scanning is always refused.** The default provider remains `none` and the execution allowlist defaults to empty.

## Official image and API sources

The [official Docker guide](https://www.zaproxy.org/docs/docker/about/) describes stable release containers and daemon operation. Stable tags receive rebuilds, so execution retains the existing **2.17.0** release and immutable digest:

```text
ghcr.io/zaproxy/zaproxy:2.17.0@sha256:781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef
```

The worker checks the running core version. No automatic add-on updates run. [Network API](https://www.zaproxy.org/docs/desktop/addons/network/api/) configures the upstream proxy; [OpenAPI importFile](https://www.zaproxy.org/docs/desktop/addons/openapi-support/) imports sanitized local files with the target override and context. [Spider API](https://github.com/zaproxy/zaproxy/wiki/ApiGen_spider) documents depth and scope options. Container/API output is data, never an instruction source.

## Boundaries and lifecycle

The API coordinator validates current organization/project membership, target/policy versions, credential references and authorization on every reconciliation. Its dispatch envelope is authenticated/encrypted, bound to organization, scan, job, fence and version snapshots. Redis receives ciphertext, never plaintext credentials. The worker has broker access but no database/API network membership. Only the worker decrypts selected credentials; tenant/reference prefixes must match.

The optional scanner worker consumes the `zap` queue. Mock workers keep the `celery` queue. A Redis global admission slot permits **one real job across workers**; per-scan/job fences prevent redelivery. A ten-second renewable coordinator lease expires on cancellation, authorization revocation or coordinator/database failure. Checks occur between bounded operations; a blocked API request can add up to 15 seconds before resource cleanup. Hard watchdogs and an independent 15-second reaper cover worker death. A cleanup failure fails the job and retains admission until expiry. Real executions are never automatically retried; a fresh active run needs another confirmation.

A bounded trusted DNS-only helper resolves the allowlisted hostname on the execution daemon, because the broker-only worker network cannot resolve public DNS. The worker validates every returned address before using the pin. The helper has a ten-second process deadline, CPU/memory/process limits and no application networks. Each scan then creates an internal Docker network, ZAP and a separate egress gateway. ZAP has no public port, database, Redis, Docker socket or infrastructure connection. Its API binds `127.0.0.1`, requires a random per-job key and is accessed only through container execution with stdin. Docker logs are disabled. The gateway joins the isolated scanner network plus an operator-selected egress network. It pins the freshly validated IP and port and checks origin, decoded paths, excluded paths, methods, rate, request count and deadline for every upstream request. Redirects undergo the same checks. Ambiguous repeated slashes, semicolon path parameters, traversal and nested encodings are rejected. Authorization and deadlines are checked again after rate waits and request-body reads; gateway failure statistics are published atomically. ZAP cannot route around the gateway. TLS CONNECT terminates at the gateway, permitting the same path/method enforcement for HTTPS; upstream TLS still validates the real hostname/certificate. **TLS/certificate-level observations reflect this interception and must not be presented as direct target TLS measurements.**

ZAP defaults to 1 CPU, 2 GiB memory (no swap), 512 processes, bounded tmpfs and a scan-duration watchdog. Gateway defaults to 0.5 CPU, 256 MiB and 256 processes. Both drop all capabilities and forbid privilege escalation. Firefox profile state uses a bounded 64 MiB writable tmpfs; the bundled WebDriver uses a separate 128 MiB executable tmpfs with nosuid/nodev. Firefox font caches use `XDG_CACHE_HOME=/tmp/browser-cache` inside the existing 256 MiB temporary filesystem. The root filesystem remains read-only. Limits apply at Docker creation, not only in policy metadata. Requests are bounded to 1 MiB and upstream responses to 4 MiB; over-limit or transport-failed scans fail rather than claiming full coverage. Native socket/OAST/WebSocket protocols cannot bypass HTTP scope restrictions.

URL targets require a traditional/AJAX policy with a positive maximum depth. No-crawl and zero-depth URL policies fail before scanner startup; zero is not passed through as ZAP’s unlimited-depth sentinel. OpenAPI import may use a no-crawl policy. URL targets use the traditional spider and add AJAX only for an AJAX-enabled policy, with the policy depth applied to both crawlers. A stopped AJAX spider with zero observations fails collection and triggers cleanup. OpenAPI targets are re-sanitized and imported without external references or document-controlled servers. Passive queues drain before collection and again after authorized active scanning. Only allowlisted active rules are enabled, and every requested rule must exist in the pinned scanner inventory; missing rules fail the scan. All progress is a closed stage enum, persisted as sanitized ScanEvents with replay deduplication.

A successful Phase 8 run completes **evidence collection**. Completeness remains `partial`; enrichment/report status remain pending and the effective gate remains `fail / evaluation_unavailable`. Normalization, AI explanations, deterministic gate evaluation and report generation are not simulated or started.

## Evidence and object storage

The worker preserves every supplied alert field, including rule/plugin ID, name, risk, confidence, CWE/WASC, URI, method, parameter, attack, evidence and references. Linked messages retain bounded request/response headers and bodies. The original JSON is encrypted with a separate Fernet artifact key and stored in a local write-once object namespace. An `O_EXCL` write prevents replacement; filenames contain organization/scan/artifact UUIDs. RawScanArtifact stores hashes, scanner/redaction versions, size, MIME type, key reference and retention metadata. Migration 0006 freezes every raw-artifact field using the existing immutable-record trigger function. Composite tenant foreign keys continue to apply; no new table or column is introduced. Downgrade restores the prior identity-only update guard without deleting evidence.

Ordinary derivatives use a deliberately conservative field allowlist: credentials, URLs/query values, arbitrary evidence, headers and bodies are omitted. Configured secret values, Bearer token components, decoded Basic credential components, URL-encoded variants and operator redaction patterns are additionally removed from retained text. New derivatives use `zap-redaction-v2`; version 1 receipts remain readable as historical provenance. The complete encrypted original remains available for later restricted evidence processing. Object directories/files are 0700/0600. No raw content is returned through the broker or scan UI.

Local artifact keys must be backed up securely and provisioned only to the scanner worker. Production credential references still require the separately planned managed secret adapter; local credentials are refused in production. This phase does not add S3, download endpoints or a retention-deletion service. Retention timestamps are metadata; operators must schedule lifecycle enforcement before a production rollout. An object written just before cancellation/DB failure can be orphaned; it must not be treated as a completed scan or a gate result.

Verification boundary: `SecretStore` is a local seal/open protocol, not an implemented KMS/Secrets Manager adapter. `ZapScannerProvider` directly decrypts the local Fernet ciphertext inside the worker; the API dispatch path selects tenant/target-scoped references and seals ciphertext without decrypting credentials. `test_secrets_worker_scope_and_redaction` exercises actual decryption and scope rejection against a fake scanner runtime and checks the authorization replacement passed to ZAP. Configuration tests cover local encryption and production refusal; redaction tests cover Bearer/Basic components. The live Docker fixtures have no credential references, so authenticated header delivery through real ZAP and the complete saved-reference-to-target path were not exercised. Cloud retrieval, IAM, KMS rotation and cloud failure handling are neither implemented nor tested. Live scans do exercise encrypted local artifact export/decryption; PostgreSQL integration separately verifies immutable metadata and cross-tenant denial. No cloud storage, key recovery/rotation or automated retention lifecycle is claimed.

## Run a local scanner

Use a dedicated/rootless Docker daemon for execution. The scanner worker's Docker socket grants control of that daemon; **do not attach the API/application host's privileged daemon in production**. The application stack and the scanner execution daemon are independent. Build the gateway image and pull ZAP on the execution daemon as well as building the worker on its own host.

```sh
uv run --project apps/api python scripts/configure_scanner.py
docker build -f apps/api/Dockerfile.scanner -t aegisforge-scanner-worker:phase8 .
docker pull ghcr.io/zaproxy/zaproxy:2.17.0@sha256:781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef
```

Set `AEGIS_SCANNER_SOCKET` to the dedicated daemon socket, `AEGIS_SCANNER_SOCKET_GID` to its group, and `AEGIS_ZAP_ALLOWLIST` to an explicit JSON array of exact origins (scheme, hostname, nondefault port; no trailing slash). Keep `AEGIS_ZAP_EGRESS_NETWORK=bridge` only for the dedicated daemon's ordinary outbound network. Supply a restrictive isolated network for private training targets. Do not put plaintext keys in shell commands, screenshots or committed files.

```sh
docker compose -p aegisforge -f docker-compose.yml -f docker-compose.scanner.yml --profile scanner-runtime up --build -d
```

The existing idle `scanner` profile is retained for the foundation's no-network image inspection; it is not the execution runtime. Real execution uses the `scanner-runtime` overlay.

## Intentionally vulnerable demo

Run on the execution daemon, separately from the application stack:

```sh
docker compose -p aegisforge -f docker-compose.scanner-demo.yml --profile scanner-demo up -d --wait
```

The training fixture is `http://172.30.88.10:8000`, reachable only on internal network `aegis-scanner-fixture`. It has reflected input and deliberately missing security headers. It stores no real user data. Configure the exact allowlist `["http://172.30.88.10:8000"]`, the egress network `aegis-scanner-fixture` and an authorized internal-test policy. The fixture publishes no ports and cannot contact the internet. The application target-validation service also needs an appropriately isolated validation path to onboard a private target; do not join the API to this scanner network. The live test harness constructs worker contracts directly for the disposable fixture and exercises the API/database handoff separately.

```sh
AEGIS_RUN_ZAP_LIVE=1 uv run --project apps/api pytest apps/api/tests/test_zap_live.py -v
docker compose -p aegisforge -f docker-compose.scanner-demo.yml --profile scanner-demo down
```

Live tests create their own unique internal network, target and unauthorized canary; every fixture is removed in `finally`. No internet target is scanned. See PHASE8_TEST_REPORT for observed results and remaining verification limits.

Strict review results and confirmed fixes are recorded in [TEST_REPORT](TEST_REPORT.md#phase-8-strict-review--2026-09-09). The official [spider options](https://www.zaproxy.org/docs/desktop/addons/spider/options/) document the zero/unlimited depth behavior; the [official AJAX API client](https://github.com/zaproxy/zap-api-python/blob/main/src/zapv2/ajaxSpider.py) documents the separate AJAX depth option.
