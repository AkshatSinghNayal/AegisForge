"""Run browser identity journeys against the shared aegisforge Compose project."""
import os
import sys
import shlex
import subprocess

compose = shlex.split(os.environ.get("COMPOSE", "docker compose")) + [
    "-p", "aegisforge", "-f", "docker-compose.yml", "-f", "docker-compose.e2e.yml",
    "-f", "docker-compose.phase6-e2e.yml", "-f", "docker-compose.phase7-e2e.yml"
]
try:
    subprocess.run(compose + ["up", "--build", "-d", "--wait", "api", "worker"], check=True)
    subprocess.run(
        ["pnpm", "--filter", "@aegisforge/web", "test-e2e", "--project=auth", *sys.argv[1:]],
        env={**os.environ, "AEGIS_E2E_AUTH": "1"}, check=True,
    )
finally:
    subprocess.run(compose + ["down"], check=True)
