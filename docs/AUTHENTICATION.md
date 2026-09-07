# Authentication and organization operations — Phase 5

This phase implements identity, organization membership, RBAC and onboarding. It does not create or execute projects, targets, scans, policies, reports or integrations. Existing persisted project resources can be read through permission-filtered summary endpoints. The supplied screenshot was absent; the product shell follows the written compact sidebar, cyan active item, organization header, bottom documentation/support and collapse requirements.

## Local operation

Run `make setup`, `make dev`, and `make migrate`. Open `/auth/sign-up`, create an account and organization, then sign in at `/auth/sign-in`. The public workspace CTA now opens registration. The product entry is `/app/getting-started`; its organization section supports creation, rename, deactivation, invitations, role changes, member deactivation and ownership transfer. The session section revokes every session. No credential is written to localStorage or sessionStorage.

Set `AEGIS_APP_ORIGIN` to the exact browser origin. Cookie writes require that Origin and a CSRF header. Development defaults to `http://localhost:5173`; production requires HTTPS and Secure cookies. Production Compose is a local infrastructure shape, not a TLS terminator: deploy behind HTTPS and configure the public origin before using authentication. Vite and nginx proxy `/api/` to FastAPI. `VITE_API_BASE_URL` remains the health utility setting; browser identity is deliberately same-origin.

SMTP uses `AEGIS_SMTP_HOST`, `AEGIS_SMTP_PORT`, `AEGIS_SMTP_USERNAME`, secret `AEGIS_SMTP_PASSWORD`, `AEGIS_SMTP_SENDER`, and `AEGIS_SMTP_STARTTLS`. An empty host sends nothing. `mail_deliveries` records only purpose, user ID and sent/failed/unconfigured status; no address, body or token is persisted there. Registration remains usable while email verification is pending. Configure a local mail catcher (STARTTLS off only locally) to exercise verification, recovery and invitation links. Real external delivery is not part of automated tests. Delivery is bounded and synchronous; there is no durable mail retry worker in Phase 5. Request a fresh reset or invitation if delivery fails.

Links carry the single-use token in a URL fragment, which is removed from browser history after capture and is never part of the HTTP request URL. The reset and verify pages submit it in the validated POST body. Invite acceptance requires sign-in with the invited address; create that account first if necessary, then reopen the email link. Pending email verification is visible and does not claim that the address was verified. Ownership of the invitation link plus the matching account is required for membership acceptance.

## Credential lifecycle

- Passwords: independently salted scrypt (`N=32768`, `r=8`, `p=3`), constant-time hash comparison; 12–128 characters for new passwords. Unknown accounts execute the same password comparison work and receive the same sign-in failure message.
- Access: random 384-bit opaque bearer credentials, SHA-256 hashes stored server-side, 10-minute default lifetime (maximum 15 minutes). Database lookup checks expiry, revocation and active user on every request. No JWT signing key or additional dependency is needed.
- Refresh: random 384-bit value in HttpOnly, SameSite=Strict, Secure-in-production cookie scoped to `/api/v1/auth`. Store only the hash, family, replacement chain and expiry. Default absolute lifetime 30 days, idle lifetime 7 days. Rotation keeps the original absolute deadline. A used/revoked/expired refresh revokes its entire family, including access credentials. Sign-out revokes the current family; revoke-all and password reset revoke every family.
- Session mutations lock the user row, then reread the refresh/token state. This serializes sign-in, refresh, reset and session revocation. Browser code uses one in-flight refresh per tab and Web Locks across same-origin tabs where supported.
- Reset/verification tokens: 384-bit random values; only hashes, purposes, expiry and use timestamps persist. Default expiry 30 minutes. Password reset invalidates all outstanding reset tokens and all sessions. Verification sets `email_verified_at` and consumes its token.
- Brute-force control: atomic Redis counters, 10 attempts per peer IP and normalized-email hash per five-minute window by default. Registration, login, recovery, token consumption and invitations use the limiter. Untrusted forwarded IP headers are ignored. Redis failure fails closed. A shared reverse proxy therefore shares the peer-IP budget; production ingress needs appropriate upstream throttling and deliberate tuning for expected traffic. Browser E2E uses a larger limit only in its isolated test fixture.
- CSRF: bootstrap `/auth/csrf` sets a host-only HttpOnly SameSite cookie and returns its random value. Every unsafe identity/organization method requires a matching `X-CSRF-Token` and exact configured Origin, including login. Bearer values are never accepted from query strings or request bodies.

## API surface

All paths below start with `/api/v1`. Responses use Pydantic schemas, existing sanitized error envelopes and `Cache-Control: no-store`. Generated OpenAPI is in `docs/generated/openapi.json`.

| Method             | Route                                                  | Behavior                                                                      |
| ------------------ | ------------------------------------------------------ | ----------------------------------------------------------------------------- |
| GET                | `/auth/csrf`                                           | Establish CSRF cookie/header pair                                             |
| POST               | `/auth/register`                                       | Create identity, initial organization and owner; generic duplicate response   |
| POST               | `/auth/sign-in`                                        | Rate-limited sign-in, access credential and refresh cookie                    |
| POST               | `/auth/refresh`                                        | Rotate refresh, reject replay and revoke family                               |
| POST               | `/auth/sign-out`, `/auth/revoke-all`                   | Revoke current family or all families                                         |
| POST               | `/auth/forgot-password`, `/auth/reset-password`        | Request and consume recovery token                                            |
| POST               | `/auth/verify-email`                                   | Consume verification token                                                    |
| GET                | `/auth/me`                                             | Current user and active organization memberships                              |
| GET, POST          | `/organizations`                                       | List own active organizations or create an owned organization                 |
| GET, PATCH, DELETE | `/organizations/{id}`                                  | Read, rename, or deactivate organization                                      |
| GET                | `/organizations/{id}/members`                          | Owner/admin member roster                                                     |
| POST               | `/organizations/{id}/invitations`                      | Invite admin/developer/viewer (only owner may invite admin)                   |
| POST               | `/organizations/accept-invite`                         | Consume invite for matching signed-in email                                   |
| PATCH, DELETE      | `/organizations/{id}/members/{member_id}`              | Change role or deactivate, subject to hierarchy                               |
| POST               | `/organizations/{id}/transfer-ownership`               | Owner transfers to an active member; former owner becomes admin               |
| GET                | `/organizations/{id}/onboarding`                       | Four booleans derived from permitted persisted records                        |
| GET                | `/organizations/{id}/resources/{kind}[/{resource_id}]` | Permission-filtered summaries for projects, targets, scans, findings, reports |

Organization deletion is deactivation so retained evidence and audit references remain intact. Ownership cannot be removed through ordinary role/deactivation endpoints. Admins cannot promote to admin or change/deactivate admins/owners. Existing memberships cannot be resurrected or have roles overwritten by invitation acceptance. Organization row locks serialize membership and ownership decisions. Role/membership status is read from the database rather than encoded in a bearer token. A deactivated member immediately loses organization access, including with an otherwise valid access credential.

The summary list is bounded to the newest 200 records; object lookup applies its ID predicate before that bound. It returns only ID, project ID and a label, never restricted evidence or credential references. Full resource workflows and paginated product lists belong to later explicit phases.

## RBAC

| Action                                        | Owner                     | Admin                     | Developer         | Viewer            |
| --------------------------------------------- | ------------------------- | ------------------------- | ----------------- | ----------------- |
| Organization settings/deactivate/transfer     | Yes                       | No                        | No                | No                |
| Member management                             | Yes                       | Developers/viewers only   | No                | No                |
| Projects, policies, integrations write policy | Yes                       | Yes                       | No                | No                |
| Targets/scans/findings/reports write policy   | Yes                       | Yes                       | Assigned projects | No                |
| Project/resource reads                        | All organization projects | All organization projects | Assigned projects | Assigned projects |

The write policies for future resource services are implemented and tested in `permitted`; those commands are not mounted in this phase. All mounted organization and resource endpoints enforce actual membership and tenant/project scope. Future resource commands must call both the action policy and project scope check; a role check alone is insufficient. Foreign organizations and foreign/unassigned objects return 404; prohibited in-organization actions return 403.

`identity_audits` is the global identity boundary for pre-organization authentication events. It stores only a user ID when known, action code, timestamps and request ID. Tenant membership/role events use tenant-bound `audit_logs`, actor member and resource IDs. Both are update-immutable. Rejected identity/authorization requests are recorded without input bodies, credentials, emails, cookies or tokens. Database failures cannot guarantee an audit write; requests fail rather than claiming success.

## Onboarding

The server counts active permitted projects and targets, completed baseline scans with complete evidence, and active organization GitHub integrations. Failed/partial/cancelled/timed-out scans cannot complete the scan step. There is no completion-write endpoint and no fake client completion state. Configure/Scan/Review cards and accordion steps link to real guides while the corresponding creation/execution features remain deferred. Refresh progress rereads the API; unavailable state is shown as unavailable rather than zero or success.

## Verification commands

Run `make check build`, `make test-integration`, and `make test-e2e`. Run `make test-auth-e2e` for the real backend browser flows: it builds an isolated API, PostgreSQL and Redis Compose project, migrates automatically, runs Chromium, and removes only that project's containers and volumes. Ports 8000, 4173 and 5174 must be available. The default general browser command skips the auth project unless `AEGIS_E2E_AUTH=1`; the dedicated command and CI explicitly enable it.

API tests cover rotation/replay, reset expiry/single use/revocation, generic login failures, Redis throttling, CSRF, each role's mounted endpoints, actual foreign object IDs, project assignments, deactivation, invitation binding and ownership transfer. Existing migration roundtrips and tenant provenance tests remain active. Browser tests use actual API responses for registration, login, logout, protected routing, reload bootstrap, organization switching, onboarding, mobile drawer and desktop collapse. They do not fabricate scan completion or call scanners.
