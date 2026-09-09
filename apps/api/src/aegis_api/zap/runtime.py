"""Docker CLI boundary. Requires a dedicated scanner daemon, never the API socket."""

import json
import subprocess
import threading
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from aegis_api.settings import WorkerSettings
from aegis_api.target_validation import permitted_ip
from aegis_api.zap.contracts import ZAP_IMAGE
from aegis_api.zap.gateway import Scope


class RuntimeFailure(Exception):
    """Code-only exception: Docker/ZAP output must never reach task logs."""


class NetworkInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    IPAddress: str = Field(pattern=r"^[0-9.]+$")


class DockerRuntime:
    def __init__(self, config: WorkerSettings, job_id: UUID, check: Callable[[], None]):
        self.config, self.check = config, check
        self.prefix = f"aegis-zap-{job_id}"
        self.zap = f"{self.prefix}-zap"
        self.gateway = f"{self.prefix}-gateway"
        self.resources: list[tuple[str, str]] = []
        self.cleaned = False
        self.gateway_ip = ""
        self.stop = threading.Event()
        self.heartbeat: threading.Thread | None = None

    def command(
        self, args: list[str], data: str | None = None, timeout: int = 15
    ) -> str:
        try:
            result = subprocess.run(
                ["docker", *args],
                input=data,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if result.returncode or len(result.stdout) > 33554432:
                raise RuntimeFailure("scanner_runtime_failed")
            return result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeFailure("scanner_runtime_failed") from None

    def reap(self) -> None:
        """Recover expired resources after hard worker loss; never touch other jobs."""
        stamp = int(time.time())
        for kind, listing in (
            ("container", ["ps", "-aq"]),
            ("network", ["network", "ls", "-q"]),
        ):
            identifiers = self.command(
                [*listing, "--filter", "label=aegis.scanner=true"]
            ).split()
            for identifier in identifiers:
                template = (
                    '{{index .Config.Labels "aegis.expires"}}'
                    if kind == "container"
                    else '{{index .Labels "aegis.expires"}}'
                )
                value = self.command(
                    [kind, "inspect", "--format", template, identifier]
                )
                if value.isdigit() and int(value) <= stamp:
                    self.command(
                        [
                            kind,
                            "rm",
                            *(["-f"] if kind == "container" else []),
                            identifier,
                        ]
                    )

    def resolve(self, host: str, port: int, allow_private: bool) -> list[str]:
        """Trusted DNS-only helper on the scanner daemon, never the broker network."""
        self.check()
        name = f"{self.prefix}-resolver"
        code = """
import json, socket, sys
request = json.load(sys.stdin)
rows = socket.getaddrinfo(request['host'], request['port'], type=socket.SOCK_STREAM)
print(json.dumps(sorted({str(row[4][0]) for row in rows})))
"""
        try:
            result = self.command(
                [
                    "run",
                    "--rm",
                    "-i",
                    "--pull",
                    "never",
                    "--name",
                    name,
                    "--label",
                    "aegis.scanner=true",
                    "--label",
                    f"aegis.expires={int(time.time()) + 30}",
                    "--network",
                    self.config.zap_egress_network,
                    "--read-only",
                    "--log-driver",
                    "none",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--memory",
                    "128m",
                    "--memory-swap",
                    "128m",
                    "--cpus",
                    "0.25",
                    "--pids-limit",
                    "32",
                    self.config.zap_gateway_image,
                    "timeout",
                    "-s",
                    "KILL",
                    "10",
                    "python",
                    "-c",
                    code,
                ],
                json.dumps(
                    {"host": host, "port": port, "allow_private": allow_private}
                ),
            )
            addresses = json.loads(result)
            if (
                not isinstance(addresses, list)
                or not addresses
                or len(addresses) > 100
                or not all(
                    isinstance(ip, str) and permitted_ip(ip, allow_private)
                    for ip in addresses
                )
            ):
                raise RuntimeFailure("target_dns_rejected")
            return addresses
        finally:
            try:
                self.command(["rm", "-f", name], timeout=5)
            except RuntimeFailure:
                pass  # --rm/hard timeout/reaper cover completed or lost helpers.

    def start(self, scope: Scope, api_key: str) -> None:
        self.check()
        self.command(["image", "inspect", ZAP_IMAGE], timeout=5)
        self.command(["image", "inspect", self.config.zap_gateway_image], timeout=5)
        expiry = str(int(time.time()) + scope.seconds + 30)
        labels = ["--label", "aegis.scanner=true", "--label", f"aegis.expires={expiry}"]
        self.resources.append(("network", self.prefix))
        self.command(["network", "create", "--internal", *labels, self.prefix])
        common = [
            "--pull",
            "never",
            "--log-driver",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=256m",
            *labels,
        ]
        self.resources.append(("container", self.gateway))
        # Start sleeping, connect the internal interface, then send the scope on
        # stdin. No credentials, scope or API key occur in Docker arguments/logs.
        self.command(
            [
                "run",
                "-d",
                "--name",
                self.gateway,
                *common,
                "--pids-limit",
                "256",
                "--cpus",
                "0.5",
                "--memory",
                "256m",
                "--memory-swap",
                "256m",
                "--network",
                self.config.zap_egress_network,
                self.config.zap_gateway_image,
                "sleep",
                str(scope.seconds + 10),
            ]
        )
        self.command(["network", "connect", self.prefix, self.gateway])
        ip = self.command(
            [
                "inspect",
                "--format",
                '{{(index .NetworkSettings.Networks "' + self.prefix + '").IPAddress}}',
                self.gateway,
            ]
        )
        NetworkInfo(IPAddress=ip)
        self.gateway_ip = ip
        self.command(
            [
                "exec",
                "-i",
                self.gateway,
                "python",
                "-c",
                "import pathlib,sys; "
                "pathlib.Path('/tmp/scope.json').write_text(sys.stdin.read()); "
                "pathlib.Path('/tmp/lease').touch()",
            ],
            scope.model_dump_json(),
        )
        self.command(
            [
                "exec",
                "-d",
                self.gateway,
                "sh",
                "-c",
                "exec python -m aegis_api.zap.gateway < /tmp/scope.json",
            ]
        )

        def keep_lease() -> None:
            while not self.stop.wait(2):
                try:
                    self.check()
                    self.command(
                        ["exec", self.gateway, "touch", "/tmp/lease"], timeout=3
                    )
                except Exception:
                    # Gateway independently cuts egress within ten seconds.
                    return

        self.heartbeat = threading.Thread(target=keep_lease, daemon=True)
        self.heartbeat.start()
        for attempt in range(20):
            self.check()
            try:
                self.command(
                    [
                        "exec",
                        self.gateway,
                        "python",
                        "-c",
                        "import socket; "
                        "socket.create_connection(('127.0.0.1',8888),1).close()",
                    ],
                    timeout=3,
                )
                break
            except RuntimeFailure:
                if attempt == 19:
                    raise
                time.sleep(0.5)
        self.resources.append(("container", self.zap))
        self.command(
            [
                "run",
                "-d",
                "--name",
                self.zap,
                *common,
                "--pids-limit",
                "512",
                "--cpus",
                str(self.config.zap_cpus),
                "--memory",
                self.config.zap_memory,
                "--memory-swap",
                self.config.zap_memory,
                "--shm-size",
                "256m",
                "--env",
                "XDG_CACHE_HOME=/tmp/browser-cache",
                "--tmpfs",
                "/home/zap/.ZAP:rw,uid=1000,gid=1000,size=512m",
                "--tmpfs",
                "/home/zap/.ZAP/webdriver:rw,exec,nosuid,nodev,uid=1000,gid=1000,size=128m",
                "--tmpfs",
                "/home/zap/.mozilla:rw,nosuid,nodev,uid=1000,gid=1000,size=64m",
                "--network",
                self.prefix,
                ZAP_IMAGE,
                "sleep",
                str(scope.seconds + 10),
            ]
        )
        self.command(
            [
                "exec",
                "-i",
                self.zap,
                "python3",
                "-c",
                "import pathlib,sys; p=pathlib.Path('/tmp/api-key'); "
                "p.write_text(sys.stdin.read()); p.chmod(0o600)",
            ],
            api_key,
        )
        # API binds only loopback; key required even from an AJAX browser. External
        # proxy is numeric and has no bypass list. Direct egress has no route.
        self.command(
            [
                "exec",
                "-d",
                self.zap,
                "sh",
                "-c",
                "exec timeout -s KILL "
                + str(scope.seconds)
                + " zap.sh -daemon -host 127.0.0.1 -port 8080 -silent "
                '-config api.key="$(cat /tmp/api-key)" '
                "-config connection.proxyChain.enabled=true "
                "-config connection.proxyChain.hostName=" + ip + " "
                "-config connection.proxyChain.port=8888 "
                "-config connection.proxyChain.skipName= "
                "-config autoupdate.checkOnStart=false "
                "-config autoupdate.downloadNewRelease=false "
                "-config autoupdate.installAddonUpdates=false "
                "-config autoupdate.installScannerRules=false > /dev/null 2>&1",
            ]
        )

    def call(
        self, component: str, kind: str, operation: str, **params: str
    ) -> dict[str, Any]:
        self.check()
        request = json.dumps(
            {"path": f"/JSON/{component}/{kind}/{operation}/", "params": params}
        )
        # POST form parameters via stdin: secrets never become command arguments.
        code = """
import json, sys, urllib.request, urllib.parse, urllib.error, pathlib
r = json.load(sys.stdin)
r['params']['apikey'] = pathlib.Path('/tmp/api-key').read_text()
d = urllib.parse.urlencode(r['params']).encode()
q = urllib.request.Request('http://127.0.0.1:8080' + r['path'], data=d)
try:
    f = urllib.request.urlopen(q, timeout=10)
except urllib.error.HTTPError as error:
    f = error
b = f.read(33554433)
assert len(b) <= 33554432
sys.stdout.buffer.write(b)
"""
        try:
            data = json.loads(
                self.command(["exec", "-i", self.zap, "python3", "-c", code], request)
            )
            if not isinstance(data, dict):
                raise RuntimeFailure("invalid_scanner_response")
            if "code" in data:
                safe_codes = {
                    "url_not_found",
                    "illegal_parameter",
                    "bad_action",
                    "no_implementor",
                    "internal_error",
                    "does_not_exist",
                    "action_not_allowed",
                    "not_in_scope",
                    "bad_format",
                    "missing_parameter",
                    "mode_violation",
                    "url_not_in_context",
                }
                code_name = data["code"] if data["code"] in safe_codes else "unknown"
                raise RuntimeFailure("zap_api_" + code_name)
            return data
        except (ValueError, TypeError):
            raise RuntimeFailure("invalid_scanner_response") from None

    def configure_proxy(self) -> None:
        for operation, params in (
            ("setHttpProxy", {"host": self.gateway_ip, "port": "8888"}),
            ("setHttpProxyEnabled", {"enabled": "true"}),
            ("setSocksProxyEnabled", {"enabled": "false"}),
        ):
            if self.call("network", "action", operation, **params) != {"Result": "OK"}:
                raise RuntimeFailure("scanner_proxy_failed")

    def file(self, path: str, content: str) -> None:
        if path != "/tmp/openapi.json":
            raise RuntimeFailure("invalid_scanner_path")
        self.command(
            [
                "exec",
                "-i",
                self.zap,
                "python3",
                "-c",
                "import pathlib,sys; "
                "pathlib.Path('/tmp/openapi.json').write_text(sys.stdin.read())",
            ],
            content,
        )

    def stats(self) -> dict[str, Any]:
        data = json.loads(
            self.command(["exec", self.gateway, "cat", "/tmp/stats.json"])
        )
        if not isinstance(data, dict):
            raise RuntimeFailure("invalid_gateway_response")
        return data

    def close(self) -> None:
        self.stop.set()
        if self.heartbeat:
            self.heartbeat.join(timeout=4)
        failed = False
        for kind, name in reversed(self.resources):
            try:
                # Idempotent cleanup handles partially completed Docker starts.
                self.command(
                    [kind, "rm", *(["-f"] if kind == "container" else []), name]
                )
            except RuntimeFailure:
                failed = True
        if failed:
            raise RuntimeFailure("scanner_cleanup_failed")
        self.cleaned = True
