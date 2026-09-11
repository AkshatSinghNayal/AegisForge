from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from factories import finding, scan, tenant
from test_auth import client as auth_client
from test_auth import login, register

from aegis_api.analytics import dashboard, window
from aegis_api.conventions import APIError
from aegis_api.db.enums import Completeness, FindingState, Role, ScanState, Severity
from aegis_api.workspace import registry


def test_default_window_and_timezone():
    end = datetime(2026, 9, 11, tzinfo=UTC)
    start, actual_end = window(None, end, "Asia/Kolkata")
    assert actual_end == end and end - start == timedelta(days=30)


@pytest.mark.parametrize(
    "start,end,zone",
    [
        (datetime(2026, 1, 1), datetime(2026, 2, 1, tzinfo=UTC), "UTC"),
        (datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC), "UTC"),
        (datetime(2024, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC), "UTC"),
        (None, None, "not-a-timezone"),
    ],
)
def test_invalid_windows(start, end, zone):
    with pytest.raises(APIError):
        window(start, end, zone)


async def load(db, member, **kwargs):
    return await dashboard(member, db, timezone="Asia/Kolkata", page=1, **kwargs)


@pytest.mark.integration
async def test_empty_aggregates_and_foreign_scope(db):
    context = await tenant(db)
    result = await load(db, context[1])
    metrics = {m.label: m.value for m in result.metrics}
    assert metrics["Completed scans"] == 0
    assert metrics["Policy pass rate"] is None
    assert metrics["Mean time to resolution"] is None
    assert result.severity == [] and result.risk_total == 1
    foreign = await load(db, context[1], target=uuid4())
    assert foreign.risk_total == 0 and foreign.risk == []
    context[1].role = Role.VIEWER
    denied = await load(db, context[1])
    assert denied.risk_total == 0
    with pytest.raises(APIError) as error:
        await registry("audit-log", context[1], db, page=1)
    assert error.value.status == 403


@pytest.mark.integration
async def test_incomplete_exclusion_filters_mttr_and_distribution(db):
    context = await tenant(db)
    foreign = await tenant(db)
    at = datetime.now(UTC) - timedelta(hours=1)
    for state, completeness in [
        (ScanState.COMPLETED, Completeness.COMPLETE),
        (ScanState.FAILED, Completeness.PARTIAL),
        (ScanState.COMPLETED, Completeness.PARTIAL),
    ]:
        item = scan(*context)
        item.state = state
        item.completeness = completeness
        item.is_demo = False
        item.created_at = at
        item.started_at = at
        item.finished_at = at + timedelta(minutes=10)
        db.add(item)
    for target in [context[2], foreign[2]]:
        item = finding(target, timestamp=at)
        item.scanner_severity = Severity.HIGH
        db.add(item)
    resolved = finding(context[2], timestamp=at - timedelta(days=40))
    resolved.state = FindingState.RESOLVED
    resolved.resolved_at = at
    db.add(resolved)
    await db.flush()
    result = await load(
        db, context[1], project=context[2].project_id, target=context[2].id
    )
    metrics = {m.label: m.value for m in result.metrics}
    assert metrics["Completed scans"] == 1 and result.excluded_scans == 2
    assert metrics["Open findings"] == 1 and metrics["New high / critical"] == 1
    assert metrics["Mean time to resolution"] == 960
    assert result.duration[0].value == 10
    assert result.completion[0].value == pytest.approx(100 / 3)
    assert (
        sum(r.value for r in result.severity)
        == sum(r.open_findings for r in result.risk)
        == 1
    )
    assert sum(r.value for r in result.categories) == 1
    assert len(result.activity) == 3
    assert any(a.path.startswith("/app/scans/") for a in result.action_items)
    assert any(a.path.startswith("/app/findings?finding=") for a in result.action_items)
    empty = await load(db, context[1], project=foreign[2].project_id)
    assert empty.risk == [] and empty.activity == [] and empty.severity == []


@pytest.mark.integration
async def test_latest_gate_only_and_invalid_duration(db):
    from aegis_api.db.enums import EnrichmentState, PolicyOutcome
    from aegis_api.db.models import PolicyEvaluation

    context = await tenant(db)
    item = scan(*context)
    item.is_demo = False
    item.state = ScanState.COMPLETED
    item.completeness = Completeness.COMPLETE
    db.add(item)
    await db.flush()
    for i, outcome in enumerate([PolicyOutcome.PASS, PolicyOutcome.FAIL]):
        db.add(
            PolicyEvaluation(
                organization_id=context[0].id,
                scan_id=item.id,
                policy_id=context[3].id,
                input_digest=str(i) * 64,
                evaluation_version="test-v1",
                outcome=outcome,
                reason_codes=[],
                completeness=Completeness.COMPLETE,
                enrichment_status=EnrichmentState.DISABLED,
                scan_state=ScanState.COMPLETED,
                created_at=datetime.now(UTC) + timedelta(seconds=i),
            )
        )
    await db.flush()
    result = await load(db, context[1])
    assert next(m.value for m in result.metrics if m.label == "Policy pass rate") == 0
    assert result.duration == []
    assert result.exclusions[0].value == 1
    assert result.exclusions[1].value == 0


@pytest.mark.integration
async def test_registry_scoping_and_metadata_redaction(db):
    from aegis_api.db.models import APIKey, Integration
    from aegis_api.workspace import deactivate

    context = await tenant(db)
    foreign = await tenant(db)
    for ctx in [context, foreign]:
        db.add(
            Integration(
                organization_id=ctx[0].id,
                provider="test-provider",
                external_installation_id=str(uuid4()),
                allowed_repositories=[],
                credential_reference="MUST-NOT-LEAK",
            )
        )
        db.add(
            APIKey(
                organization_id=ctx[0].id,
                issued_by_id=ctx[1].id,
                project_id=ctx[2].project_id,
                permission_scopes=["scan:read"],
                prefix="safe-prefix",
                key_hash=uuid4().hex * 2,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
    await db.flush()
    integrations = await registry("integrations", context[1], db, page=1)
    keys = await registry("api-keys", context[1], db, page=1)
    assert integrations.total == keys.total == 1
    assert "MUST-NOT-LEAK" not in integrations.model_dump_json()
    assert "key_hash" not in keys.model_dump_json()
    with pytest.raises(APIError) as error:
        await deactivate("api-keys", keys.items[0].id, foreign[1], db)
    assert error.value.status == 404
    await deactivate("api-keys", keys.items[0].id, context[1], db)
    assert (await registry("api-keys", context[1], db, page=1)).items[
        0
    ].status == "revoked"


client = auth_client


@pytest.mark.integration
async def test_http_authentication_validation_and_scope(client):
    path = "/api/v1/analytics/dashboard"
    assert (
        await client.get(path, params={"organization_id": str(uuid4())})
    ).status_code == 401
    await register(client)
    await login(client)
    me = (await client.get("/api/v1/auth/me")).json()
    org = me["organizations"][0]["id"]
    response = await client.get(path, params={"organization_id": org})
    assert response.status_code == 200, response.text
    assert response.json()["risk"] == []
    assert (
        await client.get(path, params={"organization_id": str(uuid4())})
    ).status_code == 404
    for params in [
        {"timezone": "invalid"},
        {"page": 0},
        {"date_from": "2026-09-01T00:00:00"},
    ]:
        assert (
            await client.get(path, params={"organization_id": org, **params})
        ).status_code == 422
    assert (
        await client.get("/api/v1/workspace/api-keys", params={"organization_id": org})
    ).json()["items"] == []


@pytest.mark.integration
async def test_half_open_window_and_local_day_buckets(db):
    context = await tenant(db)
    start = datetime(2026, 3, 8, 0, tzinfo=UTC)
    end = start + timedelta(days=1)
    for at in [start, end]:
        item = scan(*context)
        item.created_at = at
        item.is_demo = False
        item.state = ScanState.COMPLETED
        item.completeness = Completeness.COMPLETE
        item.started_at = at
        item.finished_at = at + timedelta(minutes=1)
        db.add(item)
    await db.flush()
    result = await dashboard(
        context[1],
        db,
        date_from=start,
        date_to=end,
        timezone="America/New_York",
        page=1,
    )
    assert result.metrics[0].value == 1
    assert len(result.activity) == 1
    assert result.completion[0].label == "2026-03-07"
    assert result.duration[0].label == "2026-03-07"


@pytest.mark.integration
async def test_lifecycle_excludes_failed_sources_and_gate_deactivation(db):
    from aegis_api.db.models import FindingReview, GateActivation, GatePolicy

    context = await tenant(db)
    at = datetime.now(UTC) - timedelta(hours=1)
    item = finding(context[2], timestamp=at)
    db.add(item)
    await db.flush()
    for state in [ScanState.COMPLETED, ScanState.FAILED]:
        source = scan(*context)
        source.state = state
        source.completeness = (
            Completeness.COMPLETE
            if state == ScanState.COMPLETED
            else Completeness.PARTIAL
        )
        source.is_demo = False
        db.add(source)
        await db.flush()
        db.add(
            FindingReview(
                organization_id=context[0].id,
                finding_id=item.id,
                scan_id=source.id,
                action="observation",
                previous_state="new",
                state="new",
                created_at=at,
            )
        )
    gate = GatePolicy(
        organization_id=context[0].id,
        project_id=context[2].project_id,
        version=1,
        published_by=context[1].id,
        snapshot={
            "exceptions": [{"finding_id": str(item.id), "expires_at": at.isoformat()}]
        },
    )
    db.add(gate)
    await db.flush()
    db.add(
        GateActivation(
            organization_id=context[0].id,
            project_id=context[2].project_id,
            actor_id=context[1].id,
            gate_policy_id=gate.id,
            sequence=1,
        )
    )
    await db.flush()
    result = await load(db, context[1])
    assert sum(row.value for row in result.lifecycle) == 1
    assert next(m.value for m in result.actions if m.label.startswith("Expired")) == 1
    db.add(
        GateActivation(
            organization_id=context[0].id,
            project_id=context[2].project_id,
            actor_id=context[1].id,
            gate_policy_id=None,
            sequence=2,
        )
    )
    await db.flush()
    result = await load(db, context[1])
    assert next(m.value for m in result.actions if m.label.startswith("Expired")) == 0
    assert not any("expired exception" in row.label for row in result.action_items)


@pytest.mark.integration
@pytest.mark.parametrize("role", [Role.DEVELOPER, Role.VIEWER])
async def test_assigned_project_scope_and_revocation(db, role):
    from aegis_api.db.enums import RecordState
    from aegis_api.db.models import ProjectMember

    context = await tenant(db)
    context[1].role = role
    membership = ProjectMember(
        organization_id=context[0].id,
        project_id=context[2].project_id,
        member_id=context[1].id,
    )
    db.add(membership)
    db.add(finding(context[2], timestamp=datetime.now(UTC)))
    await db.flush()
    assert (await load(db, context[1])).risk_total == 1
    membership.status = RecordState.DEACTIVATED
    await db.flush()
    denied = await load(db, context[1], target=context[2].id)
    assert denied.risk_total == 0 and denied.severity == [] and denied.activity == []
