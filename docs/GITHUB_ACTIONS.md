# GitHub Actions and inbound webhooks

Phase 14 provides `.github/workflows/aegisforge-scan.yml`, a reusable workflow, and `scripts/aegisforge_ci.py`, a dependency-free Python 3.12+ client. It calls the real organization-key API. It never starts a scanner locally, builds PR code, sends evidence to GitHub, or invents a gate verdict. Configure a running API, coordinator and authorized scanner as described in [SCANNER](SCANNER.md). Mock/demo scans remain nonpassing.

## Setup

1. Apply migration 0011 with `docker compose -p aegisforge run --rm api alembic upgrade head`. PostgreSQL stores mappings, encrypted webhook secrets and safe delivery receipts. There are no new Python/npm dependencies.
2. Register and currently authorize a target; record its project UUID, target UUID, environment and passive/baseline scanner policy UUID. Activate a deterministic **project gate policy**. Active scanner policies require the existing per-scan explicit confirmation flow and are deliberately unavailable through unattended CI/webhooks.
3. In **API Keys**, create an expiring organization key with only `scans:create` and `scans:read`. Copy its one-time value into GitHub Actions secret `AEGISFORGE_API_KEY`. The server stores only a hash; no retrieval endpoint returns the key. Expiry, revocation, creator membership, role, rate limits and tenant boundaries apply on every request.
4. Copy both workflow and script into your caller repository. Review them, commit them, and set repository variable `AEGISFORGE_CLI_REF` to that full 40-character commit SHA. This is a reviewed script revision, **not** the PR commit. The reusable workflow checks out only that script with persisted Git credentials disabled. Third-party actions are pinned to commits verified against their official repositories.
5. Set repository variables `AEGISFORGE_API_URL` and `AEGISFORGE_APP_URL` to HTTPS origins (no credentials, path, query or fragment); `AEGISFORGE_PROJECT`, `AEGISFORGE_TARGET`, and `AEGISFORGE_POLICY` to UUIDs. This policy is the scanner policy; the server resolves and freezes the active project gate separately. Set the examples' environment to the registered target environment.
6. Protect workflow/script changes with branch rules and CODEOWNERS. Configure required reviewers on the GitHub deployment environment used by the scan job, particularly for same-repository PRs. A modified caller workflow itself is privileged code and must be reviewed before receiving secrets. Fork PRs are skipped; do not enable secrets for forks. This workflow accepts push, same-repository pull_request and workflow_dispatch events only.

Keep the API key in GitHub Secrets, never command arguments, files, `set -x`, or workflow source. Set `AEGIS_NOTIFICATION_ENCRYPTION_KEY` on the API when using inbound webhooks: the existing Fernet key also encrypts webhook secrets with purpose, tenant and mapping binding. Do not rotate that encryption key without re-encrypting retained destinations/mappings. API keys and GitHub webhook secrets are different credentials.

## Push example

Save as `.github/workflows/security-push.yml` in the caller repository after copying the reusable workflow and script. Use an already deployed, registered staging target. A commit SHA is attribution; it does not deploy that commit. Add `needs: deploy-staging` when integrating with your deployment job.

```yaml
name: Security on push
on:
  push:
    branches: [main]
permissions:
  contents: read
  actions: read
  pull-requests: write
jobs:
  security:
    uses: ./.github/workflows/aegisforge-scan.yml
    with:
      trusted-ref: ${{ vars.AEGISFORGE_CLI_REF }}
      api-url: ${{ vars.AEGISFORGE_API_URL }}
      app-url: ${{ vars.AEGISFORGE_APP_URL }}
      project: ${{ vars.AEGISFORGE_PROJECT }}
      target: ${{ vars.AEGISFORGE_TARGET }}
      policy: ${{ vars.AEGISFORGE_POLICY }}
      commit: ${{ github.sha }}
      branch: ${{ github.ref_name }}
      environment: staging
      timeout: 900
      poll-interval: 5
      warn-exit: 2
      fail-exit: 1
      incomplete-exit: 3
    secrets:
      AEGISFORGE_API_KEY: ${{ secrets.AEGISFORGE_API_KEY }}
```

For centralized reuse, reference your reviewed workflow as `OWNER/REPO/.github/workflows/aegisforge-scan.yml@FULL_COMMIT_SHA`. The script checkout still comes from the **caller** repository at `trusted-ref`; GitHub reusable workflow checkout semantics do not automatically select the workflow's repository.

## Pull-request example

Save as `.github/workflows/security-pr.yml`. The optional comment job alone receives pull-request write permission. Set `pr-comment: false` for scanning without comments. GitHub validates the permission ceiling of every nested job even when skipped, so the caller must allow the permissions shown in both examples; the scan job itself receives only contents-read. To prohibit comment permission entirely, remove the `comment` job from your local reusable workflow and then remove actions-read and pull-requests-write from the caller. No PR is posted by installing the integration; only explicitly enabled workflow runs send comments.

```yaml
name: Security on pull request
on:
  pull_request:
    branches: [main]
    types: [opened, synchronize, reopened]
permissions:
  contents: read
  actions: read
  pull-requests: write
jobs:
  security:
    if: github.event.pull_request.head.repo.full_name == github.repository
    uses: ./.github/workflows/aegisforge-scan.yml
    with:
      trusted-ref: ${{ vars.AEGISFORGE_CLI_REF }}
      api-url: ${{ vars.AEGISFORGE_API_URL }}
      app-url: ${{ vars.AEGISFORGE_APP_URL }}
      project: ${{ vars.AEGISFORGE_PROJECT }}
      target: ${{ vars.AEGISFORGE_TARGET }}
      policy: ${{ vars.AEGISFORGE_POLICY }}
      commit: ${{ github.event.pull_request.head.sha }}
      branch: ${{ github.head_ref }}
      pull-request: ${{ github.event.pull_request.number }}
      environment: staging
      pr-comment: true
    secrets:
      AEGISFORGE_API_KEY: ${{ secrets.AEGISFORGE_API_KEY }}
```

No `pull_request_target` or untrusted checkout is needed. Branch/ref inputs travel as environment values, never interpolated shell code. The comment contains only a fixed heading, gate enum, severity counts and an authenticated application link. A project/target-specific hidden marker identifies the existing `github-actions[bot]` comment. The client paginates, ignores user-forged markers and PATCHes the matching bot comment; it POSTs only when absent. Repository/target/PR concurrency serializes workflow writers. Do not run other workflows with a different concurrency group against the same marker. An ambiguous POST is not automatically retried; the next run lists comments before writing. Over 10,000 comments fails closed instead of risking a duplicate.

## Runner behavior and inputs

All workflow inputs above map to CLI flags (`--project`, `--target`, `--policy`, `--commit`, `--branch`, `--pull-request`, `--environment`, `--timeout`, `--poll-interval`, `--warn-exit`, `--fail-exit`, `--incomplete-exit`). `--repository`, `--run-id`, and `--job` default to GitHub runner metadata; supply them for local reproduction. The only API credential input is environment variable `AEGISFORGE_API_KEY`.

- The context request checks project/target/environment consistency and current authorization. Submission checks the exact target, scanner policy and project gate versions again; a configuration change fails closed.
- SHA-256 idempotency includes repository, workflow run ID, job ID, commit, target, scanner policy identity/version, target version, environment and project gate identity/version. Retries use the same key; `run_attempt` is excluded. Existing API receipts expire after 24 hours; a later replay can create a new scan. Configuration changes intentionally change the key. A webhook and an Actions invocation are distinct triggers; choose one if you want only one scan per event.
- The API namespace also binds the key credential. Rotating credentials can create a new scan. Do not rotate keys in the middle of a retry sequence.
- Four bounded attempts retry network failures, 429 and selected 5xx responses. TLS verification remains enabled; redirects and environment proxies are refused. API bodies, transport exceptions and headers are never logged. Response sizes are bounded and only validated allowlisted fields enter output.
- Polling ends on completed, failed, cancelled or timed_out. The server uses the retained deterministic evaluation for the frozen gate. Unfinished, failed, partial, demo, missing-normalization and missing-evaluation results cannot pass. Counts are null when normalized evidence is unavailable, not misleading zeroes.
- Exit defaults: pass **0**, warn **2**, fail **1**, incomplete/transport failure/timeout/cancellation **3**. `warn-exit: 0` permits warnings. Fail and incomplete codes must be 1–125; invalid configuration cannot turn failure into success. API policy `incomplete_outcome: fail` is respected.
- Timeout is 1–21,000 seconds, below the workflow's six-hour job bound. Poll interval is 1–300 seconds; keep it at least five seconds for shared API quotas. SIGINT/SIGTERM and timeout attempt a bounded server cancellation. A killed runner or lost creation response may prevent cancellation; the server's independent scan deadline remains authoritative.
- The script creates a conservative redacted JSON artifact before networking, updates it while polling, and appends a GitHub job summary. The upload step uses `always()` with a seven-day retention. GitHub may prevent any cleanup/artifact upload after hard termination; no workflow can guarantee those effects after runner loss. Missing artifacts fail the upload step. The optional comment job is skipped on workflow cancellation.

Example local reproduction (set the secret using your secret manager or protected shell environment first):

```sh
python3 scripts/aegisforge_ci.py \
  --api-url https://api.example.com --app-url https://app.example.com \
  --project "$PROJECT_ID" --target "$TARGET_ID" --policy "$POLICY_ID" \
  --environment staging --repository owner/repo --run-id local-123 --job scan \
  --commit "$COMMIT_SHA" --branch main --timeout 900 --poll-interval 5
```

## Inbound webhook setup

In **Integrations → GitHub Actions and webhooks**, enter the exact `owner/repo`, push/PR base branch, registered project/target/scanner-policy UUIDs, environment and enabled events. Creation freezes current versions and generates a new high-entropy webhook secret. Copy it immediately into GitHub **Settings → Webhooks**; dismissing or leaving the page removes it from the UI. Lists never return the stored secret. Use the displayed `/api/hooks/github/MAPPING_UUID` path on the public API origin, `application/json`, SSL verification and the selected events.

**Test connection** checks local authorization, decryptability and version compatibility; it does not claim to contact GitHub. Send a GitHub webhook ping to verify actual inbound connectivity and inspect **Last GitHub deliveries**. Disable and recreate mappings to change versions, event settings, repository/branch, target or secret. Disabled mappings and revoked/demoted creators cannot trigger scans. Ownership authorization is rechecked at submission and by the existing coordinator.

The receiver validates `X-Hub-Signature-256` using constant-time HMAC-SHA256 over the exact raw body and requires a UUID `X-GitHub-Delivery`. It supports only `ping`, `push`, and `pull_request`; pull requests accept only opened/synchronize/reopened, an exact configured base branch and the same repository for head and base. Deleted pushes, other branches, unsupported repositories and fork PRs are rejected. Unknown payload fields (including URLs, deployment addresses, titles and bodies) never become scan configuration. Header event type is allowlisted separately because GitHub's signature covers the body, not those headers.

Receipts and scan/outbox records commit atomically under the organization's existing command lock. Unique database constraints deduplicate delivery ID and event/body SHA-256 per mapping, including replay with a changed delivery header. Retain receipts for the mapping's lifetime; purging them removes replay protection. No payload, signature or secret is retained in delivery history. Valid signed but unmapped events retain `rejected`; authorization/version/quota failures retain `blocked`; successful scans retain `accepted`; connectivity checks retain `ping`. Reusing a delivery ID with different bytes/event returns 409. Duplicate accepted/rejected/blocked receipts return their saved state without scanning again. A blocked delivery requires a new event after repair; changing a mapping requires a replacement mapping. Invalid signatures and unsupported top-level event types do not create receipts.

Inbound receipt handling only performs database validation and durable enqueue, not scanning or outbound network calls. GitHub does not automatically redeliver failed webhooks; use its delivery management UI to retry transient failures. Lock contention can exceed GitHub's delivery timeout; redelivery is safe after the original transaction commits.

## API routes

Machine routes (organization determined exclusively by the key): `POST /api/public/v1/ci/context`, `POST /api/public/v1/ci/scans` with `Idempotency-Key`, `GET /api/public/v1/ci/scans/{id}/summary`, and idempotent `POST /api/public/v1/ci/scans/{id}/cancel`.

Session-only administrator routes: `GET/POST /api/v1/github/mappings`, `POST /api/v1/github/mappings/{id}/test`, `GET /api/v1/github/deliveries`; mutations require existing CSRF protection. Deactivation uses `DELETE /api/v1/workspace/integrations/{integration_id}`. Lists accept a bounded 100-record page through `offset`. The public webhook route uses HMAC authentication instead of browser sessions or client-supplied organization IDs. See [generated OpenAPI](generated/openapi.json).

## References and verification

The design follows GitHub's [webhook validation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries), [replay guidance](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks), [secure Actions use](https://docs.github.com/en/actions/reference/security/secure-use), and [reusable workflow semantics](https://docs.github.com/en/actions/concepts/workflows-and-actions/reusing-workflow-configurations). Verification and deployment limitations are recorded in [PHASE14_TEST_REPORT](PHASE14_TEST_REPORT.md). Live GitHub delivery/comment publication requires your configured repository and credentials; the implementation tests use controlled transports and do not post to a real PR.
