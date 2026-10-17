"""Local static scan target and fixed Unix-socket validation relay. No app secrets."""

import http.client
import os
import socket
import socketserver
import threading
from http.server import (
    BaseHTTPRequestHandler,
    SimpleHTTPRequestHandler,
    ThreadingHTTPServer,
)
from pathlib import Path
from urllib.parse import unquote, urlsplit

HOST = "aegis-local-target:8080"
SOCKET = "/bridge/target.sock"
LIMIT = 4 * 1024 * 1024


def allowed_path(path):
    parsed = urlsplit(path)
    decoded = unquote(parsed.path)
    return (
        path.startswith("/")
        and not path.startswith("//")
        and not parsed.scheme
        and not parsed.netloc
        and not parsed.fragment
        and "\\" not in decoded
        and not any(part == ".." for part in decoded.split("/"))
        and not any(ord(c) < 32 for c in decoded)
    )


class Quiet:
    def log_message(self, *args):
        pass


class Static(Quiet, SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory="/site", **kwargs)

    def send_head(self):
        if not allowed_path(self.path):
            self.send_error(400)
            return None
        route = unquote(urlsplit(self.path).path)
        if route == "/api" or route.startswith(("/api/", "/health/")):
            self.send_error(404)
            return None
        path = Path(self.translate_path(self.path))
        if not path.is_file():
            self.path = "/index.html"
        return super().send_head()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET, HEAD, OPTIONS")
        self.end_headers()

    def address_string(self):
        return "local"


class UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(SOCKET)


class Relay(Quiet, BaseHTTPRequestHandler):
    def forward(self):
        if self.headers.get("Host") != HOST or not allowed_path(self.path):
            self.send_error(400)
            return
        if (
            self.headers.get("Transfer-Encoding")
            or self.headers.get("Content-Length", "0") != "0"
        ):
            self.send_error(400)
            return
        conn = UnixHTTP("local", timeout=5)
        try:
            # No caller headers, cookies or credentials cross this boundary.
            conn.request(self.command, self.path, headers={"Host": HOST})
            response = conn.getresponse()
            body = response.read(LIMIT + 1)
            if len(body) > LIMIT:
                raise ValueError("Oversized response")
            self.send_response(response.status)
            for header in ("Content-Type", "Last-Modified", "Allow"):
                value = response.getheader(header)
                if value:
                    self.send_header(header, value)
            length = (
                response.getheader("Content-Length", "0")
                if self.command == "HEAD"
                else str(len(body))
            )
            self.send_header("Content-Length", length)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (OSError, ValueError, http.client.HTTPException):
            self.send_error(502)
        finally:
            conn.close()

    do_GET = forward
    do_HEAD = forward
    do_OPTIONS = forward


class UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main():
    role = os.environ["AEGIS_LOCAL_ROLE"]
    if role == "target":
        if Path(SOCKET).exists():
            Path(SOCKET).unlink()
        server = UnixServer(SOCKET, Static)
        os.chmod(SOCKET, 0o600)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        handler = Static
    elif role == "relay":
        handler = Relay
    else:
        raise SystemExit("Unknown local role")
    ThreadingHTTPServer(("0.0.0.0", 8080), handler).serve_forever()


if __name__ == "__main__":
    main()
