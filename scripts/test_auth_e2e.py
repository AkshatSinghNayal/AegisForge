"""Run browser identity journeys against disposable PostgreSQL/Redis/API services."""
import base64
import secrets
import os
import sys
import shlex
import subprocess
from uuid import uuid4

project = "aegis-auth-e2e-" + uuid4().hex[:10]
compose = shlex.split(os.environ.get("COMPOSE", "docker compose")) + [
    "-p", project, "-f", "docker-compose.yml", "-f", "docker-compose.e2e.yml",
    "-f", "docker-compose.phase6-e2e.yml", "-f", "docker-compose.phase7-e2e.yml"
]
os.environ["AEGIS_LOCAL_SECRET_KEY"] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
try:
    subprocess.run(compose + ["up", "--build", "-d", "--wait", "api", "worker"], check=True)
    subprocess.run(
        ["pnpm", "--filter", "@aegisforge/web", "test-e2e", "--project=auth", *sys.argv[1:]],
        env={**os.environ, "AEGIS_E2E_AUTH": "1"}, check=True,
    )
finally:
    subprocess.run(compose + ["down", "--volumes", "--remove-orphans"], check=True)
