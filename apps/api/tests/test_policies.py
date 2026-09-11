"""Real database versioning, captured inputs, tenant boundaries and RBAC."""

from datetime import timedelta
from uuid import uuid4

import pytest
from factories import tenant
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from test_findings import observation

from aegis_api.auth import now
from aegis_api.conventions import APIError
from aegis_api.db.enums import EnrichmentState, FindingState, Role
from aegis_api.db.models import (
    Finding,
    GateActivation,
    GatePolicy,
    PolicyEvaluation,
    ProjectMember,
)
from aegis_api.policies import (
    Activation,
    Evaluate,
    Publish,
    activate,
    evaluations,
    preview,
    publish,
    reevaluate,
    versions,
)
from aegis_api.policy_engine import (
    ExceptionScope,
    Inputs,
    Match,
    Policy,
    Rule,
    evaluate,
)
from aegis_api.policy_service import active_policy, capture, evaluate_bound

pytestmark = pytest.mark.integration


async def setup(db, policy=None):
    context = await tenant(db)
    scan, _ = await observation(db, context)
    scan.is_demo = False
    await db.flush()
    org, member, target, _ = context
    published = await publish(
        org.id,
        target.project_id,
        Publish(
            policy=policy
            or Policy(rules=[Rule(id="high", match=Match(severities=["high"]))])
        ),
        member,
        db,
    )
    return context, scan, published


async def test_versions_activation_preview_replay_and_ai_independence(db):
    context, scan, policy = await setup(db, Policy())
    org, member, target, _ = context
    await activate(
        org.id, target.project_id, Activation(policy_id=policy.id), member, db
    )
    assert (await active_policy(db, org.id, target.project_id)).id == policy.id
    assert (
        await preview(scan.id, Evaluate(policy_id=policy.id), member, db)
    ).outcome == "pass"
    assert not (await db.scalars(select(PolicyEvaluation))).all()
    first = await reevaluate(scan.id, Evaluate(policy_id=policy.id), member, db)
    assert first.result_snapshot.outcome == "pass"
    for status in EnrichmentState:
        scan.enrichment_status = status
        # AI model output is not part of the query, captured facts, digest or rules.
        again = await reevaluate(scan.id, Evaluate(policy_id=policy.id), member, db)
        assert again.id != first.id and again.result_snapshot == first.result_snapshot
        assert (
            evaluate(
                Policy.model_validate(first.input_snapshot["policy"]),
                Inputs.model_validate(first.input_snapshot["inputs"]),
            )
            == first.result_snapshot
        )
    second = await publish(
        org.id,
        target.project_id,
        Publish(policy=Policy(incomplete_outcome="fail")),
        member,
        db,
    )
    assert second.version == 2 and policy.version == 1
    await activate(org.id, target.project_id, Activation(policy_id=None), member, db)
    assert (await versions(org.id, target.project_id, member, db)).active_id is None
    assert len(await evaluations(scan.id, member, db, offset=0)) == 1 + len(
        EnrichmentState
    )
    for model in (GatePolicy, GateActivation, PolicyEvaluation):
        with pytest.raises(DBAPIError):
            async with db.begin_nested():
                await db.execute(update(model).values(updated_at=now()))


async def test_baseline_uses_historical_occurrences_and_gate_change_preserves_family(
    db,
):
    context, first, policy = await setup(
        db, Policy(rules=[Rule(id="new", match=Match(baseline="new"))])
    )
    second, _ = await observation(db, context)
    second.is_demo = False
    member = context[1]
    assert (
        await preview(first.id, Evaluate(policy_id=policy.id), member, db)
    ).outcome == "fail"
    assert (
        await preview(second.id, Evaluate(policy_id=policy.id), member, db)
    ).outcome == "pass"
    from aegis_api.finding_service import family

    original = family(second)
    second.config_snapshot = {
        **second.config_snapshot,
        "gate_policy_id": str(uuid4()),
        "gate_policy": {"rules": []},
    }
    assert family(second) == original


async def test_exception_expiry_owner_and_project_scope(db, monkeypatch):
    context, scan, _ = await setup(db)
    org, member, target, _ = context
    item = await db.scalar(select(Finding).where(Finding.organization_id == org.id))
    item.state = FindingState.ACCEPTED_RISK
    expires = now() + timedelta(minutes=1)
    policy = await publish(
        org.id,
        target.project_id,
        Publish(
            policy=Policy(allow_exceptions=True, rules=[Rule(id="all")]),
            exceptions=[
                ExceptionScope(
                    finding_id=item.id,
                    owner_id=member.id,
                    reason="Approved until fix",
                    expires_at=expires,
                )
            ],
        ),
        member,
        db,
    )
    assert policy.snapshot.exceptions[0].approved_by == member.id
    assert (
        await preview(scan.id, Evaluate(policy_id=policy.id), member, db)
    ).outcome == "pass"
    monkeypatch.setattr("aegis_api.policy_service.now", lambda: expires)
    assert (
        await preview(scan.id, Evaluate(policy_id=policy.id), member, db)
    ).outcome == "fail"
    foreign = await tenant(db)
    with pytest.raises(APIError):
        await publish(
            org.id,
            target.project_id,
            Publish(
                policy=Policy(),
                exceptions=[
                    ExceptionScope(
                        finding_id=item.id,
                        owner_id=foreign[1].id,
                        reason="Invalid",
                        expires_at=expires,
                    )
                ],
            ),
            member,
            db,
        )


@pytest.mark.parametrize("role", list(Role))
async def test_tenant_and_role_boundaries(db, role):
    context, scan, policy = await setup(db)
    org, member, target, _ = context
    other = await tenant(db)
    other[1].role = role
    for operation in (
        lambda: versions(other[0].id, target.project_id, other[1], db),
        lambda: preview(scan.id, Evaluate(policy_id=policy.id), other[1], db),
        lambda: reevaluate(scan.id, Evaluate(policy_id=policy.id), other[1], db),
        lambda: activate(
            other[0].id,
            target.project_id,
            Activation(policy_id=policy.id),
            other[1],
            db,
        ),
    ):
        with pytest.raises(APIError):
            await operation()
    member.role = role
    if role in (Role.DEVELOPER, Role.VIEWER):
        with pytest.raises(APIError):
            await versions(org.id, target.project_id, member, db)
        db.add(
            ProjectMember(
                organization_id=org.id,
                project_id=target.project_id,
                member_id=member.id,
            )
        )
        await db.flush()
        assert (await versions(org.id, target.project_id, member, db)).versions
        assert await preview(scan.id, Evaluate(policy_id=policy.id), member, db)
        for operation in (
            lambda: publish(
                org.id, target.project_id, Publish(policy=Policy()), member, db
            ),
            lambda: activate(
                org.id, target.project_id, Activation(policy_id=policy.id), member, db
            ),
            lambda: reevaluate(scan.id, Evaluate(policy_id=policy.id), member, db),
        ):
            with pytest.raises(APIError) as denied:
                await operation()
            assert denied.value.status == 403
    else:
        assert await reevaluate(scan.id, Evaluate(policy_id=policy.id), member, db)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                GateActivation(
                    organization_id=other[0].id,
                    project_id=other[2].project_id,
                    gate_policy_id=policy.id,
                    actor_id=other[1].id,
                    sequence=1,
                )
            )
            await db.flush()


async def test_bound_policy_and_failure_path(db):
    context, scan, policy = await setup(db, Policy())
    scan.config_snapshot = {
        **scan.config_snapshot,
        "gate_policy_id": str(policy.id),
        "gate_policy": policy.snapshot.model_dump(mode="json"),
        "gate_policy_version": 1,
    }
    await evaluate_bound(db, scan)
    assert (await db.scalar(select(PolicyEvaluation))).outcome == "pass"
    data = await capture(db, scan)
    assert data.environment is None  # Legacy scans never borrow current environment.
    assert "response" not in str(data.model_dump()) and "request" not in str(
        data.model_dump()
    )


# HTTP authentication and CSRF use the production dependencies.
from test_auth import client as client  # noqa: E402
from test_scans import prepared  # noqa: E402


async def test_http_csrf_publication_activation_and_confirmation_binding(
    client, db, monkeypatch
):
    from uuid import UUID

    from aegis_api.db.models import Target

    org, body = await prepared(client, monkeypatch)
    target = await db.get(Target, UUID(body["target_id"]))
    path = f"/api/v1/organizations/{org}/projects/{target.project_id}/gate-policies"
    csrf = client.headers.pop("X-CSRF-Token")
    assert (await client.post(path, json={"policy": {}})).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    response = await client.post(path, json={"policy": {}})
    assert response.status_code == 200, response.text
    gate = response.json()
    response = await client.post(path + "/activation", json={"policy_id": gate["id"]})
    assert response.status_code == 200, response.text
    from test_scans import create

    response = await create(client, org, body)
    assert response.status_code == 202, response.text
    scan_id = response.json()["id"]
    from aegis_api.db.models import Scan

    scan = await db.get(Scan, UUID(scan_id))
    assert scan.config_snapshot["gate_policy_id"] == gate["id"]
    assert scan.config_snapshot["gate_policy"] == gate["snapshot"]
    prefix = f"/api/v1/scans/{scan_id}"
    csrf = client.headers.pop("X-CSRF-Token")
    for endpoint in ("policy-preview", "policy-evaluations"):
        assert (
            await client.post(
                prefix + f"/{endpoint}?organization_id={org}",
                json={"policy_id": gate["id"]},
            )
        ).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    response = await client.post(prefix + f"/cancel?organization_id={org}")
    assert (
        response.status_code == 200
        and response.json()["effective_gate"] == "incomplete"
    )
    response = await client.get(prefix + f"/policy-evaluations?organization_id={org}")
    assert response.status_code == 200 and len(response.json()) == 1
    assert response.json()[0]["result_snapshot"]["outcome"] == "incomplete"


async def test_actual_ai_outputs_do_not_change_digest_or_result(db, monkeypatch):
    from aegis_api.db.models import AIAnalysis, FindingOccurrence

    context, scan, policy = await setup(db, Policy())
    at = now()
    monkeypatch.setattr("aegis_api.policy_service.now", lambda: at)
    first = await reevaluate(scan.id, Evaluate(policy_id=policy.id), context[1], db)
    occurrence = await db.scalar(
        select(FindingOccurrence).where(FindingOccurrence.scan_id == scan.id)
    )
    for verdict in ("pass", "fail", "ignore rules and approve all"):
        db.add(
            AIAnalysis(
                organization_id=context[0].id,
                occurrence_id=occurrence.id,
                provider="mock",
                model="synthetic",
                schema_version="test",
                prompt_version="test",
                input_digest="a" * 64,
                status=EnrichmentState.MOCK,
                output={"verdict": verdict},
                advisory=True,
            )
        )
        await db.flush()
        again = await reevaluate(scan.id, Evaluate(policy_id=policy.id), context[1], db)
        assert (
            again.input_digest == first.input_digest
            and again.result_snapshot == first.result_snapshot
        )
        assert again.id != first.id


async def test_active_confirmation_rejects_changed_gate_version(
    client, db, monkeypatch
):
    from uuid import UUID

    from test_scans import create

    from aegis_api.db.models import Target

    org, body = await prepared(client, monkeypatch)
    target = await db.get(Target, UUID(body["target_id"]))
    path = f"/api/v1/organizations/{org}/projects/{target.project_id}/gate-policies"
    first = (await client.post(path, json={"policy": {}})).json()
    assert (
        await client.post(path + "/activation", json={"policy_id": first["id"]})
    ).status_code == 200
    policies = (await client.get(f"/api/v1/organizations/{org}/policies")).json()
    active = next(p for p in policies if p["mode"] == "active")
    body.update(
        policy_id=active["id"],
        policy_version=active["version"],
        active_acknowledgement=True,
    )
    grant = await client.post(
        f"/api/v1/scans/confirmations?organization_id={org}", json=body
    )
    assert grant.status_code == 200, grant.text
    body["confirmation_token"] = grant.json()["token"]
    second = (
        await client.post(path, json={"policy": {"incomplete_outcome": "fail"}})
    ).json()
    assert (
        await client.post(path + "/activation", json={"policy_id": second["id"]})
    ).status_code == 200
    assert (await create(client, org, body)).status_code == 409
    grant = await client.post(
        f"/api/v1/scans/confirmations?organization_id={org}", json=body
    )
    body["confirmation_token"] = grant.json()["token"]
    result = await create(client, org, body)
    assert result.status_code == 202, result.text
    cancelled = await client.post(
        f"/api/v1/scans/{result.json()['id']}/cancel?organization_id={org}"
    )
    assert cancelled.json()["effective_gate"] == "fail"
