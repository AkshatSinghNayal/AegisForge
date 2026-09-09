"""Phase 6 security and real PostgreSQL service coverage."""

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_auth import client as auth_client
from test_auth import login, register

from aegis_api import configuration
from aegis_api import target_validation as validation
from aegis_api.configuration_schemas import CredentialInput, PolicyInput, TargetView
from aegis_api.conventions import APIError
from aegis_api.db.models import TargetSecretReference
from aegis_api.secret_store import LocalSecretStore
from aegis_api.settings import Settings

client = auth_client


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "127.1.2.3",
        "0.0.0.0",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "169.254.170.2",
        "100.100.100.200",
        "168.63.129.16",
        "fd00:ec2::254",
        "fec0::1",
        "64:ff9b:1::a00:1",
        "224.0.0.1",
        "255.255.255.255",
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "::ffff:8.8.8.8",
        "64:ff9b::a00:1",
        "2002:7f00:1::",
        "2001::1",
    ],
)
def test_blocked_addresses(address):
    assert not validation.permitted_ip(address)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "169.254.169.254",
        "::1",
        "fe80::1",
        "224.0.0.1",
        "168.63.129.16",
        "fd00:ec2::254",
        "fec0::1",
    ],
)
def test_internal_exception_still_blocks_special_addresses(address):
    assert not validation.permitted_ip(address, True)


def test_private_exception_and_public_addresses():
    for address in ["10.2.3.4", "172.20.1.1", "192.168.1.1", "fd00::1"]:
        assert validation.permitted_ip(address, True)
    for address in ["8.8.8.8", "2606:4700:4700::1111"]:
        assert validation.permitted_ip(address)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://example.com",
        "http://user:secret@example.com",
        "https://example.com/?token=secret",
        "http://example.com#secret",
        "http://example.com\\@127.0.0.1",
        "http://[fe80::1%25eth0]/",
        "http://example.com:99999",
        "http://example.com\n/",
    ],
)
def test_url_syntax(url):
    with pytest.raises(APIError):
        validation.canonical_url(url)


async def test_dns_mixed_answers_and_numeric_forms(monkeypatch):
    loop = validation.asyncio.get_running_loop()
    lookup = AsyncMock(
        return_value=[(2, 1, 6, "", ("8.8.8.8", 80)), (2, 1, 6, "", ("127.0.0.1", 80))]
    )
    monkeypatch.setattr(loop, "getaddrinfo", lookup)
    for host in ["public.example", "2130706433", "0177.0.0.1", "0x7f000001", "127.1"]:
        with pytest.raises(APIError):
            await validation.resolve(host, 80, False)


async def test_pinned_resolver_never_requeries_dns(monkeypatch):
    lookup = AsyncMock(side_effect=AssertionError("DNS must not be consulted again"))
    monkeypatch.setattr(validation.asyncio.get_running_loop(), "getaddrinfo", lookup)
    resolver = validation.PinnedResolver("public.example", ["8.8.8.8"])
    assert (await resolver.resolve("public.example", 443))[0]["host"] == "8.8.8.8"
    with pytest.raises(APIError):
        await resolver.resolve("different.example", 443)
    lookup.assert_not_called()


async def test_redirect_rebinding_checked_before_second_connection(monkeypatch):
    lookup = AsyncMock(
        side_effect=[["8.8.8.8"], APIError(422, "invalid_target", "blocked")]
    )
    monkeypatch.setattr(validation, "resolve", lookup)
    connections = []

    class Response:
        status = 302
        headers = {"Location": "/next"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Client:
        def __init__(self, **kwargs):
            connections.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            await connections[-1]["connector"].close()

        def get(self, *args, **kwargs):
            assert kwargs["allow_redirects"] is False
            return Response()

    monkeypatch.setattr(validation.aiohttp, "ClientSession", Client)
    with pytest.raises(APIError):
        await validation.probe_url("https://public.example/")
    assert lookup.await_count == 2
    assert len(connections) == 1
    assert connections[0]["trust_env"] is False


def spec():
    return {
        "openapi": "3.0.3",
        "info": {"title": "Synthetic", "version": "1", "description": "CANARY"},
        "paths": {},
        "servers": [{"url": "http://169.254.169.254"}],
        "x-token": "CANARY",
    }


def test_openapi_sanitization():
    result = validation.sanitize_openapi(json.dumps(spec()).encode(), "api.json")
    assert "CANARY" not in json.dumps(result)
    assert "servers" not in result
    assert result["openapi"] == "3.0.3"
    doc = spec()
    doc["paths"] = {
        "/health": {"get": {"responses": {"200": {"description": "CANARY"}}}}
    }
    result = validation.sanitize_openapi(json.dumps(doc).encode(), "api.json")
    assert "CANARY" not in json.dumps(result)
    assert result["paths"]["/health"]["get"]["responses"]["200"]["description"]


@pytest.mark.parametrize(
    "content,filename",
    [
        (b"{}", "a.json"),
        (b"[]", "a.json"),
        (b"<!DOCTYPE html>", "a.html"),
        (b"a: &a [*a]", "a.yaml"),
        (b"!!python/object/apply:os.system [echo bad]", "a.yaml"),
        (b"[" * 100 + b"]" * 100, "a.json"),
        (b"x" * (1048576 + 1), "a.json"),
        (b'{"openapi":"9.0.0"}', "a.json"),
    ],
)
def test_malformed_and_oversized_openapi(content, filename):
    with pytest.raises(APIError):
        validation.sanitize_openapi(content, filename)


@pytest.mark.parametrize(
    "ref",
    [
        "https://example.com/spec",
        "file:///etc/passwd",
        "//169.254.169.254/latest",
        "../private.yaml",
    ],
)
def test_external_ref_rejected_without_fetch(ref):
    doc = spec()
    doc["components"] = {"schemas": {"A": {"$ref": ref}}}
    with pytest.raises(APIError):
        validation.sanitize_openapi(json.dumps(doc).encode(), "a.json")


def test_secret_context_encryption_and_redaction():
    config = Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        redis_url="redis://localhost",
        local_secret_key=Fernet.generate_key().decode(),
    )
    store = LocalSecretStore(config)
    org, ref = uuid4(), uuid4()
    encrypted = store.seal(org, ref, "SECRET-CANARY")
    assert "SECRET-CANARY" not in encrypted
    assert store.open(org, ref, encrypted) == "SECRET-CANARY"
    with pytest.raises(ValueError):
        store.open(uuid4(), ref, encrypted)
    assert "SECRET-CANARY" not in repr(
        CredentialInput(auth_type="bearer", value="SECRET-CANARY")
    )
    assert "value" not in TargetView.model_json_schema()["properties"]
    with pytest.raises(APIError):
        LocalSecretStore(config.model_copy(update={"profile": "prod"}))


def test_policy_and_credential_schema_guards():
    for body in [
        {"mode": "active"},
        {"allow_private": True},
        {"mode": "passive", "active_rule_allowlist": ["40012"]},
    ]:
        with pytest.raises(ValidationError):
            PolicyInput(name="Synthetic", **body)
    for body in [
        {"auth_type": "api_key", "header_name": "Host", "value": "a"},
        {"auth_type": "bearer", "value": "a\r\nb"},
        {"auth_type": "basic", "value": "a"},
        {"auth_type": "oauth", "value": "a"},
    ]:
        with pytest.raises(ValidationError):
            CredentialInput(**body)


async def setup(client):
    await register(client)
    await login(client)
    org = (await client.get("/api/v1/organizations")).json()[0]["id"]
    prefix = f"/api/v1/organizations/{org}"
    member = (await client.get(prefix + "/configuration-identity")).json()["member_id"]
    body = {
        "name": "Synthetic project",
        "slug": "synthetic",
        "owner_id": member,
        "member_ids": [member],
    }
    response = await client.post(prefix + "/projects", json=body)
    assert response.status_code == 200, response.text
    project = response.json()
    response = await client.post(prefix + "/policies/presets")
    assert response.status_code == 200, response.text
    policy = response.json()[0]
    target = {
        "project_id": project["id"],
        "display_name": "Synthetic target",
        "kind": "web_url",
        "base_url": "https://synthetic.example/",
        "authorization_declaration": "I own this synthetic test application.",
        "authorization_owner_id": member,
        "consent": True,
        "policy_id": policy["id"],
    }
    return prefix, body, project, policy, target


@pytest.mark.integration
async def test_project_target_secret_and_policy_versions(client, db, monkeypatch):
    prefix, body, project, policy, target = await setup(client)
    monkeypatch.setattr(
        configuration,
        "probe_url",
        AsyncMock(return_value=("https://synthetic.example/", 200, b"")),
    )
    from pydantic import SecretStr

    client.app.state.config.local_secret_key = SecretStr(Fernet.generate_key().decode())
    target["credential"] = {"auth_type": "bearer", "value": "SECRET-CANARY"}
    response = await client.post(prefix + "/targets", json=target)
    assert response.status_code == 200, response.text
    assert "SECRET-CANARY" not in response.text and "ciphertext" not in response.text
    row = response.json()
    secret = await db.scalar(
        select(TargetSecretReference).where(
            TargetSecretReference.target_id == row["id"]
        )
    )
    assert secret.ciphertext and "SECRET-CANARY" not in secret.ciphertext
    overview = await client.get(prefix + "/projects/" + project["id"])
    assert overview.status_code == 200, overview.text
    assert overview.json()["open_findings"] == 0
    assert len(overview.json()["targets"]) == 1
    edit = {k: v for k, v in policy.items() if k not in {"id", "version"}}
    edit["rate_limit"] = 1
    revision = await client.put(prefix + "/policies/" + policy["id"], json=edit)
    assert revision.status_code == 200, revision.text
    assert revision.json()["version"] == 2
    assert (await client.get(prefix + "/targets/" + row["id"])).json()[
        "policy_id"
    ] == policy["id"]
    from uuid import UUID

    from factories import scan as make_scan

    from aegis_api.db.models import Organization, OrganizationMember, ScanPolicy, Target

    org = await db.get(Organization, UUID(prefix.split("/")[-1]))
    actor = await db.get(OrganizationMember, UUID(body["owner_id"]))
    persisted_target = await db.get(Target, UUID(row["id"]))
    persisted_policy = await db.get(ScanPolicy, UUID(policy["id"]))
    scan = make_scan(org, actor, persisted_target, persisted_policy)
    scan.config_snapshot = {
        "policy": persisted_policy.rules_snapshot,
        "policy_version": persisted_policy.version,
    }
    db.add(scan)
    await db.flush()
    assert scan.policy_id == persisted_policy.id
    assert scan.config_snapshot["policy_version"] == 1
    with pytest.raises(DBAPIError):
        async with db.begin_nested():
            await db.execute(
                text("UPDATE scan_policies SET max_requests=1 WHERE id=:id"),
                {"id": policy["id"]},
            )
        # nested transaction rollback is required after trigger denial
    assert (
        await client.put(
            prefix + "/projects/" + project["id"],
            json={**body, "description": "Updated"},
        )
    ).status_code == 200
    assert (
        await client.delete(prefix + "/projects/" + project["id"])
    ).status_code == 200
    assert (
        await client.post(prefix + "/targets/validate", json=target)
    ).status_code == 409
    assert (
        await client.post(prefix + "/projects/" + project["id"] + "/restore")
    ).status_code == 200
    assert (
        await client.delete(
            prefix
            + "/targets/"
            + row["id"]
            + "/credentials/"
            + row["credentials"][0]["id"]
        )
    ).status_code == 200
    assert (await client.get(prefix + "/targets/" + row["id"])).json()[
        "credentials"
    ] == []
    assert (await client.delete(prefix + "/targets/" + row["id"])).status_code == 200


@pytest.mark.integration
@pytest.mark.parametrize("role", ["admin", "developer", "viewer"])
async def test_configuration_roles_and_cross_tenant(client, db, monkeypatch, role):
    from factories import tenant

    from aegis_api.db.enums import Role
    from aegis_api.db.models import OrganizationMember, ProjectMember

    prefix, body, project, policy, target = await setup(client)
    monkeypatch.setattr(
        configuration,
        "probe_url",
        AsyncMock(return_value=("https://synthetic.example/", 200, b"")),
    )
    foreign = await tenant(db)
    member = await db.scalar(
        select(OrganizationMember).where(OrganizationMember.id == body["owner_id"])
    )
    member.role = Role(role)
    await db.flush()
    assert (
        await client.get(prefix + "/projects/" + str(foreign[2].project_id))
    ).status_code == 404
    assert (
        await client.get(prefix + "/policies/" + str(foreign[3].id))
    ).status_code == 404
    response = await client.post(prefix + "/targets", json=target)
    assert response.status_code == (403 if role == "viewer" else 200), response.text
    assert (
        await client.post(prefix + "/policies", json={"name": "New policy"})
    ).status_code == (200 if role == "admin" else 403)
    assert (
        await client.put(prefix + "/projects/" + project["id"], json=body)
    ).status_code == (200 if role == "admin" else 403)
    if role != "admin":
        assignment = await db.scalar(
            select(ProjectMember).where(
                ProjectMember.member_id == member.id,
                ProjectMember.project_id == project["id"],
            )
        )
        assignment.status = "deactivated"
        await db.flush()
        assert (
            await client.get(prefix + "/projects/" + project["id"])
        ).status_code == 404


@pytest.mark.integration
async def test_invalid_configuration_no_writes(client, monkeypatch):
    prefix, body, project, policy, target = await setup(client)
    probe = AsyncMock(
        side_effect=APIError(422, "invalid_target", "Blocked destination.")
    )
    monkeypatch.setattr(configuration, "probe_url", probe)
    assert (await client.post(prefix + "/targets", json=target)).status_code == 422
    assert (await client.get(prefix + "/targets")).json() == []
    assert (await client.post(prefix + "/projects", json=body)).status_code == 409
    assert (
        await client.post(
            prefix + "/targets", json={**target, "policy_id": str(uuid4())}
        )
    ).status_code == 404
    assert (
        await client.post(
            prefix + "/targets", json={**target, "authorization_owner_id": str(uuid4())}
        )
    ).status_code == 422


async def test_chunked_request_limit():
    from aegis_api.body_limit import ConfigurationBodyLimit

    called = False

    async def downstream(scope, receive, send):
        nonlocal called
        called = True

    incoming = iter(
        [
            {"type": "http.request", "body": b"x" * 1048576, "more_body": True},
            {"type": "http.request", "body": b"x" * 1048577, "more_body": False},
        ]
    )

    async def receive():
        return next(incoming)

    sent = []

    async def send(message):
        sent.append(message)

    from aegis_api.logging import correlation_id

    token = correlation_id.set(str(uuid4()))
    await ConfigurationBodyLimit(downstream)(
        {"type": "http", "method": "POST"}, receive, send
    )
    correlation_id.reset(token)
    assert not called and sent[0]["status"] == 413
    assert b"xxxx" not in sent[1]["body"]


@pytest.mark.parametrize(
    "location",
    [
        "http://169.254.169.254/latest",
        "http://[fd00:ec2::254]/latest",
        "http://user:secret@public.example/",
        "//127.0.0.1/",
        "https://public.example/?token=secret",
    ],
)
async def test_redirect_tricks_rejected(monkeypatch, location):
    connections = []

    class Response:
        status = 302
        headers = {"Location": location}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Client:
        def __init__(self, **kwargs):
            connections.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            await connections[-1]["connector"].close()

        def get(self, *args, **kwargs):
            return Response()

    async def lookup(host, port, **kwargs):
        return [(2, 1, 6, "", ("8.8.8.8" if host == "public.example" else host, port))]

    monkeypatch.setattr(validation.asyncio.get_running_loop(), "getaddrinfo", lookup)
    monkeypatch.setattr(validation.aiohttp, "ClientSession", Client)
    with pytest.raises(APIError):
        await validation.probe_url("https://public.example/")
    assert len(connections) == 1


@pytest.mark.integration
@pytest.mark.parametrize(
    "auth_type,header",
    [("api_key", "X-API-Key"), ("bearer", "Authorization"), ("basic", "Authorization")],
)
async def test_each_credential_type_is_input_only(
    client, db, monkeypatch, auth_type, header
):
    from pydantic import SecretStr

    prefix, body, project, policy, target = await setup(client)
    monkeypatch.setattr(
        configuration,
        "probe_url",
        AsyncMock(return_value=("https://synthetic.example/", 200, b"")),
    )
    client.app.state.config.local_secret_key = SecretStr(Fernet.generate_key().decode())
    response = await client.post(prefix + "/targets", json=target)
    target_id = response.json()["id"]
    payload = {
        "auth_type": auth_type,
        "header_name": header,
        "value": "PRIVATE-CANARY",
        "username": "user-canary" if auth_type == "basic" else None,
    }
    response = await client.post(
        prefix + "/targets/" + target_id + "/credentials", json=payload
    )
    assert response.status_code == 200, response.text
    assert "PRIVATE-CANARY" not in response.text and "user-canary" not in response.text
    ref = await db.scalar(
        select(TargetSecretReference).where(
            TargetSecretReference.target_id == target_id
        )
    )
    assert ref.header_name == header
    decrypted = LocalSecretStore(client.app.state.config).open(
        ref.organization_id, ref.id, ref.ciphertext
    )
    assert decrypted.startswith(
        {"api_key": "PRIVATE-CANARY", "bearer": "Bearer ", "basic": "Basic "}[auth_type]
    )


@pytest.mark.integration
async def test_openapi_upload_and_url_paths(client, monkeypatch):
    prefix, body, project, policy, target = await setup(client)
    probe = AsyncMock(
        return_value=("https://synthetic.example/", 200, json.dumps(spec()).encode())
    )
    monkeypatch.setattr(configuration, "probe_url", probe)
    response = await client.post(
        prefix + "/targets",
        json={
            **target,
            "kind": "openapi_upload",
            "upload_filename": "a.yaml",
            "upload_content": "a: &a [*a]",
        },
    )
    assert response.status_code == 422
    probe.assert_not_called()
    response = await client.post(
        prefix + "/targets",
        json={
            **target,
            "kind": "openapi_upload",
            "upload_filename": "a.json",
            "upload_content": json.dumps(spec()),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["has_openapi"]
    assert "CANARY" not in response.text
    response = await client.post(
        prefix + "/targets",
        json={
            **target,
            "base_url": "https://synthetic.example/api",
            "kind": "openapi_url",
            "openapi_url": "https://synthetic.example/openapi.json",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["has_openapi"]
    assert probe.await_count == 3
