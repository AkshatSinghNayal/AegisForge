"""Validate rendered Compose boundaries without printing environment credentials."""
import json
import os
import shlex
import subprocess

compose = shlex.split(os.environ.get("COMPOSE", "docker compose")) + ["-p", "aegisforge"]


def config(*args: str) -> dict:
    result = subprocess.run(
        [*compose, *args, "config", "--format", "json"],
        check=True, capture_output=True, text=True,
    )
    rendered = json.loads(result.stdout)
    assert rendered["name"] == "aegisforge", "Compose project must be aegisforge"
    return rendered


for mode, args in (
    ("dev", ()),
    ("prod", ("-f", "docker-compose.yml", "-f", "docker-compose.prod.yml")),
):
    rendered = config(*args)
    services = rendered["services"]
    assert "zap" not in services, "Scanner must be opt-in"
    for service in ("postgres", "redis", "worker", "prometheus", "grafana"):
        assert not services[service].get("ports"), f"{service} publishes host ports"
    assert not set(services["worker"]["networks"]) & set(services["api"]["networks"])
    assert "AEGIS_DATABASE_URL" not in services["worker"]["environment"]
    for network in ("database", "api_broker", "worker_broker", "observability"):
        assert rendered["networks"][network]["internal"]
    for name, destination in (("prometheus", "/prometheus"), ("grafana", "/var/lib/grafana")):
        service = services[name]
        assert set(service["networks"]) == {"observability"}
        assert any(
            mount["type"] == "volume" and mount["source"] == f"{name}_data"
            and mount["target"] == destination for mount in service["volumes"]
        )
        assert any(mount["type"] == "bind" and mount.get("read_only") for mount in service["volumes"])
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

# Render opt-in execution boundaries with nonsecret validation-only values.
scanner_env = {
    **os.environ,
    "AEGIS_ZAP_DISPATCH_KEY": "validation-only",
    "AEGIS_ZAP_ARTIFACT_KEY": "validation-only",
    "AEGIS_SCANNER_SOCKET": "/tmp/validation-only-scanner.sock",
    "AEGIS_SCANNER_SOCKET_GID": "10001",
}
scanner_render = json.loads(subprocess.run(
    [*compose, "-f", "docker-compose.yml", "-f", "docker-compose.scanner.yml",
     "--profile", "scanner-runtime", "config", "--format", "json"],
    env=scanner_env, check=True, capture_output=True, text=True,
).stdout)
worker = scanner_render["services"]["scanner-worker"]
assert set(worker["networks"]) == {"worker_broker"}
assert "AEGIS_DATABASE_URL" not in worker["environment"]
assert not worker.get("ports") and worker["mem_limit"] and worker["cpus"]
assert scanner_render["services"]["scanner-reaper"]["network_mode"] == "none"
for name in ("api", "web", "worker"):
    assert not any("docker.sock" in str(mount) for mount in scanner_render["services"][name].get("volumes", []))
demo = config("-f", "docker-compose.scanner-demo.yml", "--profile", "scanner-demo")
assert demo["networks"]["fixture"]["internal"]
assert not demo["services"]["training"].get("ports")
assert set(demo["services"]["training"]["networks"]) == {"fixture"}
print("Phase 8: worker, reaper, socket and vulnerable fixture isolation assertions passed")
