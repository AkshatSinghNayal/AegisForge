"""Strict Phase 6 regressions: malformed inputs and failure paths."""

import json
from unittest.mock import AsyncMock

import aiohttp
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select
from test_auth import client as auth_client
from test_configuration import setup, spec

from aegis_api import configuration
from aegis_api import target_validation as validation
from aegis_api.conventions import APIError
from aegis_api.db.models import TargetSecretReference

client = auth_client


def test_openapi_named_maps_are_not_metadata():
    doc = spec()
    doc["paths"] = {
        "/data": {"get": {"responses": {"default": {"description": "CANARY"}}}}
    }
    names = ["description", "default", "example", "enum", "servers", "x-field"]
    doc["components"] = {
        "schemas": {
            "Payload": {
                "type": "object",
                "properties": {
                    name: {"type": "string", "example": "CANARY"} for name in names
                },
            }
        }
    }
    result = validation.sanitize_openapi(json.dumps(doc).encode(), "api.json")
    assert set(result["components"]["schemas"]["Payload"]["properties"]) == set(names)
    assert "default" in result["paths"]["/data"]["get"]["responses"]
    assert "CANARY" not in json.dumps(result)


@pytest.mark.parametrize(
    "bad",
    [{"servers": "not-an-array"}, {"unknownField": True}, {"info": {"title": "bad"}}],
)
def test_invalid_original_cannot_be_sanitized_into_success(bad):
    with pytest.raises(APIError):
        validation.sanitize_openapi(json.dumps({**spec(), **bad}).encode(), "api.json")


@pytest.mark.parametrize(
    "scenario",
    [
        "timeout",
        "tls",
        "server_error",
        "missing_location",
        "downgrade",
        "loop",
        "mime",
        "compressed",
        "oversize",
    ],
)
async def test_probe_failure_paths(monkeypatch, scenario):
    monkeypatch.setattr(validation, "resolve", AsyncMock(return_value=["8.8.8.8"]))
    captured = []

    class Content:
        async def iter_chunked(self, size):
            yield b"x" * (validation.MAX_SPEC + 1)

    class Response:
        status = (
            500
            if scenario == "server_error"
            else 302
            if scenario in {"missing_location", "downgrade", "loop"}
            else 200
        )
        headers = (
            {"Location": "http://public.example/"}
            if scenario == "downgrade"
            else {"Location": "/again"}
            if scenario == "loop"
            else {"Content-Encoding": "gzip"}
            if scenario == "compressed"
            else {}
        )
        content_type = "text/html" if scenario == "mime" else "application/json"
        content = Content()

        async def __aenter__(self):
            if scenario == "timeout":
                raise TimeoutError
            if scenario == "tls":
                raise aiohttp.ClientSSLError(None, OSError("synthetic TLS failure"))
            return self

        async def __aexit__(self, *args):
            pass

    class Client:
        def __init__(self, **kwargs):
            self.connector = kwargs["connector"]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            await self.connector.close()

        def get(self, url, **kwargs):
            captured.append(kwargs)
            return Response()

    monkeypatch.setattr(validation.aiohttp, "ClientSession", Client)
    with pytest.raises(APIError) as error:
        await validation.probe_url(
            "https://public.example/",
            fetch_spec=scenario in {"mime", "compressed", "oversize"},
        )
    assert error.value.status == 422
    assert all(
        call["headers"] == {"Accept-Encoding": "identity"}
        and not call["allow_redirects"]
        for call in captured
    )
    assert len(captured) == (6 if scenario == "loop" else 1)


@pytest.mark.integration
async def test_archived_project_still_allows_revocation(client, db, monkeypatch):
    prefix, _, project, _, target = await setup(client)
    monkeypatch.setattr(
        configuration,
        "probe_url",
        AsyncMock(return_value=("https://synthetic.example/", 200, b"")),
    )
    client.app.state.config.local_secret_key = SecretStr(Fernet.generate_key().decode())
    target["credential"] = {"auth_type": "bearer", "value": "SECRET-CANARY"}
    response = await client.post(prefix + "/targets", json=target)
    assert response.status_code == 200
    target_id = response.json()["id"]
    ref_id = response.json()["credentials"][0]["id"]
    await client.delete(prefix + "/projects/" + project["id"])
    response = await client.delete(
        prefix + "/targets/" + target_id + "/credentials/" + ref_id
    )
    assert response.status_code == 200, response.text
    ref = await db.scalar(
        select(TargetSecretReference).where(TargetSecretReference.id == ref_id)
    )
    assert ref.revoked_at
    assert (await client.delete(prefix + "/targets/" + target_id)).status_code == 200


@pytest.mark.integration
async def test_foreign_target_and_secret_mutations_denied(client, db, monkeypatch):
    from factories import tenant

    from aegis_api.db.enums import Role
    from aegis_api.db.models import OrganizationMember

    prefix, body, _, _, target = await setup(client)
    foreign = await tenant(db)
    foreign_target = str(foreign[2].id)
    for suffix, method, data in [
        ("", "GET", None),
        ("", "DELETE", None),
        ("/credentials", "POST", {"auth_type": "bearer", "value": "CANARY"}),
        ("/credentials/" + foreign_target, "DELETE", None),
    ]:
        response = await client.request(
            method, prefix + "/targets/" + foreign_target + suffix, json=data
        )
        assert response.status_code == 404, response.text
    member = await db.scalar(
        select(OrganizationMember).where(OrganizationMember.id == body["owner_id"])
    )
    member.role = Role.DEVELOPER
    await db.flush()
    probe = AsyncMock()
    monkeypatch.setattr(configuration, "probe_url", probe)
    response = await client.post(
        prefix + "/targets",
        json={**target, "authorization_owner_id": str(foreign[1].id)},
    )
    assert response.status_code == 422
    probe.assert_not_called()


@pytest.mark.integration
async def test_missing_key_rolls_back_target_and_secret(client, db, monkeypatch):
    prefix, _, _, _, target = await setup(client)
    monkeypatch.setattr(
        configuration,
        "probe_url",
        AsyncMock(return_value=("https://synthetic.example/", 200, b"")),
    )
    from contextlib import asynccontextmanager

    from aegis_api import auth

    @asynccontextmanager
    async def borrowed_session():
        yield db

    # Exercise the production rollback dependency, not the shared-session
    # fixture override (which intentionally does not end request transactions).
    client.app.state.sessions = borrowed_session
    client.app.dependency_overrides.pop(auth.session)
    client.app.state.config.local_secret_key = SecretStr("")
    response = await client.post(
        prefix + "/targets",
        json={**target, "credential": {"auth_type": "bearer", "value": "CANARY"}},
    )
    assert response.status_code == 503
    assert "CANARY" not in response.text
    assert (await client.get(prefix + "/targets")).json() == []


async def test_fragmented_upload_replayed_as_one_bounded_body():
    from aegis_api.body_limit import ConfigurationBodyLimit

    count = 0
    received = []

    async def receive():
        nonlocal count
        count += 1
        return {"type": "http.request", "body": b"x", "more_body": count < 10000}

    async def app(scope, receive, send):
        received.append(await receive())

    async def send(message):
        pass

    await ConfigurationBodyLimit(app)({"type": "http", "method": "POST"}, receive, send)
    assert received == [
        {"type": "http.request", "body": b"x" * 10000, "more_body": False}
    ]


@pytest.mark.integration
async def test_legacy_policy_is_not_exposed_as_current_preset(client, db):
    from test_auth import login, register

    from aegis_api.db.enums import ScanMode, Severity
    from aegis_api.db.models import ScanPolicy

    await register(client)
    await login(client)
    org = (await client.get("/api/v1/organizations")).json()[0]["id"]
    prefix = f"/api/v1/organizations/{org}"
    row = ScanPolicy(
        organization_id=org,
        name="Passive baseline",
        version=1,
        mode=ScanMode.PASSIVE,
        fail_severity=Severity.HIGH,
        max_duration_seconds=300,
        max_requests=100,
        max_depth=2,
        require_enrichment=False,
        require_report=False,
        allow_waivers=False,
        required_coverage=["passive"],
        schema_version="legacy.v1",
        rules_snapshot={},
    )
    db.add(row)
    await db.commit()
    response = await client.get(prefix + "/policies/" + str(row.id))
    assert response.status_code == 409
    response = await client.post(prefix + "/policies/presets")
    assert response.status_code == 200, response.text
    replacement = response.json()[0]
    assert replacement["id"] != str(row.id)
    assert replacement["version"] == 2
    assert row.rules_snapshot == {}


def test_schema_property_named_components_cannot_hide_external_reference(monkeypatch):
    from unittest.mock import Mock

    from aegis_api.conventions import APIError

    doc = spec()
    doc["components"] = {
        "schemas": {
            "Payload": {
                "type": "object",
                "properties": {
                    "components": {
                        "type": "array",
                        "items": {"$ref": "http://127.0.0.1/schema"},
                    }
                },
            }
        }
    }
    validator = Mock()
    monkeypatch.setattr(validation, "validate", validator)
    with pytest.raises(APIError):
        validation.sanitize_openapi(json.dumps(doc).encode(), "api.json")
    validator.assert_not_called()
