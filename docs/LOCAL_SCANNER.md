# Local isolated frontend scanning

This opt-in development setup preserves the cloud Actions workflow, application authentication and target-validation rules. It is a Phase 14 local verification aid, not production deployment infrastructure.

## Design

- The existing application stays on Docker context `default`.
- A static build of this repository's frontend runs on context `rootless`, internal network `aegis-local-scan-target`, as `http://aegis-local-target:8080`. It has no host port, Docker socket, application credentials, backend proxy or application-network membership. `/api/` and `/health/` return 404. Authenticated API testing is outside this static target's coverage.
- The same target process serves a Unix socket in the ignored `.local-scanner/bridge` directory. Directory mode is 0700 and socket mode is 0600, owned by the desktop user (UID 0 inside the rootless container maps to that user). Do not replace this with a world-writable shared directory.
- A small relay on the default daemon's internal validation-only network accepts only the fixed host `aegis-local-target:8080` and GET/HEAD/OPTIONS. It forwards only to that Unix socket, never an arbitrary URL, and never forwards caller credentials. It has no Docker socket, host ports or other network membership. Its socket mount is read-only. The API joins only this validation network, not the scanner network.
- DNS for the canonical hostname resolves to the relay for the API, and to the static frontend for the scanner. Both paths terminate at the same static server/files; validation is not faked. Existing private-address authorization, scope checks and normal consent registration remain mandatory. The ZAP egress gateway retains its exact-origin/method/path enforcement.
- The trusted scanner worker retains broker-only access and the dedicated rootless Docker socket as in Phase 8; ZAP itself receives neither. The socket is never `/var/run/docker.sock` from the application daemon. Rootless Docker is an additional boundary, not a VM; trusted administrators still control both daemons.

## Host prerequisite: controller delegation

The rootless daemon must enforce CPU, memory and PID limits. Merely seeing `name=rootless` is insufficient. On the current host, only `memory pids` were delegated and startup failed with `NanoCPUs can not be set`. Do not remove the CPU limit.

As desktop user `akshat` (UID 1000), run the following in a terminal where you can enter your sudo password. The instance-specific drop-in changes delegation only for this user:

```sh
sudo mkdir -p /etc/systemd/system/user@1000.service.d
printf '[Service]\nDelegate=cpu cpuset io memory pids\n' | sudo tee /etc/systemd/system/user@1000.service.d/aegis-scanner-delegate.conf >/dev/null
sudo systemctl daemon-reload
systemctl --user restart docker

docker --context rootless info --format 'CPU quota={{.CPUCfsQuota}} Memory={{.MemoryLimit}} PIDs={{.PidsLimit}}'
```

All three must be `true`. If CPU remains false, save your work and reboot so the user manager starts with the new delegation, then check again. Do not restart `user@1000.service` during your desktop session: it can terminate your applications. Do not disable the system Docker daemon. See [Docker's controller delegation guidance](https://docs.docker.com/engine/security/rootless/tips/#limiting-resources).

## Prepare and start

Run from the repository root. This intentionally changes local scanner settings in the ignored `.env`, preserving keys. The host user must own the rootless context and socket. No credentials are printed, and no scans are submitted by these commands.

```sh
pnpm --filter @aegisforge/web build
apps/api/.venv/bin/python scripts/setup_local_scanner.py

docker --context rootless compose -p aegisforge \
  -f docker-compose.local-target.yml up -d --wait

docker --context default compose -p aegisforge \
  -f docker-compose.yml -f docker-compose.scanner.yml \
  -f docker-compose.local-validation.yml --profile scanner-runtime \
  up -d --wait api validation-relay scanner-worker scanner-reaper

python3.12 scripts/check_local_scanner.py
```

The setup script builds the static frontend server from a minimal context (compiled assets and server only), builds the existing scanner-worker image, transfers both images into the dedicated daemon, and pulls the pinned ZAP image there. It sets the exact allowlist `["http://aegis-local-target:8080"]`, egress network, socket identity and relay UID/GID. Internet access is needed for image/dependency preparation; scanning the static target itself needs none. Rebuild after frontend changes. The base `.env` scanner provider is not changed; the opt-in scanner overlay enables it on the API.

Do not start the runtime if existing queued scans are unexpected: enabling the coordinator/provider may dispatch previously submitted work. The live check verifies topology, response identity through both paths, absence of backend proxying, and denial of application DNS, selected infrastructure TCP ports, public TCP and metadata TCP from the target network. It does not replace an actual completed ZAP scan or certify every possible host firewall configuration.

## Register and run normally

1. Keep your existing project and activated deterministic gate.
2. Use an administrator-created baseline policy with private internal tests enabled, a truthful internal authorization declaration, and GET/HEAD scope. For a short local run, use maximum depth 2, 100 requests, 2 requests/second, and 300 seconds; target limits must not exceed its policy.
3. In Targets, register **`http://aegis-local-target:8080`**, environment **`development`**, authentication **None**, inclusion `/*`, methods `GET,HEAD`. Declare your ownership of this isolated copy, consent, validate, and register. Do not insert authorization rows manually or keep using `http://web:5173/` for this isolated setup.
4. Copy the new target UUID. The existing project/scanner-policy UUIDs are reusable if their configuration matches. Use a key from that organization with `scans:create` and `scans:read`.
5. Dispatch the [local Actions workflow](GITHUB_LOCAL_TEST.md) from main with the new target. Inspect the real scan, retained evaluation, artifact and optional comment. Static-serving observations describe this isolated copy, not the production nginx/API configuration. No successful scan is claimed merely by preparing this setup.

## Stop the local components

```sh
docker --context default compose -p aegisforge \
  -f docker-compose.yml -f docker-compose.scanner.yml \
  -f docker-compose.local-validation.yml --profile scanner-runtime \
  stop scanner-worker scanner-reaper validation-relay

docker --context rootless compose -p aegisforge \
  -f docker-compose.local-target.yml down

docker --context default compose -p aegisforge -f docker-compose.yml \
  up -d --no-deps api
```

This restores the API's base configuration and removes its validation-network attachment; it does not delete database volumes, scanner images or encryption keys. Keep `.local-scanner` out of Git and Docker build contexts.
