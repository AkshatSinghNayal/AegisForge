"""Create ignored local credentials once; never print secrets or overwrite .env."""
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
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(content)
    print("Created .env with local-only credentials (mode 0600).")
