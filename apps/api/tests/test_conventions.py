from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError
from test_health import settings

from aegis_api.conventions import (
    APIError,
    Cursor,
    CursorCodec,
    FindingQuery,
    FindingSummary,
    etag,
    expected_version,
    request_digest,
)
from aegis_api.main import create_app


def test_cursor_binding_and_tampering() -> None:
    codec = CursorCodec(b"synthetic-test-only-signing-key-000")
    org = uuid4()
    query = FindingQuery()
    binding = codec.binding("findings", query)
    cursor = Cursor(
        organization_id=org, binding=binding, created_at=datetime.now(UTC), id=uuid4()
    )
    encoded = codec.encode(cursor)
    assert codec.decode(encoded, org, binding) == cursor
    for token, tenant_id, scope in [
        (encoded[:-8] + "abcdefgh", org, binding),
        (encoded, uuid4(), binding),
        (encoded, org, codec.binding("findings", FindingQuery(state="resolved"))),
        ("!", org, binding),
    ]:
        with pytest.raises(APIError) as error:
            codec.decode(token, tenant_id, scope)
        assert error.value.status == 400


def test_serialization_and_validation() -> None:
    at = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    summary = FindingSummary(
        id=uuid4(),
        target_id=uuid4(),
        created_at=at,
        updated_at=at,
        title="Synthetic",
        scanner_severity="high",
        state="new",
    )
    body = summary.model_dump(mode="json")
    assert body["created_at"] == "2025-12-31T18:30:00Z"
    assert body["scanner_severity"] == "high"
    assert body["state"] == "new"
    for changes in [
        {"created_at": datetime(2026, 1, 1)},
        {"state": "clean"},
        {"token": "synthetic-canary"},
    ]:
        with pytest.raises(ValidationError):
            FindingSummary.model_validate(summary.model_dump() | changes)
    for query in [
        {"limit": 101},
        {"order": "password_hash"},
        {"organization_id": str(uuid4())},
    ]:
        with pytest.raises(ValidationError):
            FindingQuery.model_validate(query)


def test_preconditions_and_digest() -> None:
    assert expected_version(etag(2)) == 2
    for value, status in [
        (None, 428),
        ('W/"1"', 400),
        ("*", 400),
        ('"0"', 400),
        ('"١"', 400),
    ]:
        with pytest.raises(APIError) as error:
            expected_version(value)
        assert error.value.status == status
    assert request_digest({"a": 1, "b": 2}) == request_digest({"b": 2, "a": 1})


def test_error_boundary_and_openapi() -> None:
    app = create_app(settings())

    class Input(BaseModel):
        count: int

    @app.post("/api/v1/test-input")
    async def validate(body: Input) -> None:
        pass

    @app.get("/api/v1/test-error")
    async def fail() -> None:
        raise RuntimeError("synthetic-secret-canary")

    @app.get("/api/v1/test-http")
    async def http_fail() -> None:
        raise HTTPException(403, "synthetic-secret-canary")

    with TestClient(app) as client:
        responses = [
            client.get("/api/v1/missing"),
            client.get("/api/v1/test-error"),
            client.get("/api/v1/test-http"),
            client.post(
                "/api/v1/test-input", json={"count": "synthetic-secret-canary"}
            ),
        ]
        assert [r.status_code for r in responses] == [404, 500, 403, 422]
        for response in responses:
            body = response.json()["error"]
            assert set(body) == {"code", "message", "details", "request_id"}
            assert body["request_id"] == response.headers["X-Request-ID"]
            assert response.headers["Cache-Control"] == "no-store"
            assert "synthetic-secret-canary" not in response.text
        assert client.get("/api/v1/openapi.json").json()["info"]["version"] == "0.4.0"
    config = settings().model_copy(update={"profile": "prod"})
    with TestClient(create_app(config)) as client:
        assert client.get("/api/v1/openapi.json").status_code == 404


def test_schema_catalog_contains_only_safe_responses() -> None:
    import json

    from aegis_api.db.models import Base
    from aegis_api.schema_docs import documents

    docs = documents()
    assert len(Base.metadata.tables) == 23
    api = json.loads(docs["openapi.json"])
    assert set(api["paths"]) == {"/health/live", "/health/ready"}
    for name in [
        "password_hash",
        "token_hash",
        "key_hash",
        "restricted_object_key",
        "secret_provider_ref",
    ]:
        assert name not in docs["conventions.schema.json"]
        assert name not in docs["openapi.json"]
    assert all(
        "created_at" in table.c and "updated_at" in table.c
        for table in Base.metadata.tables.values()
    )
