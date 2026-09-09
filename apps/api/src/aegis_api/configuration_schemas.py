"""Explicit request and response contracts; secrets are input-only."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from aegis_api.auth import Payload
from aegis_api.db.enums import RecordState, ScanMode, Severity
from aegis_api.target_validation import canonical_url

Name = Annotated[str, Field(min_length=1, max_length=120)]
PathPattern = Annotated[
    str, Field(min_length=1, max_length=256, pattern=r"^/[^\s?#]*$")
]


class ProjectInput(Payload):
    name: Name
    slug: str = Field(
        min_length=1, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )
    description: str = Field(default="", max_length=4000)
    repository_url: str | None = Field(default=None, max_length=500)
    default_branch: Name = "main"
    environment: Annotated[str, Field(min_length=1, max_length=64)] = "development"
    owner_id: UUID
    member_ids: list[UUID] = Field(default_factory=list, max_length=200)

    @field_validator("repository_url")
    @classmethod
    def repository(cls, value: str | None) -> str | None:
        return canonical_url(value) if value else None


class ProjectView(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str
    repository_url: str | None
    default_branch: str
    environment: str
    owner_id: UUID
    member_ids: list[UUID]
    status: RecordState
    version: int


class PolicyInput(Payload):
    name: Name
    mode: ScanMode = ScanMode.BASELINE
    max_duration_seconds: int = Field(default=300, ge=30, le=3600)
    max_requests: int = Field(default=1000, ge=1, le=100000)
    max_depth: int = Field(default=5, ge=0, le=20)
    spider: Literal["none", "traditional", "ajax"] = "traditional"
    active_rule_allowlist: list[Annotated[str, Field(pattern=r"^\d{1,10}$")]] = Field(
        default_factory=list, max_length=200
    )
    rate_limit: int = Field(default=2, ge=1, le=100)
    excluded_paths: list[PathPattern] = Field(default_factory=list, max_length=100)
    fail_severity: Severity = Severity.HIGH
    warn_severity: Severity = Severity.MEDIUM
    allow_private: bool = False
    internal_test_declaration: str = Field(default="", max_length=1000)
    active_warning_acknowledged: bool = False

    @model_validator(mode="after")
    def safety(self) -> "PolicyInput":
        if self.allow_private and len(self.internal_test_declaration.strip()) < 20:
            raise ValueError("Describe the authorized internal test environment.")
        if self.mode == ScanMode.ACTIVE and (
            not self.active_warning_acknowledged or not self.active_rule_allowlist
        ):
            raise ValueError(
                "Active policies require a rule allowlist and warning acknowledgement."
            )
        if self.mode != ScanMode.ACTIVE and self.active_rule_allowlist:
            raise ValueError("Passive policies cannot enable active rules.")
        order = list(Severity)
        if order.index(self.warn_severity) > order.index(self.fail_severity):
            raise ValueError("Warning threshold must not exceed failure threshold.")
        return self


class PolicyView(PolicyInput):
    id: UUID
    version: int


class CredentialInput(Payload):
    auth_type: Literal["api_key", "bearer", "basic"]
    header_name: str = Field(
        default="Authorization", max_length=120, pattern=r"^[A-Za-z][A-Za-z0-9-]*$"
    )
    value: SecretStr = Field(min_length=1, max_length=4096)
    username: SecretStr | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def safe_header(self) -> "CredentialInput":
        if self.header_name.lower() in {
            "host",
            "cookie",
            "connection",
            "content-length",
            "transfer-encoding",
            "proxy-authorization",
            "forwarded",
            "x-forwarded-for",
        }:
            raise ValueError("This header cannot be configured as an API key.")
        if any(x in self.value.get_secret_value() for x in ("\r", "\n", "\x00")):
            raise ValueError("Credentials cannot contain control characters.")
        if self.auth_type == "basic" and (
            not self.username
            or ":" in self.username.get_secret_value()
            or any(c in self.username.get_secret_value() for c in "\r\n\x00")
        ):
            raise ValueError("Basic authentication requires a valid username.")
        return self


class CredentialView(BaseModel):
    id: UUID
    auth_type: str
    header_name: str
    masked: Literal["••••••••"] = "••••••••"
    version: int
    revoked: bool


class TargetInput(Payload):
    project_id: UUID
    display_name: Name
    kind: Literal["web_url", "openapi_url", "openapi_upload", "rest_base_url"]
    base_url: str = Field(max_length=2048)
    openapi_url: str | None = Field(default=None, max_length=2048)
    environment: Annotated[str, Field(min_length=1, max_length=64)] = "development"
    authorization_declaration: str = Field(min_length=20, max_length=2000)
    authorization_owner_id: UUID
    consent: Literal[True]
    inclusion_patterns: list[PathPattern] = Field(
        default_factory=lambda: ["/*"], min_length=1, max_length=100
    )
    exclusion_patterns: list[PathPattern] = Field(default_factory=list, max_length=100)
    allowed_methods: list[
        Literal["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"]
    ] = Field(default=["GET", "HEAD"], min_length=1, max_length=7)
    rate_limit: int = Field(default=2, ge=1, le=100)
    timeout_seconds: int = Field(default=300, ge=30, le=3600)
    policy_id: UUID
    upload_filename: str | None = Field(default=None, max_length=120)
    upload_content: SecretStr | None = Field(default=None, max_length=1048576)
    credential: CredentialInput | None = None

    @field_validator("base_url", "openapi_url")
    @classmethod
    def url(cls, value: str | None) -> str | None:
        return canonical_url(value) if value is not None else None

    @field_validator("authorization_declaration")
    @classmethod
    def declaration(cls, value: str) -> str:
        if len(value.strip()) < 20:
            raise ValueError("Provide a meaningful authorization declaration.")
        return value.strip()

    @model_validator(mode="after")
    def spec(self) -> "TargetInput":
        if self.kind == "openapi_url" and not self.openapi_url:
            raise ValueError("An OpenAPI document URL is required.")
        if self.kind == "openapi_upload" and (
            not self.upload_filename or not self.upload_content
        ):
            raise ValueError("Upload an OpenAPI document.")
        if self.kind != "openapi_upload" and (
            self.upload_content or self.upload_filename
        ):
            raise ValueError("Only upload targets accept documents.")
        return self


class TargetView(BaseModel):
    id: UUID
    project_id: UUID
    display_name: str
    kind: str
    base_url: str
    environment: str
    policy_id: UUID | None
    consent_at: datetime | None
    authorization_owner_id: UUID | None
    authorization_declaration: str
    inclusion_patterns: list[str]
    exclusion_patterns: list[str]
    allowed_methods: list[str]
    rate_limit: int
    timeout_seconds: int
    status: RecordState
    version: int
    verified_at: datetime | None
    has_openapi: bool
    credentials: list[CredentialView]


class ValidationView(BaseModel):
    valid: bool
    final_url: str
    http_status: int
    openapi_valid: bool
    message: str


class ScanSummary(BaseModel):
    id: UUID
    state: str
    completeness: str
    created_at: datetime


class ProjectOverview(BaseModel):
    project: ProjectView
    recent_scans: list[ScanSummary]
    open_findings: int
    targets: list[TargetView]
