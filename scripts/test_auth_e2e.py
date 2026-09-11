"""Run browser identity journeys against the shared aegisforge Compose project."""

import base64
import json
import os
import shlex
import subprocess
import sys

compose = shlex.split(os.environ.get("COMPOSE", "docker compose")) + [
    "-p",
    "aegisforge",
    "-f",
    "docker-compose.yml",
    "-f",
    "docker-compose.e2e.yml",
    "-f",
    "docker-compose.phase6-e2e.yml",
    "-f",
    "docker-compose.phase7-e2e.yml",
]
# Validate in memory before starting/stopping the shared stack; never print config.
rendered = json.loads(
    subprocess.run(
        compose + ["config", "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
)
key = rendered["services"]["api"]["environment"].get("AEGIS_LOCAL_SECRET_KEY", "")
try:
    valid_key = len(base64.b64decode(key, altchars=b"-_", validate=True)) == 32
except (ValueError, TypeError):
    valid_key = False
if not valid_key:
    raise SystemExit(
        "Configure a persistent 32-byte base64 AEGIS_LOCAL_SECRET_KEY in .env before E2E; the shared stack was not changed."
    )
try:
    subprocess.run(
        compose + ["up", "--build", "-d", "--wait", "api", "worker"], check=True
    )
    subprocess.run(
        [
            "pnpm",
            "--filter",
            "@aegisforge/web",
            "test-e2e",
            "--project=auth",
            *sys.argv[1:],
        ],
        env={**os.environ, "AEGIS_E2E_AUTH": "1"},
        check=True,
    )
finally:
    subprocess.run(compose + ["down"], check=True)
