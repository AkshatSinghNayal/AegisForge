"""Closed execution envelope and untrusted scanner response contracts."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from aegis_api.configuration_schemas import PolicyInput
from aegis_api.normalization import Observation
from aegis_api.target_validation import canonical_url

ZAP_IMAGE = (
    "ghcr.io/zaproxy/zaproxy:2.17.0@sha256:"
    "781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef"
)


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Credential(Closed):
    id: UUID
    header_name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9-]{0,119}$")
    ciphertext: SecretStr


class Execution(Closed):
    organization_id: UUID
    scan_id: UUID
    job_id: UUID
    fence: int = Field(ge=0)
    target_version: int = Field(ge=1)
    policy_version: int = Field(ge=1)
    target_url: str
    kind: Literal["web_url", "rest_base_url", "openapi_url", "openapi_upload"]
    policy: PolicyInput
    includes: list[str] = Field(min_length=1, max_length=100)
    excludes: list[str] = Field(default_factory=list, max_length=100)
    methods: list[str] = Field(min_length=1, max_length=7)
    deadline: datetime
    authorized_until: datetime
    authorization_digest: str = Field(min_length=1, max_length=64)
    active_confirmation_digest: str | None = Field(default=None, max_length=64)
    credentials: list[Credential] = Field(default_factory=list, max_length=20)
    spec: dict[str, Any] | None = None

    @field_validator("target_url")
    @classmethod
    def canonical(cls, value: str) -> str:
        return canonical_url(value)

    @field_validator("includes", "excludes")
    @classmethod
    def paths(cls, values: list[str]) -> list[str]:
        if any(not v.startswith("/") or len(v) > 256 for v in values):
            raise ValueError("Invalid scope")
        return values

    @field_validator("methods")
    @classmethod
    def verbs(cls, values: list[str]) -> list[str]:
        if not set(values) <= {
            "GET",
            "HEAD",
            "OPTIONS",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        }:
            raise ValueError("Invalid method")
        return values


class ArtifactReceipt(Closed):
    normalizer: Literal["zap-normalizer-v1"] | None = None
    observations: list[Observation] = Field(default_factory=list, max_length=20000)
    id: UUID
    organization_id: UUID
    scan_id: UUID
    restricted_object_key: str = Field(max_length=500)
    redacted_object_key: str = Field(max_length=500)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    redacted_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    scanner_version: str = Field(pattern=r"^2\.17\.0$")
    size_bytes: int = Field(ge=0, le=268435456)
    encryption_key_reference: Literal["local:scanner-artifacts-v1"] = (
        "local:scanner-artifacts-v1"
    )
    redaction_version: Literal["zap-redaction-v1", "zap-redaction-v2"] = (
        "zap-redaction-v2"
    )

    @model_validator(mode="after")
    def normalized_indices(self) -> "ArtifactReceipt":
        if self.normalizer is None and self.observations:
            raise ValueError("Observations require a normalizer version")
        if [o.index for o in self.observations] != list(range(len(self.observations))):
            raise ValueError("Observations must preserve contiguous raw alert indices")
        return self


class Alert(BaseModel):
    # Preserve every supplied field in the encrypted raw document. Validate fields
    # used by our collector; ZAP add-ons may supply additional metadata.
    model_config = ConfigDict(extra="allow", hide_input_in_errors=True)
    pluginId: str = Field(pattern=r"^\d+$")
    alert: str
    risk: str
    confidence: str
    url: str
    method: str
    messageId: str = Field(pattern=r"^\d+$")


class Alerts(Closed):
    alerts: list[Alert] = Field(max_length=500)


class Message(BaseModel):
    model_config = ConfigDict(extra="allow", hide_input_in_errors=True)
    requestHeader: str
    requestBody: str
    responseHeader: str
    responseBody: str


class Messages(Closed):
    message: Message


class OpenApiImport(Closed):
    # ZAP returns a warning list named after this operation, not Result: OK.
    # Any warning means coverage could be incomplete, so fail closed.
    importFile: list[dict[str, str]] = Field(max_length=0)


class ScannerRule(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    id: str = Field(pattern=r"^\d+$")


class ScannerRules(Closed):
    scanners: list[ScannerRule] = Field(max_length=1000)
