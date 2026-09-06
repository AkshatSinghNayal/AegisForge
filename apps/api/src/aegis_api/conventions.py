"""Shared API primitives. Business endpoints opt in after authentication exists."""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from starlette.exceptions import HTTPException

from aegis_api.db.enums import FindingState, ScanState, Severity
from aegis_api.logging import correlation_id


class Schema(BaseModel):
    model_config = ConfigDict(
        extra="forbid", from_attributes=True, hide_input_in_errors=True
    )


class ErrorDetail(Schema):
    field: str
    code: str


class Error(Schema):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)
    request_id: UUID


class ErrorResponse(Schema):
    error: Error


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message


def error_response(
    status: int, code: str, message: str, details: list[ErrorDetail] | None = None
) -> JSONResponse:
    body = ErrorResponse(
        error=Error(
            code=code,
            message=message,
            details=details or [],
            request_id=UUID(correlation_id.get()),
        )
    )
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    return error_response(exc.status, exc.code, exc.message)


async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    # Never echo exception detail or arbitrary headers from dependencies.
    return error_response(
        exc.status_code, "http_error", "Request could not be completed."
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Input, ctx, msg and user-controlled location names can contain secrets.
    return error_response(422, "validation_error", "Request validation failed.")


class RecordSummary(Schema):
    id: UUID
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class FindingSummary(RecordSummary):
    target_id: UUID
    title: str
    scanner_severity: Severity
    state: FindingState


class EventSummary(RecordSummary):
    scan_id: UUID
    sequence: int
    stage: ScanState
    message_code: str
    attempt: int


class Page(Schema):
    next_cursor: str | None
    has_more: bool


class Collection[T](Schema):
    data: list[T]
    page: Page
    request_id: UUID


class ListQuery(Schema):
    limit: Annotated[int, Field(ge=1, le=100)] = 25
    cursor: Annotated[str | None, Field(max_length=2048)] = None
    order: Literal["created_at", "-created_at"] = "-created_at"


class FindingQuery(ListQuery):
    target_id: UUID | None = None
    severity: Severity | None = None
    state: FindingState | None = None
    cwe: Annotated[int | None, Field(gt=0)] = None


class EventQuery(ListQuery):
    scan_id: UUID


class Cursor(Schema):
    version: Literal[1] = 1
    organization_id: UUID
    binding: str
    created_at: AwareDatetime
    id: UUID


class CursorCodec:
    def __init__(self, signing_key: bytes) -> None:
        if len(signing_key) < 32:
            raise ValueError("Cursor signing key must have at least 32 bytes")
        self._key = signing_key

    @staticmethod
    def binding(resource: str, query: ListQuery) -> str:
        value = {
            "resource": resource,
            "query": query.model_dump(mode="json", exclude={"cursor"}),
        }
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def encode(self, cursor: Cursor) -> str:
        payload = cursor.model_dump_json().encode()
        signature = hmac.digest(self._key, payload, "sha256")
        return base64.urlsafe_b64encode(signature + payload).decode().rstrip("=")

    def decode(self, value: str, organization_id: UUID, binding: str) -> Cursor:
        try:
            if len(value) > 2048:
                raise ValueError
            data = base64.b64decode(
                value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
            )
            signature, payload = data[:32], data[32:]
            if not hmac.compare_digest(
                signature, hmac.digest(self._key, payload, "sha256")
            ):
                raise ValueError
            cursor = Cursor.model_validate_json(payload)
            if cursor.organization_id != organization_id or cursor.binding != binding:
                raise ValueError
            return cursor
        except (ValueError, TypeError) as exc:
            raise APIError(
                400, "invalid_cursor", "Cursor is invalid for this query."
            ) from exc


def etag(version: int) -> str:
    return f'"{version}"'


def expected_version(if_match: str | None) -> int:
    if if_match is None:
        raise APIError(428, "precondition_required", "If-Match is required.")
    if not (
        len(if_match) <= 22
        and if_match.startswith('"')
        and if_match.endswith('"')
        and if_match[1:-1].isascii()
        and if_match[1:-1].isdigit()
    ):
        raise APIError(
            400, "invalid_precondition", "Use a quoted positive resource version."
        )
    value = int(if_match[1:-1])
    if value < 1:
        raise APIError(
            400, "invalid_precondition", "Use a quoted positive resource version."
        )
    return value


def request_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
