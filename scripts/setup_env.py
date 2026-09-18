"""Create ignored local credentials once; never print secrets or overwrite .env."""
import base64
import os
import secrets
from pathlib import Path

path = Path(".env")
if path.exists():
    print("Existing .env preserved.")
else:
    content = Path(".env.example").read_text()
    for key in ("POSTGRES_PASSWORD", "REDIS_PASSWORD"):
        content = content.replace(f"{key}=\n", f"{key}={secrets.token_hex(24)}\n")
    for key in ("AEGIS_LOCAL_SECRET_KEY", "AEGIS_NOTIFICATION_ENCRYPTION_KEY"):
        value = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
        content = content.replace(f"{key}=\n", f"{key}={value}\n")
    content = content.replace(
        "AEGIS_REPORT_SIGNING_KEY=\n",
        "AEGIS_REPORT_SIGNING_KEY=" + secrets.token_urlsafe(32) + "\n",
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(content)
    print("Created .env with local-only credentials (mode 0600).")
