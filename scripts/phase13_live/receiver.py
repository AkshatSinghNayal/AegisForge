"""Real TLS fixture: verify raw-byte HMAC before acknowledging delivery."""

import hashlib
import hmac
import json
import ssl
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

root = Path("/fixture")
secret = (root / "hmac.txt").read_text()


class Receiver(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        stamp = self.headers.get("X-Aegis-Timestamp", "")
        expected = (
            "sha256="
            + hmac.new(
                secret.encode(), stamp.encode() + b"." + body, hashlib.sha256
            ).hexdigest()
        )
        valid = (
            stamp.isdigit()
            and abs(time.time() - int(stamp)) < 60
            and hmac.compare_digest(expected, self.headers.get("X-Aegis-Signature", ""))
        )
        if valid:
            data = json.loads(body)
            assert data["event"] == "scan.failed"
            assert secret.encode() not in body and b"SECRET_BODY_CANARY" not in body
            (root / "received.json").write_text(
                json.dumps(
                    {
                        "verified": True,
                        "event": data["event"],
                        "organization_id": data["organization_id"],
                        "delivery_id": self.headers["X-Aegis-Delivery"],
                        "bytes": len(body),
                    }
                )
            )
        self.send_response(204 if valid else 401)
        self.end_headers()


server = ThreadingHTTPServer(("0.0.0.0", 443), Receiver)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(root / "server.pem", root / "server.key")
server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever()
