"""Add a missing local encryption key without replacing existing credentials."""
import base64
import os
import secrets
from pathlib import Path

path = Path('.env')
if not path.is_file():
    raise SystemExit('Run make setup first.')
content = path.read_text()
lines = content.splitlines()
entries = [line for line in lines if line.startswith('AEGIS_LOCAL_SECRET_KEY=')]
if any(line.partition('=')[2].strip() for line in entries):
    print('Existing local secret key preserved.')
else:
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    lines = [line for line in lines if not line.startswith('AEGIS_LOCAL_SECRET_KEY=')]
    lines.append('AEGIS_LOCAL_SECRET_KEY=' + key)
    # Never print the value; preserve all other environment entries.
    os.chmod(path, 0o600)
    path.write_text('\n'.join(lines) + '\n')
    print('Local encryption key configured. Keep .env backed up securely.')
