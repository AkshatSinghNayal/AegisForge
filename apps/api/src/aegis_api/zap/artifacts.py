"""Write-once local object storage: encrypted originals, conservative derivatives."""

import base64
import binascii
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus
from uuid import uuid4

from cryptography.fernet import Fernet

from aegis_api.zap.contracts import ArtifactReceipt, Execution

SENSITIVE = re.compile(
    r"authorization|cookie|token|session|password|passwd|secret|api.?key|credential",
    re.I,
)


def redact(value: Any, secrets: list[str], patterns: list[str]) -> Any:
    """Drop bodies, headers and free-form evidence from ordinary derivatives.

    Full originals are retained encrypted. Unknown response fields are excluded
    rather than guessing which scanner strings contain sensitive application data.
    """
    safe = {
        "schema",
        "scanner_version",
        "alerts",
        "pluginId",
        "alert",
        "risk",
        "confidence",
        "cweid",
        "wascid",
        "method",
        "sourceid",
        "id",
        "count",
    }
    if isinstance(value, dict):
        return {k: redact(v, secrets, patterns) for k, v in value.items() if k in safe}
    if isinstance(value, list):
        return [redact(v, secrets, patterns) for v in value]
    if isinstance(value, str):
        components = set(secrets)
        for secret in secrets:
            scheme, separator, token = secret.partition(" ")
            if separator and scheme.lower() in {"bearer", "basic"}:
                components.add(token)
                if scheme.lower() == "basic":
                    try:
                        decoded = base64.b64decode(token, validate=True).decode()
                        components.add(decoded)
                        components.update(decoded.split(":", 1))
                    except (ValueError, UnicodeError, binascii.Error):
                        pass
        for secret in sorted(components, key=len, reverse=True):
            for variant in {secret, quote(secret, safe=""), quote_plus(secret)}:
                if variant:
                    value = value.replace(variant, "[REDACTED]")
        for pattern in patterns:
            value = re.sub(pattern, "[REDACTED]", value)
        if SENSITIVE.search(value):
            return "[REDACTED]"
        return value[:1024]
    return value


class LocalArtifactStore:
    def __init__(self, root: Path, key: str):
        self.root = root
        self.cipher = Fernet(key)

    def write(self, key: str, content: bytes) -> None:
        path = self.root / key
        # pathlib's parents=True applies mode only to the leaf, leaving tenant
        # parents at the process umask. Create and secure each owned directory.
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        parent = self.root
        for part in Path(key).parts[:-1]:
            parent /= part
            parent.mkdir(exist_ok=True, mode=0o700)
            parent.chmod(0o700)
        # O_EXCL provides object immutability even under duplicate task delivery.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

    def export(
        self,
        execution: Execution,
        raw: dict[str, Any],
        secrets: list[str],
        patterns: list[str],
    ) -> ArtifactReceipt:
        data = json.dumps(raw, ensure_ascii=True, separators=(",", ":")).encode()
        if len(data) > 268435456:
            raise ValueError("Artifact size limit")
        clean = json.dumps(redact(raw, secrets, patterns), sort_keys=True).encode()
        artifact_id = uuid4()
        prefix = f"{execution.organization_id}/{execution.scan_id}/{artifact_id}"
        receipt = ArtifactReceipt(
            id=artifact_id,
            organization_id=execution.organization_id,
            scan_id=execution.scan_id,
            restricted_object_key=f"{prefix}.fernet",
            redacted_object_key=f"{prefix}.json",
            content_hash=hashlib.sha256(data).hexdigest(),
            redacted_hash=hashlib.sha256(clean).hexdigest(),
            scanner_version=raw["scanner_version"],
            size_bytes=len(data),
        )
        self.write(receipt.restricted_object_key, self.cipher.encrypt(data))
        self.write(receipt.redacted_object_key, clean)
        return receipt
