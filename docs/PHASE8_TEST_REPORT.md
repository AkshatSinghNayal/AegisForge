# Phase 8 verification — 2026-09-09

## Scope and implementation

Connected the worker-only `ScannerProvider` contract to `ZapScannerProvider`, retaining the explicit mock adapter. The API seals dispatch envelopes; the worker revalidates DNS, resolves credential references, configures scoped contexts/authentication, spiders or imports sanitized OpenAPI, drains passive queues, optionally runs authorized active rules, polls bounded progress and exports encrypted evidence. Collection completes as partial with an unavailable/failing effective gate; later normalization, AI, policy evaluation and reporting are not simulated.

New implementation is under `apps/api/src/aegis_api/zap/` and `zap_dispatch.py`, with coordinator/lifecycle/worker/settings integration. Migration `0006_immutable_scanner_artifacts.py` freezes every artifact metadata field. Dockerfile.scanner, the scanner runtime/demo Compose overlays, `infra/scanner/fixture.py`, the key setup helper and Compose assertions provide opt-in execution. Tests are in `test_zap.py`, `test_zap_dispatch.py` and `test_zap_live.py`. The auth browser runner now starts only its required development server. Existing uncommitted Phase 6/7 work was preserved.

See [SCANNER](SCANNER.md) and ADR-025 for the pinned official image, responsible-use warning, exact allowlist, dedicated-daemon requirement, enforcement and setup. The pin was pulled and its digest verified. Official ZAP Docker, network, OpenAPI and spider documentation was consulted. No internet target was scanned.

## Commands and observed results

Commands ran from the repository root. Host commands used the bundled Node runtime and `/tmp/aegis-tools` on PATH, with `UV_CACHE_DIR=/tmp/aegis-uv-cache`. `sg docker` activates the account's existing Docker group; no permissions were changed.

```sh
PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/tmp/aegis-tools:$PATH UV_CACHE_DIR=/tmp/aegis-uv-cache make lint typecheck schema-check
apps/api/.venv/bin/pytest -c apps/api/pyproject.toml apps/api/tests/test_zap.py -q
sg docker -c 'docker build -f apps/api/Dockerfile.scanner -t aegisforge-scanner-worker:phase8 .'
sg docker -c 'python3 scripts/check_compose.py'
PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/tmp/aegis-tools:$PATH UV_CACHE_DIR=/tmp/aegis-uv-cache make build
```

Final lint/format, strict TypeScript/mypy and generated-schema checks passed (57 Python files formatted, 34 source files typechecked). The final focused scanner suite passed **47 tests** after the DNS helper correction. Worker/gateway image build passed. Development/production/scanner Compose assertions passed. Final Vite production assets and API wheel/source distribution built successfully.

```sh
sg docker -c 'docker compose -p aegis-phase8-check -f docker-compose.yml -f docker-compose.test.yml run --rm -v /home/akshat/Desktop/aegis-4th-year/apps/api/src:/app/src:ro -v /home/akshat/Desktop/aegis-4th-year/apps/api/tests:/app/tests:ro -v /home/akshat/Desktop/aegis-4th-year/apps/api/migrations:/app/migrations:ro api pytest -q'
pnpm --filter @aegisforge/web test
```

Backend: **232 passed, 7 skipped in 187.79 seconds**, including actual PostgreSQL/Redis integration, migration roundtrips, immutable artifacts, tenant denial, real dispatch progress/fencing and failure handling. The seven skips are opt-in live ZAP cases run separately below. Two existing upstream deprecation warnings remain. This full run preceded the final implementation-only lightweight DNS helper correction; all 47 relevant scanner tests and affected live cases were rerun afterward. Frontend: **25 passed**. Overlapping targeted runs are not added to these totals.

```sh
sg docker -c 'AEGIS_RUN_ZAP_LIVE=1 apps/api/.venv/bin/pytest -c apps/api/pyproject.toml apps/api/tests/test_zap_live.py -v --tb=short'
sg docker -c 'AEGIS_RUN_ZAP_LIVE=1 apps/api/.venv/bin/pytest -c apps/api/pyproject.toml apps/api/tests/test_zap_live.py -k "active or openapi" -v --tb=short'
```

The latest full live run had **5 passed and 2 failed**: passive, cancellation, timeout, ZAP crash and network/lease enforcement passed; active and OpenAPI failed before scanner startup in the bounded DNS helper. Removing unnecessary application imports from that CPU-limited helper corrected startup. The affected rerun then passed **2/2 in 145.27 seconds**. All **7 distinct live scenarios** therefore have passing evidence across the full run and rerun; the original full run is not relabeled as entirely green.

Real tests use a disposable internal target and a separate unauthorized canary, without published ports. They assert the canary receives no HTTP requests, direct routes from ZAP to both containers fail, a foreign proxy target is denied, and heartbeat loss closes the gateway. Contract tests also assert exact socket destinations through real loopback HTTP/TLS and cover malformed responses, import warnings, provider cleanup, scope, resource arguments, DNS rejection and redaction. These assertions test the configured boundaries; they are not a claim of general container-escape resistance.

```sh
sg docker -c 'PATH=/home/akshat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/tmp/aegis-tools:$PATH python3 scripts/test_auth_e2e.py scans.spec.ts --workers=1'
```

Real-backend Chromium scan journey: **1 passed in 3.0 minutes**, using PostgreSQL, Redis and the mock Celery provider, including progress, reconnect, cancellation and desktop/mobile axe assertions. This is a browser orchestration regression, not an end-to-end browser-to-real-ZAP claim. The disposable browser stack was removed automatically.

## Corrections and review

Earlier runs exposed actual ZAP API differences: protected mode is `protect`; active scanning must use the scoped context because ZAP strips the root URL slash before its protection check; OpenAPI import returns an empty warnings list on success. These were corrected and exercised against the pinned image. Gateway readiness is polled before launching ZAP. DNS resolution runs in a limited trusted helper because the broker-only worker cannot resolve external DNS; the worker still validates every returned address. Import warnings fail closed.

An initial browser run timed out before tests while starting an unrelated production preview; auth mode now starts only its required server. A final lint run caught a long Python string, corrected before the passing rerun. Initial Docker socket permission and sandbox network restrictions were handled using the existing Docker group and approved execution. A prior automatic approval review temporarily rejected Docker execution due to an account usage limit; verification resumed when execution became available. No failed or unavailable run is counted as a pass.

Manual code/configuration review covered API isolation, socket placement, fixed image digest, resource limits, fail-closed authorization leases, immutable metadata and absence of raw evidence/credentials in broker results. This inspection is not counted as runtime testing. No human screen-reader, other browser engine or full live AJAX/HTTPS ZAP journey is claimed; HTTPS gateway enforcement is covered by actual loopback TLS tests.

## Operational limits

The provider defaults to disabled, the allowlist defaults empty, and internet active scans are always refused. Production requires a dedicated/rootless execution daemon, secure key provisioning and operator-owned retention enforcement. Local encrypted credential references are development/test only; the managed production secret adapter remains future work. Large complete artifacts use encrypted local write-once object storage, with hashes/metadata in PostgreSQL; no S3/download/retention-deletion service is added. TLS interception means certificate observations are not direct target TLS measurements. Private demo onboarding still needs an appropriately isolated validation path; the API must not join the scanner network. Real API/database handoff and real isolated execution are tested separately.

No deployment or later phase was started. The next unblocked phase requires a separate explicit request.

## Cleanup and Git handoff

The live harness removed its targets, canaries, jobs and networks in `finally`; label/name-filtered Docker queries returned no leftover scanner resources. The disposable PostgreSQL/Redis stack was removed with:

```sh
sg docker -c 'docker compose -p aegis-phase8-check -f docker-compose.yml -f docker-compose.test.yml down --volumes --remove-orphans'
git diff --check
git add apps/api/src/aegis_api/zap/contracts.py
```

The Git staging attempt failed with exit 128: `.git/index.lock` cannot be created on the protected read-only filesystem. No commit was created and no Git permissions or protected metadata were modified. Existing application stacks/data were preserved.

## Subsequent strict review

The initial handoff above is historical. See [Phase 8 strict review](TEST_REPORT.md#phase-8-strict-review--2026-09-09) for confirmed scope, authorization, failure-statistics, artifact-permission, credential-redaction and crawl/rule-policy defects, their fixes and new verification results.
