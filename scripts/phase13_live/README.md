# Phase 13 live security journeys

Run from the repository root with Docker access, the API virtualenv, Node/pnpm and Playwright Chromium installed:

```sh
apps/api/.venv/bin/python scripts/phase13_live/run.py
```

The harness builds `aegisforge-api-test`, creates a disposable PostgreSQL database, starts the actual API and its notification coordinator, and drives Chromium plus independent HTTP clients. Every Compose command uses `-p aegisforge`. It stops the shared test stack at completion, drops only its randomly named database, deletes its temporary certificates/secrets, and retains Docker volumes. Do not run concurrently with another test using ports 8000/5174 or the shared Compose project.

The three checks are:

1. Authenticated destination-creation requests reject seven malicious endpoints with HTTP 422 and persist no destinations: IPv4 loopback, metadata IP, IPv6 loopback, IPv4-mapped loopback, a hostname resolving to loopback, plaintext HTTP and a disallowed port.
2. A synthetic failed-scan row triggers the real subscription fanout and durable delivery worker. A separate HTTPS server independently verifies timestamp freshness and HMAC-SHA256 against the raw bytes before returning 204. It also rejects an intentionally invalid signature with 401. The test requires the database-backed delivery API to report `sent`.
3. Chromium creates a real API key and sees the secret once; dismissal/reload and the listing API cannot retrieve it. A new cookie-free client authenticates with that key. Direct database inspection confirms SHA-256-only storage and recorded usage. Replacing only the stored hash makes the same key fail with 401; restoring the hash restores 200. Scope denial and revocation also return 403 and 401 respectively. No secret is printed or captured in screenshots.

This is local network end-to-end coverage, not an internet-provider test. The HTTPS receiver uses a fresh private CA and `webhook.receiver.test`, resolving to a public-classified IPv4 address on the **internal-only** Docker fixture subnet `11.203.13.0/24`. That network does not send packets to the real public subnet. The API retains its unchanged destination validation, DNS resolver, TLS verification, HTTP transport, database queue and retry logic; there are no dependency overrides, monkeypatches or mocked HTTP responses. The failed scan is explicitly seeded test data, not a real target scan. No third-party message service or production credential is used.
