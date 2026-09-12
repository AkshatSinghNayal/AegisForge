"""The 200-row selector page is not a limit on reachable authorized records."""

from datetime import UTC, datetime

import pytest
from factories import tenant
from test_auth import actor
from test_auth import client as auth_client

from aegis_api import configuration
from aegis_api.configuration_schemas import PolicyInput
from aegis_api.db.enums import Role
from aegis_api.db.models import Project, ProjectMember, Target
from aegis_api.organizations import resources

client = auth_client


@pytest.mark.integration
async def test_every_selector_reaches_record_201_with_ties_and_tenant_scope(db):
    org, member, first, _ = await tenant(db)
    foreign = await tenant(db)
    at = datetime.now(UTC)
    first.created_at = at
    for n in range(200):
        db.add(
            Target(
                organization_id=org.id,
                project_id=first.project_id,
                canonical_url=f"https://target-{n}.example.invalid",
                kind="web",
                scope_hosts=[f"target-{n}.example.invalid"],
                scope_paths=["/"],
                display_name=f"Synthetic target {n}",
                created_at=at,
            )
        )
        db.add(
            Project(
                organization_id=org.id,
                name=f"Synthetic project {n}",
                created_by_id=member.id,
                created_at=at,
            )
        )
    for n in range(201):
        await configuration.add_policy(
            PolicyInput(name=f"Synthetic policy {n}"), member, db
        )
    await db.flush()
    for kind, listing in [
        ("projects", configuration.projects),
        ("targets", configuration.targets),
    ]:
        pages = [
            await resources(kind, member, db, offset=offset) for offset in (0, 200, 400)
        ]
        assert [len(page) for page in pages] == [200, 1, 0]
        assert len({row.id for page in pages for row in page}) == 201
        full = [await listing(member, db, offset=offset) for offset in (0, 200, 400)]
        assert [len(page) for page in full] == [200, 1, 0]
        assert {row.id for page in full for row in page} == {
            row.id for page in pages for row in page
        }
    assert [
        len(await configuration.policies(member, db, offset=offset))
        for offset in (0, 200, 400)
    ] == [200, 1, 0]
    assert (
        len(
            await resources(
                "targets", member, db, offset=200, project_id=first.project_id
            )
        )
        == 1
    )
    assert (
        await resources(
            "targets", member, db, offset=200, project_id=foreign[2].project_id
        )
        == []
    )
    member.role = Role.VIEWER
    assert await resources("targets", member, db, offset=200) == []
    db.add(
        ProjectMember(
            organization_id=org.id, project_id=first.project_id, member_id=member.id
        )
    )
    await db.flush()
    assert len(await resources("targets", member, db, offset=200)) == 1
    assert len(await configuration.targets(member, db, offset=200)) == 1
    assert await configuration.projects(member, db, offset=200) == []


@pytest.mark.integration
async def test_http_rejects_negative_selector_offsets(client, db):
    context = await tenant(db)
    await actor(client, db, context[0], Role.OWNER)
    base = f"/api/v1/organizations/{context[0].id}"
    for suffix in (
        "resources/projects",
        "resources/targets",
        "projects",
        "targets",
        "policies",
    ):
        assert (await client.get(f"{base}/{suffix}?offset=-1")).status_code == 422
