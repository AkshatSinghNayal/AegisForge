"""Intentionally vulnerable LOCAL TRAINING fixture. Never publish a host port."""
import os
from pathlib import Path

from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit


class Training(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        Path("/tmp/requests").write_text("contacted")
        query = parse_qs(urlsplit(self.path).query).get("q", ["training"])[0]
        # Deliberately unescaped reflection for the isolated XSS scan test.
        data = (
            '<h1>AegisForge vulnerable training fixture</h1>'
            '<p>DEMO ONLY — intentionally insecure</p>'
            '<a href="/?q=hello">Search</a>'
            f'<a href="{os.environ.get("OUT_OF_SCOPE_ORIGIN", "http://198.51.100.7")}/forbidden">Blocked external link</a>'
            '<a href="/excluded">Excluded local path</a>' + query
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Set-Cookie", "session=synthetic-fixture-secret")
        self.end_headers()
        self.wfile.write(data)


HTTPServer(("0.0.0.0", 8000), Training).serve_forever()
