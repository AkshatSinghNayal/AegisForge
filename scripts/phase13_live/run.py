"""Run three real Phase 13 journeys on an isolated HTTPS fixture network.

Builds the test API image and requires Node/Playwright.
No production validation function or transport is patched. Only synthetic data
is used, in a disposable database. The fixture's public-classified IPv4 subnet
is Docker-internal: it never routes packets to that public network.
"""

import json
import os
import secrets
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[2]
os.chdir(root)
fixture = Path(tempfile.mkdtemp(prefix="aegis-phase13-live-"))
fixture.chmod(0o755)
base = [
    "docker",
    "compose",
    "-p",
    "aegisforge",
    "-f",
    "docker-compose.yml",
    "-f",
    "docker-compose.e2e.yml",
]
rendered = json.loads(
    subprocess.check_output([*base, "config", "--format", "json"], text=True)
)
db_name = "phase13_live_" + secrets.token_hex(8)
db_url = (
    make_url(rendered["services"]["api"]["environment"]["AEGIS_DATABASE_URL"])
    .set(database=db_name)
    .render_as_string(hide_password=False)
)
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name(
    [x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Phase 13 fixture CA")]
)
start = datetime.now(UTC) - timedelta(minutes=1)
ca = (
    x509.CertificateBuilder()
    .subject_name(name)
    .issuer_name(name)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(start)
    .not_valid_after(start + timedelta(days=1))
    .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
    .sign(key, hashes.SHA256())
)
server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
server = (
    x509.CertificateBuilder()
    .subject_name(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "webhook.receiver.test")])
    )
    .issuer_name(name)
    .public_key(server_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(start)
    .not_valid_after(start + timedelta(days=1))
    .add_extension(
        x509.SubjectAlternativeName([x509.DNSName("webhook.receiver.test")]),
        critical=False,
    )
    .sign(key, hashes.SHA256())
)
for filename, value in {
    "ca.pem": ca.public_bytes(serialization.Encoding.PEM),
    "server.pem": server.public_bytes(serialization.Encoding.PEM),
    "server.key": server_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ),
    "hmac.txt": secrets.token_urlsafe(48).encode(),
}.items():
    (fixture / filename).write_bytes(value)
    (fixture / filename).chmod(0o644)

config = {
    "services": {
        "api": {
            "image": "aegisforge-api-test",
            "pull_policy": "never",
            "environment": {
                "AEGIS_DATABASE_URL": db_url,
                "AEGIS_SCAN_COORDINATOR_ENABLED": "false",
                "AEGIS_REPORTING_ENABLED": "true",
                "AEGIS_AI_PROVIDER": "none",
                "AEGIS_NOTIFICATION_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "SSL_CERT_FILE": "/fixture/ca.pem",
            },
            "volumes": [
                f"{fixture}:/fixture:ro",
                f"{root}/scripts/phase13_live:/live:ro",
            ],
            "extra_hosts": [
                "webhook.receiver.test:11.203.13.2",
                "blocked.webhook.test:127.0.0.1",
            ],
            "networks": {"notification_fixture": {}},
        },
        "webhook-receiver": {
            "image": "aegisforge-api-test",
            "pull_policy": "never",
            "user": f"{os.getuid()}:{os.getgid()}",
            "command": ["python", "/live/receiver.py"],
            "volumes": [f"{fixture}:/fixture", f"{root}/scripts/phase13_live:/live:ro"],
            "networks": {"notification_fixture": {"ipv4_address": "11.203.13.2"}},
            "security_opt": ["no-new-privileges:true"],
            "cap_drop": ["ALL"],
            "cap_add": ["NET_BIND_SERVICE"],
        },
    },
    "networks": {
        "notification_fixture": {
            "internal": True,
            "ipam": {"config": [{"subnet": "11.203.13.0/24"}]},
        }
    },
}
(fixture / "compose.json").write_text(json.dumps(config))
(fixture / "compose.json").chmod(0o600)
compose = [*base, "-f", str(fixture / "compose.json")]
frontend = None
created = False
try:
    subprocess.run([*compose, "build", "api"], check=True)
    subprocess.run([*compose, "up", "-d", "--wait", "postgres", "redis"], check=True)
    subprocess.run(
        [*compose, "exec", "-T", "postgres", "createdb", "-U", "aegis", db_name],
        check=True,
    )
    created = True
    subprocess.run(
        [*compose, "up", "-d", "--no-build", "--wait", "api", "webhook-receiver"],
        check=True,
    )
    with open("/tmp/phase13-live-vite.log", "w") as output:
        frontend = subprocess.Popen(
            [
                "pnpm",
                "--filter",
                "@aegisforge/web",
                "dev",
                "--port",
                "5174",
                "--strictPort",
            ],
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    for _ in range(60):
        try:
            with urllib.request.urlopen("http://127.0.0.1:5174", timeout=2):
                break
        except OSError:
            time.sleep(1)
    else:
        raise RuntimeError("Frontend unavailable")
    subprocess.run(
        ["node", "scripts/phase13_live/journey.mjs"],
        env={**os.environ, "AEGIS_LIVE_FIXTURE": str(fixture)},
        check=True,
        timeout=180,
    )
    print(
        "PASS: all three live Phase 13 journeys completed; synthetic event, real TLS/HMAC delivery, real API/Redis/PostgreSQL and browser.",
        flush=True,
    )
finally:
    if frontend:
        os.killpg(frontend.pid, signal.SIGTERM)
        frontend.wait(timeout=15)
    subprocess.run([*compose, "stop", "api", "webhook-receiver"], check=True)
    if created:
        subprocess.run(
            [
                *compose,
                "exec",
                "-T",
                "postgres",
                "dropdb",
                "--force",
                "-U",
                "aegis",
                db_name,
            ],
            check=True,
        )
    subprocess.run([*compose, "down"], check=True)
    shutil.rmtree(fixture)
