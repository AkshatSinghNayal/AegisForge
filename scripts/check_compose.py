"""Validate rendered Compose boundaries without printing environment credentials."""
import json
import os
import shlex
import subprocess

compose = shlex.split(os.environ.get("COMPOSE", "docker compose"))


def config(*args: str) -> dict:
    result = subprocess.run(
        [*compose, *args, "config", "--format", "json"],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


for mode, args in (
    ("dev", ()),
    ("prod", ("-f", "docker-compose.yml", "-f", "docker-compose.prod.yml")),
):
    rendered = config(*args)
    services = rendered["services"]
    assert "zap" not in services, "Scanner must be opt-in"
    for service in ("postgres", "redis", "worker"):
        assert not services[service].get("ports"), f"{service} publishes host ports"
    assert not set(services["worker"]["networks"]) & set(services["api"]["networks"])
    assert "AEGIS_DATABASE_URL" not in services["worker"]["environment"]
    for network in ("database", "api_broker", "worker_broker"):
        assert rendered["networks"][network]["internal"]
    if mode == "prod":
        assert not services["api"].get("ports")
        assert not services["web"].get("volumes")
        assert services["api"]["environment"]["AEGIS_PROFILE"] == "prod"
    for service in services.values():
        assert service.get("healthcheck")
    print(f"{mode}: Compose configuration and isolation assertions passed")
scanner = config("--profile", "scanner")["services"]["zap"]
assert scanner["network_mode"] == "none"
assert "@sha256:" in scanner["image"]
assert not scanner.get("ports")
print("scanner: opt-in, digest-pinned, no network or published ports")
