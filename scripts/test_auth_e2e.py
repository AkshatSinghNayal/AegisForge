"""Run browser identity journeys against disposable PostgreSQL/Redis/API services."""
import os
import shlex
import subprocess
from uuid import uuid4

project = "aegis-auth-e2e-" + uuid4().hex[:10]
compose = shlex.split(os.environ.get("COMPOSE", "docker compose")) + [
    "-p", project, "-f", "docker-compose.yml", "-f", "docker-compose.e2e.yml"
]
try:
    subprocess.run(compose + ["up", "--build", "-d", "--wait", "api"], check=True)
    subprocess.run(
        ["pnpm", "--filter", "@aegisforge/web", "test-e2e", "--project=auth"],
        env={**os.environ, "AEGIS_E2E_AUTH": "1"}, check=True,
    )
finally:
    subprocess.run(compose + ["down", "--volumes", "--remove-orphans"], check=True)
