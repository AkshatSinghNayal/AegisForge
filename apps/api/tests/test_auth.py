from datetime import timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select

from aegis_api import auth
from aegis_api.auth import digest, now, password_hash, password_matches
from aegis_api.auth_models import (
    AccessCredential,
    IdentityAudit,
    IdentityToken,
    Invitation,
)
from aegis_api.db.enums import RecordState, Role
from aegis_api.db.models import OrganizationMember, ProjectMember, User
from aegis_api.main import create_app
from aegis_api.organizations import permitted
from aegis_api.settings import get_settings


def test_password_hash_and_policy():
    a, b = (
        password_hash("long synthetic password"),
        password_hash("long synthetic password"),
    )
    assert a != b and password_matches("long synthetic password", a)
    assert not password_matches("incorrect", a)
    assert not password_matches("incorrect", None)
    assert not password_matches("dummy password that is never a credential", None)
    for role in Role:
        assert permitted(role, "project.read")
        assert permitted(role, "organization.write") == (role == Role.OWNER)
        for action in [
            "members.write",
            "policies.write",
            "integrations.write",
            "projects.write",
        ]:
            assert permitted(role, action) == (role in {Role.OWNER, Role.ADMIN})
        for action in [
            "targets.write",
            "scans.write",
            "findings.write",
            "reports.write",
        ]:
            assert permitted(role, action) == (role != Role.VIEWER)
        assert not permitted(role, "unknown")


@pytest.fixture
async def client(db, monkeypatch):
    config = get_settings().model_copy(update={"auth_rate_limit": 100})
    app = create_app(config)
    app.state.redis = Redis.from_url(config.redis_url.get_secret_value())
    keys = [key async for key in app.state.redis.scan_iter("auth:*")]
    if keys:
        await app.state.redis.delete(*keys)

    async def session():
        yield db

    app.dependency_overrides[auth.session] = session
    deliveries = []

    async def deliver(request, session, email, purpose, token, user_id=None):
        deliveries.append((email, purpose, token))

    monkeypatch.setattr(auth, "deliver", deliver)
    import aegis_api.organizations as organizations

    monkeypatch.setattr(organizations, "deliver", deliver)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=config.app_origin
    ) as http:
        http.headers["Origin"] = config.app_origin
        token = (await http.get("/api/v1/auth/csrf")).json()["csrf_token"]
        http.headers["X-CSRF-Token"] = token
        http.app = app
        http.deliveries = deliveries
        yield http
    await app.state.redis.aclose()


async def register(client, email="synthetic@example.test"):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "synthetic password 12345",
            "display_name": "Synthetic user",
            "organization_name": "Synthetic org",
        },
    )
    assert response.status_code == 200, response.text
    return email


async def login(
    client, email="synthetic@example.test", password="synthetic password 12345"
):
    response = await client.post(
        "/api/v1/auth/sign-in", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
    return response


@pytest.mark.integration
async def test_registration_rotation_replay_logout(client, db):
    email = await register(client)
    await login(client, email)
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["organizations"][0]["role"] == "owner"
    assert not me.json()["email_verified"]
    verification = client.deliveries[0][2]
    assert (
        await client.post("/api/v1/auth/verify-email", json={"token": verification})
    ).status_code == 200
    assert (
        await client.post("/api/v1/auth/verify-email", json={"token": verification})
    ).status_code == 400
    old = client.cookies.get("aegis_refresh")
    rotated = await client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200 and client.cookies.get("aegis_refresh") != old
    client.headers["Authorization"] = "Bearer " + rotated.json()["access_token"]
    replay = await client.post(
        "/api/v1/auth/refresh",
        headers={
            "Cookie": (
                f"aegis_refresh={old}; aegis_csrf={client.headers['X-CSRF-Token']}"
            )
        },
    )
    assert replay.status_code == 401
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401
    await login(client)
    assert (await client.post("/api/v1/auth/sign-out")).status_code == 200
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert not client.cookies.get("aegis_refresh")
    actions = list(await db.scalars(select(IdentityAudit.action)))
    assert "authentication.refresh_rejected" in actions
    assert "authentication.signed_out" in actions
    stored = list(await db.scalars(select(IdentityToken.token_hash)))
    assert verification not in stored and digest(verification) in stored


@pytest.mark.integration
async def test_reset_expiry_single_use_revokes_all(client, db):
    await register(client)
    await login(client)
    first_access = client.headers["Authorization"]
    await login(client)
    await client.post(
        "/api/v1/auth/forgot-password", json={"email": "synthetic@example.test"}
    )
    raw = client.deliveries[-1][2]
    item = await db.scalar(
        select(IdentityToken).where(IdentityToken.token_hash == digest(raw))
    )
    item.expires_at = now() - timedelta(seconds=1)
    await db.commit()
    body = {"token": raw, "password": "new synthetic password 987"}
    assert (
        await client.post("/api/v1/auth/reset-password", json=body)
    ).status_code == 400
    await client.post(
        "/api/v1/auth/forgot-password", json={"email": "synthetic@example.test"}
    )
    body["token"] = client.deliveries[-1][2]
    assert (
        await client.post("/api/v1/auth/reset-password", json=body)
    ).status_code == 200
    assert (
        await client.post("/api/v1/auth/reset-password", json=body)
    ).status_code == 400
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (
        await client.get("/api/v1/auth/me", headers={"Authorization": first_access})
    ).status_code == 401
    await login(client, password=body["password"])
    assert (await client.post("/api/v1/auth/revoke-all")).status_code == 200
    assert (await client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.integration
async def test_rate_limit_and_csrf(client):
    await register(client)
    for headers in [
        {"X-CSRF-Token": ""},
        {"Origin": "https://evil.example"},
        {"Cookie": ""},
    ]:
        response = await client.post(
            "/api/v1/auth/sign-in",
            json={"email": "synthetic@example.test", "password": "wrong"},
            headers=headers,
        )
        assert response.status_code == 403
    client.app.state.config.auth_rate_limit = 3
    responses = [
        await client.post(
            "/api/v1/auth/sign-in", json={"email": email, "password": "wrong"}
        )
        for email in [
            "synthetic@example.test",
            "unknown@example.test",
            "unknown@example.test",
        ]
    ]
    assert [r.status_code for r in responses] == [401, 401, 429]
    assert (
        responses[0].json()["error"]["message"]
        == responses[1].json()["error"]["message"]
    )


async def actor(client, db, org, role):
    user = User(
        normalized_email=f"{uuid4().hex}@example.test", display_name="Synthetic role"
    )
    db.add(user)
    await db.flush()
    member = OrganizationMember(organization_id=org.id, user_id=user.id, role=role)
    db.add(member)
    token = uuid4().hex
    db.add(
        AccessCredential(
            user_id=user.id,
            family_id=uuid4(),
            token_hash=digest(token),
            expires_at=now() + timedelta(minutes=5),
        )
    )
    await db.commit()
    client.headers["Authorization"] = "Bearer " + token
    return member


@pytest.mark.integration
@pytest.mark.parametrize("role", list(Role))
async def test_role_endpoints_and_real_foreign_ids(client, db, two_organizations, role):
    a, b = two_organizations
    member = await actor(client, db, a[0], role)
    base = f"/api/v1/organizations/{a[0].id}"
    foreign = f"/api/v1/organizations/{b[0].id}"
    assert (await client.get(base)).status_code == 200
    assert (await client.get(foreign)).status_code == 404
    assert (await client.patch(foreign, json={"name": "forbidden"})).status_code == 404
    assert (await client.get(base + "/members")).status_code == (
        200 if role in {Role.OWNER, Role.ADMIN} else 403
    )
    assert (await client.patch(base, json={"name": "Updated"})).status_code == (
        200 if role == Role.OWNER else 403
    )
    assert (await client.get(base + f"/resources/targets/{b[2].id}")).status_code == 404
    assert (
        await client.get(base + f"/resources/projects/{b[2].project_id}")
    ).status_code == 404
    result = await client.get(base + f"/resources/targets/{a[2].id}")
    assert result.status_code == (200 if role in {Role.OWNER, Role.ADMIN} else 404)
    if role not in {Role.OWNER, Role.ADMIN}:
        db.add(
            ProjectMember(
                organization_id=a[0].id, project_id=a[2].project_id, member_id=member.id
            )
        )
        await db.commit()
        assert (
            await client.get(base + f"/resources/targets/{a[2].id}")
        ).status_code == 200
    for kind in ["projects", "targets", "scans", "findings", "reports"]:
        assert (await client.get(base + f"/resources/{kind}")).status_code == 200
    assert (
        await client.post(
            base + "/invitations",
            json={"email": "invite@example.test", "role": "viewer"},
        )
    ).status_code == (200 if role in {Role.OWNER, Role.ADMIN} else 403)
    assert (
        await client.patch(base + f"/members/{b[1].id}", json={"role": "viewer"})
    ).status_code == (404 if role in {Role.OWNER, Role.ADMIN} else 403)
    assert (await client.delete(base + f"/members/{a[1].id}")).status_code == 403
    assert (
        await client.post(
            base + "/transfer-ownership", json={"member_id": str(b[1].id)}
        )
    ).status_code == (404 if role == Role.OWNER else 403)
    progress = (await client.get(base + "/onboarding")).json()
    assert progress == {
        "create_project": True,
        "register_target": True,
        "run_safe_baseline": False,
        "configure_ci": False,
    }
    member.status = RecordState.DEACTIVATED
    await db.commit()
    assert (await client.get(base)).status_code == 404


@pytest.mark.integration
async def test_invite_binding_single_use_and_ownership(client, db, two_organizations):
    a, b = two_organizations
    owner = await actor(client, db, a[0], Role.OWNER)
    base = f"/api/v1/organizations/{a[0].id}"
    response = await client.post(
        base + "/invitations", json={"email": "new@example.test", "role": "developer"}
    )
    assert response.status_code == 200
    token = client.deliveries[-1][2]
    assert (
        await client.post("/api/v1/organizations/accept-invite", json={"token": token})
    ).status_code == 400
    await register(client, "new@example.test")
    await login(client, "new@example.test")
    assert (
        await client.post("/api/v1/organizations/accept-invite", json={"token": token})
    ).status_code == 200
    assert (
        await client.post("/api/v1/organizations/accept-invite", json={"token": token})
    ).status_code == 400
    invite = await db.scalar(
        select(Invitation).where(Invitation.token_hash == digest(token))
    )
    assert invite.used_at
    user = await db.scalar(
        select(User).where(User.normalized_email == "new@example.test")
    )
    member = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == a[0].id,
            OrganizationMember.user_id == user.id,
        )
    )
    token = uuid4().hex
    db.add(
        AccessCredential(
            user_id=owner.user_id,
            family_id=uuid4(),
            token_hash=digest(token),
            expires_at=now() + timedelta(minutes=5),
        )
    )
    await db.commit()
    client.headers["Authorization"] = "Bearer " + token
    assert (
        await client.post(
            base + "/transfer-ownership", json={"member_id": str(member.id)}
        )
    ).status_code == 200
    await db.refresh(owner)
    await db.refresh(member)
    assert owner.role == Role.ADMIN and member.role == Role.OWNER
    assert (await client.delete(base)).status_code == 403


@pytest.mark.integration
async def test_concurrent_refresh_replay_revokes_winner(migrated_database, monkeypatch):
    import asyncio

    config = get_settings().model_copy(update={"auth_rate_limit": 100})
    app = create_app(config)

    async def discard_mail(*args, **kwargs):
        pass

    monkeypatch.setattr(auth, "deliver", discard_mail)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=config.app_origin
        ) as first:
            first.headers["Origin"] = config.app_origin
            first.headers["X-CSRF-Token"] = (
                await first.get("/api/v1/auth/csrf")
            ).json()["csrf_token"]
            email = f"{uuid4().hex}@example.test"
            await register(first, email)
            await login(first, email)
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url=config.app_origin,
                headers=dict(first.headers),
                cookies=first.cookies,
            ) as second:
                responses = await asyncio.gather(
                    first.post("/api/v1/auth/refresh"),
                    second.post("/api/v1/auth/refresh"),
                )
                assert sorted(r.status_code for r in responses) == [200, 401]
                winner = next(r for r in responses if r.status_code == 200)
                assert (
                    await first.get(
                        "/api/v1/auth/me",
                        headers={
                            "Authorization": "Bearer " + winner.json()["access_token"]
                        },
                    )
                ).status_code == 401


@pytest.mark.integration
async def test_expired_access_secure_cookie_and_generic_recovery(client, db):
    await register(client)
    client.app.state.config.cookie_secure = True
    response = await login(client)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    assert "Path=/api/v1/auth" in cookie
    credential = await db.scalar(
        select(AccessCredential).where(
            AccessCredential.token_hash == digest(response.json()["access_token"])
        )
    )
    credential.expires_at = now() - timedelta(seconds=1)
    await db.commit()
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    known = await client.post(
        "/api/v1/auth/forgot-password", json={"email": "synthetic@example.test"}
    )
    unknown = await client.post(
        "/api/v1/auth/forgot-password", json={"email": "unknown@example.test"}
    )
    assert known.status_code == unknown.status_code == 200
    assert known.json()["message"] == unknown.json()["message"]


@pytest.mark.integration
@pytest.mark.parametrize("role", list(Role))
async def test_member_mutation_allowed_denied_matrix(
    client, db, two_organizations, role
):
    a, b = two_organizations
    await actor(client, db, a[0], role)
    target_user = User(
        normalized_email=f"{uuid4().hex}@example.test", display_name="Managed member"
    )
    db.add(target_user)
    await db.flush()
    target = OrganizationMember(
        organization_id=a[0].id, user_id=target_user.id, role=Role.DEVELOPER
    )
    db.add(target)
    await db.commit()
    base = f"/api/v1/organizations/{a[0].id}"
    path = f"{base}/members/{target.id}"
    expected = 200 if role in {Role.OWNER, Role.ADMIN} else 403
    assert (await client.patch(path, json={"role": "viewer"})).status_code == expected
    assert (await client.patch(path, json={"role": "admin"})).status_code == (
        200 if role == Role.OWNER else 403
    )
    assert (await client.delete(path)).status_code == expected
    # Organization deletion preserves references and is owner-only.
    assert (await client.delete(base)).status_code == (
        200 if role == Role.OWNER else 403
    )
    assert (await client.get(f"/api/v1/organizations/{b[0].id}")).status_code == 404


@pytest.mark.integration
async def test_onboarding_uses_completed_baseline_and_real_ci(
    client, db, two_organizations
):
    from factories import scan

    from aegis_api.db.enums import Completeness, ScanMode, ScanState
    from aegis_api.db.models import Integration

    a, _ = two_organizations
    await actor(client, db, a[0], Role.ADMIN)
    url = f"/api/v1/organizations/{a[0].id}/onboarding"
    item = scan(*a)
    item.mode = ScanMode.BASELINE
    item.state = ScanState.FAILED
    item.completeness = Completeness.PARTIAL
    db.add(item)
    await db.commit()
    for state in [
        ScanState.FAILED,
        ScanState.CANCELLED,
        ScanState.TIMED_OUT,
        ScanState.COMPLETED,
    ]:
        item.state = state
        await db.commit()
        assert not (await client.get(url)).json()["run_safe_baseline"]
    item.completeness = Completeness.COMPLETE
    await db.commit()
    assert (await client.get(url)).json()["run_safe_baseline"]
    integration = Integration(
        organization_id=a[0].id,
        provider="github",
        external_installation_id=uuid4().hex,
        allowed_repositories=["synthetic/repository"],
        credential_reference="test-only-reference",
        status=RecordState.DEACTIVATED,
    )
    db.add(integration)
    await db.commit()
    assert not (await client.get(url)).json()["configure_ci"]
    integration.status = RecordState.ACTIVE
    await db.commit()
    assert (await client.get(url)).json()["configure_ci"]
