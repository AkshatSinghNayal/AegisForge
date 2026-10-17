"""Phase 16 regressions; existing suites supply the remaining abuse matrix."""

import asyncio
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute, _iter_routes_with_context
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from test_auth import client, login, register  # noqa: F401
from test_health import settings

from aegis_api import body_limit
from aegis_api.auth import now
from aegis_api.conventions import APIError
from aegis_api.db.enums import RecordState
from aegis_api.db.models import APIKey, User
from aegis_api.logging import correlation_id
from aegis_api.main import create_app
from aegis_api.settings import Settings
from aegis_api.target_validation import sanitize_openapi


@pytest.mark.parametrize("path", ["/health/live", "/missing", "/api/v1/auth/me"])
def test_headers_and_no_cross_origin_access(path):
    with TestClient(
        create_app(
            settings().model_copy(
                update={"reporting_enabled": False, "scan_coordinator_enabled": False}
            )
        )
    ) as http:
        response = http.get(path, headers={"Origin": "https://attacker.invalid"})
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert "default-src 'none'" in response.headers["Content-Security-Policy"]
        assert "Access-Control-Allow-Origin" not in response.headers
        preflight = http.options(
            path,
            headers={
                "Origin": "https://attacker.invalid",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,x-csrf-token",
            },
        )
        assert "Access-Control-Allow-Origin" not in preflight.headers


def test_production_security_headers():
    config = settings().model_copy(
        update={
            "profile": "prod",
            "cookie_secure": True,
            "app_origin": "https://aegis.test",
        }
    )
    with TestClient(create_app(config)) as http:
        response = http.get("/api/v1/docs")
        assert response.status_code == 404
        assert response.headers["Strict-Transport-Security"] == "max-age=31536000"


@pytest.mark.parametrize(
    "origin",
    [
        "https://aegis.test:bad",
        "https://aegis.test:0",
        "https://aegis.test?x=1",
        "https://aegis.test#fragment",
        "https://user:pass@aegis.test",
        "https://aegis.test\\evil",
        "https://aegis.test\n",
    ],
)
def test_origin_configuration_is_exact(origin):
    with pytest.raises(ValidationError):
        Settings(**(settings().model_dump() | {"app_origin": origin}))


@pytest.mark.parametrize("mode", ["compressed", "oversize", "trickle"])
async def test_request_body_abuse_never_reaches_handler(monkeypatch, mode):
    called = False
    messages = []

    async def handler(scope, receive, send):
        nonlocal called
        called = True

    async def receive():
        if mode == "trickle":
            await asyncio.sleep(0.02)
            return {"type": "http.request", "body": b"a", "more_body": True}
        return {"type": "http.request", "body": b"a" * (body_limit.MAX_BODY + 1)}

    async def send(message):
        messages.append(message)

    correlation_id.set(str(uuid4()))
    monkeypatch.setattr(body_limit, "BODY_TIMEOUT_SECONDS", 0.01)
    await body_limit.ConfigurationBodyLimit(handler)(
        {
            "type": "http",
            "method": "POST",
            "headers": [(b"content-encoding", b"gzip")] if mode == "compressed" else [],
        },
        receive,
        send,
    )
    assert not called
    assert (
        messages[0]["status"]
        == {"compressed": 415, "oversize": 413, "trickle": 408}[mode]
    )


@pytest.mark.parametrize(
    "content,filename",
    [
        (
            b'{"openapi":"3.0.3","openapi":"3.1.0","info":{"title":"x","version":"1"},"paths":{}}',
            "x.json",
        ),
        (
            b'openapi: 3.0.3\ninfo: {title: x, version: "1"}\npaths: {}\npaths: {}',
            "x.yaml",
        ),
        (
            b'openapi: 3.0.3\ninfo: {title: x, version: "1"}\npaths: {}\nx-num: .nan',
            "x.yaml",
        ),
        (
            b'{"openapi":"3.0.3","info":{"title":"x","version":"1"},"paths":{},"x-num":NaN}',
            "x.json",
        ),
    ],
)
def test_ambiguous_openapi_rejected(content, filename):
    with pytest.raises(APIError):
        sanitize_openapi(content, filename)


@pytest.mark.parametrize(
    "filename", ["../x.json", "/tmp/x.yaml", "..\\x.yml", "x\n.json"]
)
def test_openapi_unsafe_filename(filename):
    with pytest.raises(APIError):
        sanitize_openapi(
            json.dumps(
                {
                    "openapi": "3.0.3",
                    "info": {"title": "x", "version": "1"},
                    "paths": {},
                }
            ).encode(),
            filename,
        )


def dependency_names(dependant):
    return {getattr(dependant.call, "__name__", "")} | set().union(
        *(dependency_names(d) for d in dependant.dependencies)
    )


def test_all_http_routes_have_explicit_auth_boundary():
    public = {
        "/health/live",
        "/health/ready",
        "/api/v1/auth/csrf",
        "/api/v1/auth/register",
        "/api/v1/auth/sign-in",
        "/api/v1/auth/refresh",
        "/api/v1/auth/forgot-password",
        "/api/v1/auth/reset-password",
        "/api/v1/auth/verify-email",
        "/api/v1/reports/{report_id}/content",
        "/api/hooks/github/{identity}",
    }
    app = create_app(settings())
    checked = 0
    for original, context in _iter_routes_with_context(app.routes):
        if not isinstance(original, APIRoute):
            continue
        route = context or original
        checked += 1
        names = dependency_names(route.dependant)
        assert route.path in public or names & {"principal", "authenticate"}, route.path
        if route.methods & {"POST", "PUT", "PATCH", "DELETE"} and route.path.startswith(
            "/api/v1/"
        ):
            assert "csrf" in names or "/webhooks/" in route.path, route.path
        # All user request objects must reject undeclared fields, recursively.
        if route.body_field:
            schema = route.body_field._type_adapter.json_schema()
            for item in [schema, *schema.get("$defs", {}).values()]:
                if item.get("type") == "object" and "properties" in item:
                    assert item.get("additionalProperties") is False, route.path

    assert checked >= 90, "Route enumeration must include nested routers"


@pytest.mark.integration
async def test_api_key_issuer_status_and_prefix_binding(client, db):  # noqa: F811
    await register(client)
    await login(client)
    org = (await client.get("/api/v1/auth/me")).json()["organizations"][0]["id"]
    created = await client.post(
        f"/api/v1/api-keys?organization_id={org}",
        json={
            "name": "security regression",
            "scopes": ["scans:read"],
            "expires_at": (now() + timedelta(days=1)).isoformat(),
        },
    )
    assert created.status_code == 201
    value = created.json()
    client.headers["Authorization"] = "Bearer " + value["secret"]
    assert (await client.get("/api/public/v1/projects")).status_code == 200
    row = await db.get(APIKey, value["id"])
    prefix = row.prefix
    row.prefix = "agf_wrongprefix_"
    await db.flush()
    assert (await client.get("/api/public/v1/projects")).status_code == 401
    row.prefix = prefix
    user = await db.scalar(
        select(User).where(User.normalized_email == "synthetic@example.test")
    )
    user.status = RecordState.DEACTIVATED
    await db.flush()
    assert (await client.get("/api/public/v1/projects")).status_code == 401


async def test_non_ascii_security_tokens_are_denied_without_server_error():
    from types import SimpleNamespace

    from aegis_api import auth, reporting

    config = settings()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(config=config)),
        headers={"origin": config.app_origin, "x-csrf-token": "é" * 64},
        cookies={"aegis_csrf": "é" * 64},
    )
    with pytest.raises(APIError) as csrf_error:
        await auth.csrf(request, None)
    assert csrf_error.value.status == 403
    with pytest.raises(APIError) as download_error:
        await reporting.content(
            uuid4(), uuid4(), int(now().timestamp()) + 30, "é" * 64, request, None
        )
    assert download_error.value.status == 403


@pytest.mark.parametrize(
    "order", ["created_at; DROP TABLE users", "(SELECT 1)", "organization_id"]
)
def test_dynamic_sql_order_cannot_escape_allowlist(order):
    from aegis_api.conventions import ListQuery

    with pytest.raises(ValidationError):
        ListQuery(order=order)


@pytest.mark.integration
async def test_sql_filter_is_data_and_mass_assignment_denied(client, db):  # noqa: F811
    await register(client)
    await login(client)
    org = (await client.get("/api/v1/auth/me")).json()["organizations"][0]["id"]
    response = await client.get(
        "/api/v1/admin/audit",
        params={"organization_id": org, "action": "x' OR 1=1; DROP TABLE users; --"},
    )
    assert response.status_code == 200 and response.json() == []
    member = (
        await client.get(f"/api/v1/organizations/{org}/configuration-identity")
    ).json()["member_id"]
    denied = await client.post(
        f"/api/v1/organizations/{org}/projects",
        json={
            "name": "Synthetic project",
            "slug": "synthetic-abuse",
            "owner_id": member,
            "member_ids": [member],
            "organization_id": str(uuid4()),
            "role": "owner",
        },
    )
    assert denied.status_code == 422
    assert (await client.get(f"/api/v1/organizations/{org}/projects")).json() == []
    assert (await client.get("/api/v1/auth/me")).status_code == 200
