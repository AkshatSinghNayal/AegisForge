"""Real PostgreSQL ingestion, lifecycle and review authorization."""

from datetime import timedelta
from uuid import uuid4

import pytest
from factories import scan as make_scan
from factories import tenant
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_auth import client as auth_client
from test_auth import login, register
from test_normalization import golden
from test_zap_dispatch import receipt

from aegis_api.auth import now
from aegis_api.conventions import APIError
from aegis_api.db.enums import Completeness, FindingState, Role, ScanState
from aegis_api.db.models import (
    Finding,
    FindingOccurrence,
    FindingReview,
    RawScanArtifact,
)
from aegis_api.finding_service import ingest
from aegis_api.findings import Review, detail, review
from aegis_api.normalization import NORMALIZER, normalize

pytestmark = pytest.mark.integration


async def observation(
    db, context, raw=None, state=ScanState.COMPLETED, complete=Completeness.COMPLETE
):
    scan = make_scan(*context)
    scan.state, scan.completeness = state, complete
    scan.created_at = now()
    scan.finished_at = now()
    db.add(scan)
    await db.flush()
    value = receipt(scan).model_copy(
        update={
            "normalizer": NORMALIZER,
            "observations": normalize(raw if raw is not None else golden(), [], []),
        }
    )
    db.add(
        RawScanArtifact(
            **value.model_dump(exclude={"normalizer", "observations"}),
            artifact_kind="zap-raw-v1",
            content_type="application/json",
            restricted_expires_at=now() + timedelta(days=7),
            redacted_expires_at=now() + timedelta(days=90),
        )
    )
    await db.flush()
    await ingest(db, scan, value)
    return scan, value


async def test_lifecycle_failed_partial_never_resolve_and_reopen(db):
    context = await tenant(db)
    first, receipt1 = await observation(db, context)
    item = await db.scalar(select(Finding).where(Finding.target_id == context[2].id))
    assert item.state == FindingState.NEW
    await ingest(db, first, receipt1)
    assert len((await db.scalars(select(FindingOccurrence))).all()) == 1
    second, _ = await observation(db, context)
    assert item.state == FindingState.RECURRING
    assert second.normalization["baseline_scan_id"] == str(first.id)
    empty = {"alerts": []}
    await observation(db, context, empty, ScanState.FAILED, Completeness.PARTIAL)
    await observation(db, context, empty, ScanState.COMPLETED, Completeness.PARTIAL)
    assert item.state == FindingState.RECURRING
    third, _ = await observation(db, context, empty)
    assert item.state == FindingState.RESOLVED
    assert third.normalization["changes"][str(item.id)] == "resolved"
    await observation(db, context)
    assert item.state == FindingState.REOPENED
    changed = golden()
    changed["alerts"][0]["confidence"] = "Confirmed"
    await observation(db, context, changed)
    assert item.state == FindingState.CHANGED


async def test_review_permissions_traceability_and_cross_tenant(db):
    context = await tenant(db)
    foreign = await tenant(db)
    first, _ = await observation(db, context)
    item = await db.scalar(select(Finding).where(Finding.target_id == context[2].id))
    result = await detail(item.id, context[1], db)
    assert result["occurrences"][0]["artifact_id"]
    assert "canary" not in str(result)
    for role in [Role.OWNER, Role.ADMIN, Role.DEVELOPER, Role.VIEWER]:
        foreign[1].role = role
        with pytest.raises(APIError) as failure:
            await detail(item.id, foreign[1], db)
        assert failure.value.status == 404
    context[1].role = Role.VIEWER
    with pytest.raises(APIError):
        await review(
            item.id,
            Review(action="note", note="Review", version=item.version),
            context[1],
            db,
        )
    context[1].role = Role.OWNER
    with pytest.raises(APIError):
        await review(
            item.id,
            Review(
                action="resolve",
                note="Not verified",
                version=item.version,
                verification_scan_id=first.id,
            ),
            context[1],
            db,
        )
    await review(
        item.id,
        Review(
            action="accept_risk",
            note="Time bounded exception reviewed",
            version=item.version,
        ),
        context[1],
        db,
    )
    assert item.state == FindingState.ACCEPTED_RISK
    await observation(db, context)
    assert item.state == FindingState.ACCEPTED_RISK
    await review(
        item.id,
        Review(action="reopen", note="Exception removed", version=item.version),
        context[1],
        db,
    )
    assert item.state == FindingState.REOPENED
    await review(
        item.id,
        Review(
            action="false_positive",
            note="Verified scanner mismatch",
            version=item.version,
        ),
        context[1],
        db,
    )
    assert item.state == FindingState.FALSE_POSITIVE
    final, _ = await observation(db, context, {"alerts": []})
    await review(
        item.id,
        Review(
            action="resolve",
            note="Verified absence",
            version=item.version,
            verification_scan_id=final.id,
        ),
        context[1],
        db,
    )
    assert item.state == FindingState.RESOLVED
    history = await db.scalar(
        select(FindingReview).where(FindingReview.finding_id == item.id)
    )
    with pytest.raises(DBAPIError):
        async with db.begin_nested():
            await db.execute(
                text("UPDATE finding_reviews SET note='tampered' WHERE id=:id"),
                {"id": history.id},
            )


async def test_cross_tenant_occurrence_fk(db):
    context, foreign = await tenant(db), await tenant(db)
    scan, _ = await observation(db, context)
    other, _ = await observation(db, foreign)
    item = await db.scalar(
        select(FindingOccurrence).where(FindingOccurrence.scan_id == scan.id)
    )
    with pytest.raises(DBAPIError):
        async with db.begin_nested():
            db.add(
                FindingOccurrence(
                    organization_id=context[0].id,
                    target_id=context[2].id,
                    finding_id=item.finding_id,
                    scan_id=other.id,
                    artifact_id=item.artifact_id,
                    scanner_rule_id="40018",
                    observed_severity="high",
                    occurrence_hash=uuid4().hex,
                    redacted_evidence_pointer="test",
                    normalization_version=NORMALIZER,
                    coverage_ref="test",
                )
            )
            await db.flush()


async def test_duplicate_observations_use_stable_representative(db):
    import copy

    context = await tenant(db)
    raw = golden()
    second = copy.deepcopy(raw["alerts"][0])
    second["confidence"] = "High"
    raw["alerts"].append(second)
    first, _ = await observation(db, context, raw)
    item = await db.scalar(select(Finding).where(Finding.target_id == context[2].id))
    assert item.scanner_confidence == "high"
    rows = (
        await db.scalars(
            select(FindingOccurrence).where(FindingOccurrence.scan_id == first.id)
        )
    ).all()
    assert len(rows) == 2
    assert item.normalized["provenance"]["occurrence_id"] in {
        str(row.id) for row in rows
    }
    raw["alerts"].reverse()
    await observation(db, context, raw)
    assert item.state == FindingState.RECURRING
    assert item.scanner_confidence == "high"


async def test_partial_evidence_does_not_replace_comparison_baseline(db):
    context = await tenant(db)
    first, _ = await observation(db, context)
    changed = golden()
    changed["alerts"][0]["risk"] = "Low"
    await observation(db, context, changed, ScanState.COMPLETED, Completeness.PARTIAL)
    last, _ = await observation(db, context)
    item = await db.scalar(select(Finding).where(Finding.target_id == context[2].id))
    assert last.normalization["baseline_scan_id"] == str(first.id)
    assert item.state == FindingState.RECURRING


async def test_policy_configuration_change_starts_separate_baseline(db):
    context = await tenant(db)
    first, _ = await observation(db, context)
    from aegis_api.finding_service import family

    second = make_scan(*context)
    second.config_snapshot = {"schema_version": "test-v2"}
    assert family(first) != family(second)


client = auth_client


async def test_http_filters_pagination_review_csrf_and_roles(client, db):
    from aegis_api.db.models import (
        Organization,
        OrganizationMember,
        Project,
        ProjectMember,
        ScanPolicy,
        Target,
    )

    await register(client)
    await login(client)
    org_id = (await client.get("/api/v1/organizations")).json()[0]["id"]
    from uuid import UUID

    org = await db.get(Organization, UUID(org_id))
    member = await db.scalar(
        select(OrganizationMember).where(OrganizationMember.organization_id == org.id)
    )
    synthetic = await tenant(db)
    project = Project(
        organization_id=org.id, name="Finding HTTP fixture", created_by_id=member.id
    )
    db.add(project)
    await db.flush()
    target = Target(
        organization_id=org.id,
        project_id=project.id,
        canonical_url="https://fixture.example.invalid",
        kind="web",
        scope_hosts=["fixture.example.invalid"],
        scope_paths=["/"],
    )
    source = synthetic[3]
    policy = ScanPolicy(
        organization_id=org.id,
        name="HTTP fixture policy",
        version=1,
        mode=source.mode,
        fail_severity=source.fail_severity,
        max_duration_seconds=300,
        max_requests=100,
        max_depth=2,
        require_enrichment=True,
        require_report=True,
        allow_waivers=False,
        required_coverage=["passive"],
        schema_version="test-v1",
        rules_snapshot={"schema_version": "test-v1"},
    )
    db.add_all([target, policy])
    await db.flush()
    scan, _ = await observation(db, (org, member, target, policy))
    await db.commit()
    prefix = f"/api/v1/findings?organization_id={org.id}"
    response = await client.get(
        prefix + "&severity=high&confidence=medium&cwe=89&owasp=OWASP_2021_A03"
        "&route=search&page_size=1&sort=route"
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    item = response.json()["items"][0]
    for query in [
        "severity=low",
        "route=%25",
        "project=" + str(uuid4()),
        "target=" + str(uuid4()),
        "scan=" + str(uuid4()),
        "status=resolved",
        "date_from=2099-01-01T00:00:00",
    ]:
        result = await client.get(prefix + "&" + query)
        assert result.status_code == 200, result.text
        assert result.json()["total"] == 0
    endpoint = f"/api/v1/findings/{item['id']}"
    client.app.state.config = client.app.state.config.model_copy(
        update={"ai_provider": "mock"}
    )
    ai_endpoint = endpoint + f"/analyses?organization_id={org.id}"
    assert (
        await client.post(ai_endpoint, headers={"X-CSRF-Token": ""})
    ).status_code == 403
    generated = await client.post(ai_endpoint)
    assert generated.status_code == 200, generated.text
    assert generated.json()["status"] == "mock"
    assert (await client.get(ai_endpoint)).json()[0]["id"] == generated.json()["id"]
    feedback_endpoint = endpoint + (
        f"/analyses/{generated.json()['id']}/feedback?organization_id={org.id}"
    )
    assert (
        await client.post(
            feedback_endpoint, json={"useful": True}, headers={"X-CSRF-Token": ""}
        )
    ).status_code == 403
    assert (
        await client.post(
            feedback_endpoint, json={"useful": True, "note": "Synthetic review"}
        )
    ).status_code == 200
    assert (
        await client.post(
            feedback_endpoint, json={"useful": True, "unknown": "forbidden"}
        )
    ).status_code == 422

    assert (
        await client.get(endpoint + f"?organization_id={synthetic[0].id}")
    ).status_code == 404
    assert (await client.get(prefix + "&page_size=101")).status_code == 422
    assert (await client.get(prefix + "&scan=" + str(scan.id))).json()["total"] == 1
    for role in [Role.OWNER, Role.ADMIN, Role.DEVELOPER, Role.VIEWER]:
        member.role = role
        if role == Role.VIEWER:
            await db.flush()
            assert (await client.post(ai_endpoint)).status_code == 403
            assert (
                await client.post(feedback_endpoint, json={"useful": False})
            ).status_code == 403
        if role == Role.DEVELOPER:
            db.add(
                ProjectMember(
                    organization_id=org.id, project_id=project.id, member_id=member.id
                )
            )
        await db.commit()
        current = (await client.get(endpoint + f"?organization_id={org.id}")).json()
        body = {
            "action": "note",
            "note": "Reviewed synthetic observation",
            "version": current["finding"]["version"],
        }
        result = await client.post(
            endpoint + f"/review?organization_id={org.id}", json=body
        )
        assert result.status_code == (403 if role == Role.VIEWER else 200), result.text
    member.role = Role.OWNER
    await db.commit()
    del client.headers["X-CSRF-Token"]
    assert (
        await client.post(endpoint + f"/review?organization_id={org.id}", json=body)
    ).status_code == 403


async def test_real_collection_connects_normalization_without_passing_gate(
    client, db, monkeypatch
):
    from test_zap_dispatch import real_job

    from aegis_api.db.enums import EnrichmentState
    from aegis_api.zap_dispatch import collected

    scan, _, _ = await real_job(client, db, monkeypatch)
    value = receipt(scan).model_copy(
        update={"normalizer": NORMALIZER, "observations": normalize(golden(), [], [])}
    )
    await collected(db, scan, value)
    assert scan.state == ScanState.COMPLETED
    assert scan.completeness == Completeness.COMPLETE
    assert scan.enrichment_status == EnrichmentState.PENDING
    assert scan.normalization["version"] == NORMALIZER
    assert await db.scalar(
        select(FindingOccurrence.id).where(FindingOccurrence.scan_id == scan.id)
    )
    response = await client.get(
        f"/api/v1/scans/{scan.id}?organization_id={scan.organization_id}"
    )
    assert response.status_code == 200, response.text
    assert response.json()["effective_gate"] == "fail"
