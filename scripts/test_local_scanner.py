"""Local relay failure paths and real Unix-socket forwarding; no Docker required."""

import http.client
import importlib.util
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "local_server",
    Path(__file__).resolve().parents[1] / "infra/local-scanner/server.py",
)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


@contextmanager
def running(instance):
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=3)


class Tests(unittest.TestCase):
    def test_url_rejections(self):
        for value in (
            "http://api:8000/",
            "//api:8000/",
            "/%2e%2e/private",
            "/..\\private",
            "/%00",
            "/#fragment",
        ):
            with self.subTest(value=value):
                self.assertFalse(server.allowed_path(value))
        self.assertTrue(server.allowed_path("/assets/app.js?version=1"))

    def test_static_copy_has_no_backend_proxy(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "index.html").write_text("<html>isolated</html>")

            class Static(server.Static):
                def __init__(self, *args, **kwargs):
                    server.SimpleHTTPRequestHandler.__init__(
                        self, *args, directory=directory, **kwargs
                    )

            with running(ThreadingHTTPServer(("127.0.0.1", 0), Static)) as target:
                for method, path, expected in (
                    ("GET", "/", 200),
                    ("GET", "/app/projects", 200),
                    ("HEAD", "/", 200),
                    ("OPTIONS", "/", 204),
                    ("GET", "/api/v1/auth/me", 404),
                    ("GET", "/health/ready", 404),
                    ("GET", "/%2e%2e/private", 400),
                    ("POST", "/", 501),
                ):
                    with self.subTest(method=method, path=path):
                        conn = http.client.HTTPConnection(
                            "127.0.0.1", target.server_port, timeout=3
                        )
                        conn.request(method, path)
                        response = conn.getresponse()
                        self.assertEqual(response.status, expected)
                        response.read()
                        conn.close()

    def test_relay_fixed_destination_and_fail_closed(self):
        seen = []

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                seen.append(dict(self.headers))
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"isolated target")

        with tempfile.TemporaryDirectory() as directory:
            server.SOCKET = str(Path(directory) / "target.sock")
            with (
                running(server.UnixServer(server.SOCKET, Upstream)),
                running(ThreadingHTTPServer(("127.0.0.1", 0), server.Relay)) as relay,
            ):

                def request(method="GET", path="/", headers=None):
                    conn = http.client.HTTPConnection(
                        "127.0.0.1", relay.server_port, timeout=3
                    )
                    conn.request(method, path, headers=headers or {"Host": server.HOST})
                    response = conn.getresponse()
                    result = response.status, response.read()
                    conn.close()
                    return result

                code, body = request(
                    headers={
                        "Host": server.HOST,
                        "Authorization": "secret",
                        "Cookie": "secret",
                    }
                )
                self.assertEqual((code, body), (200, b"isolated target"))
                self.assertNotIn("Authorization", seen[0])
                self.assertNotIn("Cookie", seen[0])
                self.assertEqual(request(headers={"Host": "api:8000"})[0], 400)
                self.assertEqual(request(path="http://api:8000/")[0], 400)
                self.assertEqual(request("POST")[0], 501)
                self.assertEqual(request("CONNECT")[0], 501)
                self.assertEqual(
                    request(headers={"Host": server.HOST, "Content-Length": "1"})[0],
                    400,
                )
                self.assertEqual(len(seen), 1)
                server.SOCKET = str(Path(directory) / "missing.sock")
                self.assertEqual(request()[0], 502)


if __name__ == "__main__":
    unittest.main()
