# Phase 14 on a local self-hosted runner

Use `.github/workflows/aegisforge-scan-local-test.yml`. It supports manual dispatch and reuse from a manually dispatched caller on `main`, and both jobs use `runs-on: self-hosted`. It does not trigger on pushes or PR events. The production workflow and CLI are unchanged. The separate `scripts/aegisforge_ci_local_test.py` entry point allows only the exact HTTP origins below; other origins retain HTTPS validation and redirects/proxies remain disabled.

## Local prerequisites

- Run the registered runner directly on the same Linux host as Compose, with Python 3.12+ and Git on its service PATH. A runner inside an isolated container has a different loopback interface and is not covered by this example. If you have multiple self-hosted runners, ensure this is the only eligible runner or add a dedicated host label to both jobs.
- **API: `http://127.0.0.1:8000`**. `docker-compose.yml` publishes `127.0.0.1:8000:8000`; use this IPv4 literal, not `localhost` (which can resolve to IPv6). App links use **`http://127.0.0.1:5173`**, matching `127.0.0.1:5173:5173`. Open links on this machine; remote GitHub viewers cannot reach your loopback. Sign in using the app's configured origin if necessary.
- Your existing API must have Phase 14 migrations/code, a running coordinator, and a real authorized scanner configured per [SCANNER](SCANNER.md). Base Compose defaults to scanner provider `none`; an idle runner alone does not enable scans. Mock/demo output cannot pass. This workflow neither starts Compose nor deploys code or a target.
- Have a registered, currently authorized target, its project UUID, its exact environment, a passive/baseline scanner policy UUID belonging to that project, and an active deterministic project gate. The scanner target is resolved from the registered UUID; it is not the loopback API address. Do not submit an arbitrary target URL.
- Check readiness from the runner's host/account without any key: `curl --fail --silent --show-error http://127.0.0.1:8000/health/ready`. Readiness does not prove scanner configuration or target reachability.

At implementation verification time, the unauthenticated readiness probe returned connection refused on `127.0.0.1:8000`. The Compose binding is confirmed from source; start/restore your existing stack before dispatch. No stack services were started by this change.

## Exact repository secrets

In `AkshatSinghNayal/AegisForge` → **Settings → Secrets and variables → Actions → Repository secrets**, create exactly:

| Name                 | Value                                                                                                                                                                                                                                                                         |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `AEGISFORGE_API_KEY` | The full one-time plaintext value of a real Phase 13 organization API key issued by your local stack, with `scans:create` and `scans:read` scopes, valid expiry, and an active creator authorized for the selected project. Paste the key itself, without a `Bearer ` prefix. |

Create it in the local application's **API Keys** screen while in the target's organization. Stored key hashes cannot be used or retrieved as plaintext; issue a new key if you no longer have the one-time value. Do not send the value in chat or paste it into workflow inputs/logs. No GitHub PAT, SSH key, webhook secret, database password or encryption key is needed. GitHub supplies `GITHUB_TOKEN` automatically to the optional comment job; that job alone has `pull-requests: write`. The scan job receives only contents-read and the organization key. Organization repository policies must permit the requested comment permission.

No repository variables or GitHub deployment environment are required by this local variant. The `environment` input is AegisForge target metadata, not a deployment instruction.

## Trigger a real run

1. Review and push the new workflow and both scripts to `main` (the default branch). GitHub must have the workflow on its default branch before manual dispatch appears. Protect workflow/script changes; self-hosted jobs execute reviewed repository code on your machine.
2. Open **Actions → AegisForge local test → Run workflow**, select **main**.
3. Supply `project`, `target`, and `policy` UUIDs. Set `environment` to the target's exact registered value (default `development`); set `timeout` in seconds (default 900). Leave `pull-request` at 0 and `pr-comment` false for the first run.
4. Click **Run workflow**. The checkout uses the dispatched `github.sha` on main; that SHA and branch are scan attribution. It does not deploy that revision to your target. Dispatching another branch skips the scan job.

Equivalent CLI on your already authenticated machine (replace the UUID placeholders):

```sh
gh workflow run aegisforge-scan-local-test.yml \
  --repo AkshatSinghNayal/AegisForge --ref main \
  -f project=PROJECT_UUID -f target=TARGET_UUID -f policy=SCANNER_POLICY_UUID \
  -f environment=development -f timeout=900 \
  -f pull-request=0 -f pr-comment=false
```

To test comments, dispatch again with an existing same-repository PR number and `pr-comment=true`. This posts a real comment only when explicitly selected. The comment is about the registered target and dispatched main revision, not deployment of the PR's head. Run once more for the same project/target/PR and confirm the existing `github-actions[bot]` comment URL/ID stays the same; its hidden `aegisforge` marker is updated in place. The shared concurrency group serializes this writer with the cloud workflow for the same PR/target. No PR source is checked out.

## Evidence to inspect

- **Check local runner runtime** succeeds; **Run authorized passive scan** prints only the fixed diagnostic on failure and `AegisForge CLI exit code: N`. No key, authorization header, response body or raw finding should appear. No verbose transport tracing is enabled.
- Exit **0** = pass, **2** = warn, **1** = fail, **3** = incomplete/error/timeout/cancellation. A policy may classify incomplete as fail. Nonzero makes the scan job red; this is expected gate behavior, not proof of broken integration. There is no `continue-on-error` masking the result.
- The job summary has one latest verdict, counts and application link. Download artifact `aegisforge-RUN_ID-RUN_ATTEMPT-TARGET_UUID` and inspect `aegisforge-summary.json`: its scan ID must match the local application, and terminal state, completeness, outcome and counts must agree with the retained evaluation. Artifact retention is seven days, including failed gates when upload is possible. Null counts are not a clean scan.
- For the optional comment, check the separate **comment** job and actual PR: only gate/counts/link plus a hidden marker, no evidence payload or credentials. The organization key is not passed to this job. A rerun updates the bot-owned marker rather than adding another comment.
- A transport/configuration failure remains incomplete. Check local readiness, key validity/scopes, target authorization, scanner readiness and policy versions locally. Cancellation attempts remote scan cancellation; abrupt runner loss cannot guarantee cancellation or artifact upload.

This verifies outbound Actions → local API → real scanner → deterministic gate → artifact/optional comment. It does **not** test inbound GitHub webhooks: GitHub cannot deliver to your loopback URL. No public exposure or deployment is added here.

GitHub reference: [manually running workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).
