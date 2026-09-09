"""Add missing scanner encryption keys without displaying or replacing secrets."""
from pathlib import Path

from cryptography.fernet import Fernet

path = Path(".env")
if not path.exists():
    raise SystemExit("Run make setup first.")
lines = path.read_text().splitlines()
for name in ("AEGIS_ZAP_DISPATCH_KEY", "AEGIS_ZAP_ARTIFACT_KEY"):
    existing = next((i for i, line in enumerate(lines) if line.startswith(name + "=")), None)
    if existing is None:
        lines.append(name + "=" + Fernet.generate_key().decode())
    elif not lines[existing].split("=", 1)[1].strip():
        lines[existing] = name + "=" + Fernet.generate_key().decode()
path.write_text("\n".join(lines) + "\n")
path.chmod(0o600)
print("Scanner keys configured in .env; existing keys preserved.")
