# Deterministic project gate policies — Phase 11

Gate policies are separate from scanner execution policies. Open **Workspace → Gates** (`/app/gates`), select a project, publish an immutable version and activate it. Owner/admin roles may publish, activate, deactivate, approve exceptions and retain re-evaluations. Assigned developers and viewers may read project versions and preview historical scans. Existing organization, project-membership and CSRF dependencies apply to every endpoint. No executable expressions are accepted.

## Rule semantics

The `gate-v1` schema and `deterministic-v1` evaluator accept only validated normalized scanner fields and explicit reviewer state. AI analyses, model verdicts, enrichment availability and model confidence are excluded from evaluator inputs and input digests.

Each rule has a unique stable ID, a structured match, a nonnegative maximum count and a `warn` or `fail` outcome. Conditions within a rule use AND; members of a list use OR. An empty list has no restriction. Match fields are severity, minimum scanner confidence, finding status, CWE, exact OWASP tag, exact/prefix canonical route, exact environment and new/existing relative to baseline. There is no regex, script, template evaluation or natural-language verdict. OWASP tags use the scanner's normalized strings, for example `OWASP_2021_A03`.

Confidence order is false_positive < low < medium < high < confirmed. Default rules include open states (new, recurring, reopened, changed, accepted_risk) and minimum low confidence. Explicit status filters may include resolved or false_positive; no reviewer disposition automatically waives accepted risk. Multiple observations count as one finding; every matching occurrence ID is retained. All rules run. Any fail overrides warn; any warn overrides pass. A maximum of zero prohibits the matched category. For “fail on new high/critical with minimum medium confidence,” select high and critical, medium confidence, new baseline status, maximum zero and fail.

Before evaluating thresholds, incomplete evidence produces the version's stored `incomplete` or `fail` outcome. Failed, cancelled, timed-out, unfinished, partial, unnormalized and demo scans never pass. The database also rejects passing evaluations that contradict the stored scan's state/completeness or refer to demo scans. A missing gate policy produces an unavailable/incomplete effective gate; demo scans retain their explicit failing gate label. Publishing an empty rule list deliberately means no finding thresholds; completeness guards still apply.

## Baselines and reviewer state

Evaluation uses immutable occurrences from the requested scan, never the canonical finding's latest scanner severity. The normalization record identifies the last complete comparable baseline. A finding is new if absent from that baseline; with no baseline all observations are new. Failed/partial scans cannot become comparison baselines. Gate-only version changes do not alter scanner coverage or start a separate comparison family. Scanner execution/configuration changes continue to do so.

Legacy scans without a captured environment cannot satisfy environment-constrained policies: they evaluate incomplete/fail-closed instead of guessing from the target's current environment.

Historical evaluation uses the scan's recorded lifecycle status with current accepted-risk/false-positive reviewer dispositions. Withdrawal of a disposition prevents an older normalization map from retaining the waiver. These captured states become immutable inputs for that evaluation. Re-evaluation captures a new time and current reviewer state, so expiry or review changes may intentionally change the result. Replaying the same captured inputs and policy always gives the same result.

## Accepted-risk exceptions

An exception has an exact finding-ID scope within the policy's project, an active organization-member owner, a nonempty reason and a future timezone-aware expiry. Publishing records server-owned creation time and the authenticated admin's approval identity; clients cannot submit approval claims. Scope cannot refer to another project or tenant. An exception applies only when the policy enables exceptions, its finding is currently accepted risk, and `created_at <= evaluated_at < expires_at`. At the expiry instant it no longer applies. Renew or remove an exception by publishing a new policy version; earlier approvals and evaluation inputs remain intact. Approval is given by the publishing admin; a separate second approver is not required.

## Storage and execution

Migration `0009` adds immutable `gate_policies` and append-only `gate_activations`, with tenant-safe composite foreign keys and per-project version/activation sequencing. Existing `PolicyEvaluation` gains a gate-policy reference and immutable input/result JSON snapshots; the original scanner-policy reference is preserved. Re-evaluation inserts a new record even when its digest and result match a prior record. UPDATE and DELETE triggers preserve history. The downgrade refuses to discard retained gate policies/evaluations; empty migration round trips restore the previous guard. PostgreSQL retains the unused additive `incomplete` enum value on a downgrade.

At scan creation the active gate ID, version, full policy and target environment are frozen in the scan configuration. Active-scan confirmations bind to that gate version as well as the existing target/scanner configuration. Changing activation between confirmation and submission requires a new confirmation. New scans use the new activation; running scans keep their stored gate. Successful ZAP collection evaluates after normalized observations are committed to the transaction. Failed/cancelled/timed-out transitions append the bound policy's incomplete/fail result in that same transaction.

Each evaluation stores its engine version, policy version, exact evaluation time, completeness, baseline ID, safe structured finding fields, finding/occurrence IDs, input digest, matched rule IDs, readable reasons, exclusions and outcome. Request/response bodies, credentials and advisory text are not part of these snapshots. Database enrichment metadata is retained for legacy compatibility but is not a decision input. Scan detail displays the most recent retained gate result and links to evaluation history.

## API

Project routes are under `/api/v1/organizations/{organization_id}/projects/{project_id}/gate-policies`:

- GET: active version ID and published versions.
- POST: publish `{policy, exceptions}` with server-owned approval metadata.
- POST `/activation`: `{policy_id}` activates a project version; null deactivates it.

Scan routes use authenticated `organization_id` query selection under `/api/v1/scans/{scan_id}`:

- POST `/policy-preview`: `{policy_id}` evaluates without inserting a record.
- POST `/policy-evaluations`: `{policy_id}` appends a retained evaluation.
- GET `/policy-evaluations?offset=0`: retained snapshots, matches and contributing IDs, newest first, 50 per page.

Preview requires a published policy from the scan's project. Publishing does not activate it. The UI's copy-to-builder control allows revising a published policy using safe controls before publishing another version. Preview is read-only in persistence terms but uses POST and CSRF protection because it receives structured input.

## Phase boundary

No new environment variables, providers or dependencies are introduced. Apply migrations through `0009`. No reports, CI integration, notifications, deployment or subsequent phase work is included. Browser tests use explicitly synthetic HTTP boundary fixtures; API/database integration tests independently exercise the real authorization, persistence and evaluation paths. See [Phase 11 verification](PHASE11_TEST_REPORT.md).
