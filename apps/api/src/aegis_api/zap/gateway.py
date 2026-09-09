"""Single-target HTTP(S) egress guard, in a separate disposable container.

Scanner has only an internal network. This gateway has no application/broker/DB
network membership. All upstream connections use the execution-time pinned IP.
CONNECT is terminated locally so paths, methods and budgets also apply to HTTPS.
No remote response is interpreted as a configuration or instruction.
"""

import fnmatch
import http.client
import ipaddress
import json
import os
import socket
import ssl
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pydantic import Field

from aegis_api.zap.contracts import Closed

STATS_PATH = Path("/tmp/stats.json")


class Scope(Closed):
    target_url: str
    address: str
    includes: list[str]
    excludes: list[str]
    methods: list[str]
    max_requests: int = Field(ge=1, le=100000)
    rate: int = Field(ge=1, le=100)
    seconds: int = Field(ge=1, le=3600)
    require_lease: bool = False

    def permits(self, url: str, method: str) -> bool:
        target, candidate = urlsplit(self.target_url), urlsplit(url)
        if (
            candidate.scheme != target.scheme
            or candidate.hostname != target.hostname
            or (candidate.port or (443 if candidate.scheme == "https" else 80))
            != (target.port or (443 if target.scheme == "https" else 80))
            or candidate.username is not None
            or candidate.password is not None
            or method not in self.methods
        ):
            return False
        path = candidate.path or "/"
        # Reject ambiguous traversal/encoding before matching the declared paths.
        for _ in range(4):
            decoded = unquote(path)
            if decoded == path:
                break
            path = decoded
        if (
            "%" in path
            or "\\" in path
            or "//" in path
            or ";" in path
            or any(p in {".", ".."} for p in path.split("/"))
        ):
            return False
        if any(ord(c) < 32 for c in path):
            return False
        return any(fnmatch.fnmatchcase(path, p) for p in self.includes) and not any(
            fnmatch.fnmatchcase(path, p) for p in self.excludes
        )


class Budget:
    def __init__(self, scope: Scope):
        self.scope = scope
        self.until = time.monotonic() + scope.seconds
        self.lock = threading.Lock()
        self.count = 0
        self.denied = 0
        self.exhausted = False
        self.failed = False
        self.next_request = 0.0

    def lease_current(self) -> bool:
        if not self.scope.require_lease:
            return True
        try:
            return time.time() - Path("/tmp/lease").stat().st_mtime < 10
        except OSError:
            return False

    def admit(self, url: str, method: str) -> bool:
        with self.lock:
            if not self.lease_current():
                self.exhausted = True
                return False
            if not self.scope.permits(url, method):
                self.denied += 1
                return False
            if self.count >= self.scope.max_requests or time.monotonic() >= self.until:
                self.exhausted = True
                return False
            delay = max(0, self.next_request - time.monotonic())
            self.next_request = time.monotonic() + delay + 1 / self.scope.rate
            self.count += 1
        if delay > max(0, self.until - time.monotonic()):
            self.exhausted = True
            return False
        time.sleep(delay)
        return self.current()

    def current(self) -> bool:
        # A reserved rate slot is not permission to send after revocation.
        with self.lock:
            if not self.lease_current() or time.monotonic() >= self.until:
                self.exhausted = True
                return False
            return True

    def persist(self) -> None:
        # Readers must never see a torn JSON snapshot from concurrent requests.
        with self.lock:
            temporary = STATS_PATH.with_suffix(".pending")
            temporary.write_text(json.dumps(self.stats()))
            temporary.replace(STATS_PATH)

    def stats(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "denied": self.denied,
            "exhausted": self.exhausted,
            "failed": self.failed,
        }


def certificate(host: str, root: Path = Path("/tmp")) -> ssl.SSLContext:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    try:
        san: x509.GeneralName = x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        san = x509.DNSName(host)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(hours=2))
        .add_extension(x509.SubjectAlternativeName([san]), critical=False)
        .sign(key, hashes.SHA256())
    )
    (root / "tls-key.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    (root / "tls-cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    (root / "tls-key.pem").chmod(0o600)
    context.load_cert_chain(root / "tls-cert.pem", root / "tls-key.pem")
    return context


def handler(
    scope: Scope, budget: Budget, tls: ssl.SSLContext
) -> type[BaseHTTPRequestHandler]:
    target = urlsplit(scope.target_url)
    port = target.port or (443 if target.scheme == "https" else 80)
    authority = target.netloc

    class Handler(BaseHTTPRequestHandler):
        timeout = 10
        protocol_version = "HTTP/1.0"

        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_CONNECT(self) -> None:
            if target.scheme != "https" or self.path != f"{target.hostname}:{port}":
                budget.denied += 1
                self.send_error(403)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.flush()
            self.connection = tls.wrap_socket(self.connection, server_side=True)
            self.rfile = self.connection.makefile("rb")
            self.wfile = self.connection.makefile("wb")
            self.close_connection = True
            self.handle_one_request()

        def forward(self) -> None:
            url = self.path
            if url.startswith("/"):
                url = f"{target.scheme}://{authority}{url}"
            if not budget.admit(url, self.command):
                budget.persist()
                self.send_error(403)
                return
            if self.headers.get("Transfer-Encoding") or self.headers.get("Upgrade"):
                budget.failed = True
                budget.persist()
                self.send_error(400)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 1048576:
                    raise ValueError
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError
                parsed = urlsplit(url)
                path = (parsed.path or "/") + (
                    f"?{parsed.query}" if parsed.query else ""
                )
                if not budget.current():
                    self.send_error(403)
                    return
                # No DNS lookup at connect time: connect exclusively to the pin.
                sock = socket.create_connection((scope.address, port), timeout=10)
                if target.scheme == "https":
                    sock = ssl.create_default_context().wrap_socket(
                        sock,
                        server_hostname=target.hostname,
                    )
                connection = http.client.HTTPConnection(scope.address, port, timeout=10)
                connection.sock = sock
                strip = {
                    "host",
                    "connection",
                    "proxy-connection",
                    "proxy-authorization",
                    "transfer-encoding",
                    "content-length",
                    "upgrade",
                }
                headers = {
                    k: v for k, v in self.headers.items() if k.lower() not in strip
                }
                headers.update({"Host": authority, "Connection": "close"})
                try:
                    connection.request(self.command, path, body, headers)
                    response = connection.getresponse()
                    data = response.read(4194305)
                    if len(data) > 4194304:
                        raise ValueError
                    self.send_response(response.status)
                    for k, v in response.getheaders():
                        if k.lower() not in strip:
                            self.send_header(k, v)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    if self.command != "HEAD":
                        self.wfile.write(data)
                finally:
                    connection.close()
            except Exception:
                budget.failed = True
                self.send_error(502)
            finally:
                budget.persist()

        do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = (
            forward
        )

    return Handler


def main() -> None:
    scope = Scope.model_validate_json(sys.stdin.readline())
    budget = Budget(scope)
    tls = certificate(str(urlsplit(scope.target_url).hostname))
    # Hard watchdog survives caller loss. No container restart policy is allowed.
    timer = threading.Timer(scope.seconds, lambda: os._exit(124))
    timer.daemon = True
    timer.start()

    def lease_watchdog() -> None:
        while True:
            if not budget.lease_current():
                os._exit(125)
            time.sleep(1)

    threading.Thread(target=lease_watchdog, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", 8888), handler(scope, budget, tls))
    server.daemon_threads = True
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
