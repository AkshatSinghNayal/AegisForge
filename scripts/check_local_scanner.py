"""Read-only live connectivity/isolation checks after local setup startup."""

import json
import subprocess
import sys


def docker(context, *args):
    result = subprocess.run(
        ["docker", "--context", context, *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def service(context, files, name):
    result = docker(context, "compose", "-p", "aegisforge", *files, "ps", "-q", name)
    if not result:
        raise SystemExit(f"Required service is not running: {name}")
    return json.loads(docker(context, "inspect", result))[0]


def config_check():
    local = json.loads(
        docker(
            "rootless",
            "compose",
            "-p",
            "aegisforge",
            "-f",
            "docker-compose.local-target.yml",
            "config",
            "--format",
            "json",
        )
    )
    app = json.loads(
        docker(
            "default",
            "compose",
            "-p",
            "aegisforge",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.scanner.yml",
            "-f",
            "docker-compose.local-validation.yml",
            "--profile",
            "scanner-runtime",
            "config",
            "--format",
            "json",
        )
    )
    assert local["name"] == app["name"] == "aegisforge"
    assert local["networks"]["target"]["internal"]
    assert app["networks"]["validation"]["internal"]
    services = app["services"]
    assert set(services["validation-relay"]["networks"]) == {"validation"}
    assert set(services["api"]["networks"]) == {
        "frontend",
        "database",
        "api_broker",
        "validation",
    }
    assert set(services["scanner-worker"]["networks"]) == {"worker_broker"}
    for item in (local["services"]["local-target"], services["validation-relay"]):
        assert not item.get("ports")
        assert (
            item["read_only"]
            and item["cpus"]
            and item["mem_limit"]
            and item["pids_limit"]
        )
        assert len(item["volumes"]) == 1 and item["volumes"][0]["target"] == "/bridge"
    assert services["validation-relay"]["volumes"][0]["read_only"]
    assert not any(
        "docker.sock" in mount["source"] for mount in services["api"]["volumes"]
    )
    print("PASS: rendered local Compose isolation and resource boundaries.")


def main():
    config_check()
    if sys.argv[1:] == ["--config-only"]:
        return
    target = service(
        "rootless", ["-f", "docker-compose.local-target.yml"], "local-target"
    )
    api = service(
        "default",
        ["-f", "docker-compose.yml", "-f", "docker-compose.local-validation.yml"],
        "api",
    )
    relay = service(
        "default",
        ["-f", "docker-compose.yml", "-f", "docker-compose.local-validation.yml"],
        "validation-relay",
    )
    assert set(target["NetworkSettings"]["Networks"]) == {"aegis-local-scan-target"}
    assert set(relay["NetworkSettings"]["Networks"]) == {"aegisforge_validation"}
    assert "aegisforge_validation" in api["NetworkSettings"]["Networks"]
    assert not target["HostConfig"]["PortBindings"]
    assert not relay["HostConfig"]["PortBindings"]
    for context, network in (
        ("rootless", "aegis-local-scan-target"),
        ("default", "aegisforge_validation"),
    ):
        assert json.loads(docker(context, "network", "inspect", network))[0]["Internal"]
    for item in (api, relay, target):
        assert not any("docker.sock" in mount["Source"] for mount in item["Mounts"])
    for item in (relay, target):
        assert item["HostConfig"]["ReadonlyRootfs"]
        assert item["HostConfig"]["NanoCpus"] > 0
        assert item["HostConfig"]["Memory"] > 0
        assert item["HostConfig"]["PidsLimit"] > 0
    fetch = """
import hashlib, urllib.request, urllib.error
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
body=opener.open('http://aegis-local-target:8080/', timeout=5).read()
assert b'<html' in body.lower()
print(hashlib.sha256(body).hexdigest())
try:
    opener.open('http://aegis-local-target:8080/api/v1/auth/me', timeout=5)
except urllib.error.HTTPError as error:
    assert error.code == 404
else:
    raise AssertionError('Static target must not proxy API calls')
"""
    direct = docker("rootless", "exec", target["Id"], "python", "-c", fetch)
    via_relay = docker("default", "exec", api["Id"], "python", "-c", fetch)
    assert direct == via_relay
    app_addresses = [
        entry["IPAddress"] for entry in api["NetworkSettings"]["Networks"].values()
    ]
    deny = """
import socket, sys, json
for name in ('api', 'postgres', 'redis', 'web'):
    try:
        socket.getaddrinfo(name, 8000)
    except socket.gaierror:
        pass
    else:
        raise AssertionError('Application hostname reachable')
for host, port in json.loads(sys.argv[1]):
    try:
        connection=socket.create_connection((host, port), timeout=1)
    except OSError:
        pass
    else:
        connection.close()
        raise AssertionError('Forbidden outbound TCP connection succeeded')
"""
    endpoints = [
        (address, port) for address in app_addresses for port in (8000, 5432, 6379)
    ]
    endpoints += [("1.1.1.1", 443), ("169.254.169.254", 80)]
    docker(
        "rootless", "exec", target["Id"], "python", "-c", deny, json.dumps(endpoints)
    )
    print(
        "PASS: same static target via API validation and scanner network; no API proxy, host ports, application DNS or tested forbidden TCP egress."
    )


if __name__ == "__main__":
    main()
