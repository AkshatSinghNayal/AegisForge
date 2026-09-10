"""Real database authorization, immutable versions and failure isolation."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from factories import tenant
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from test_findings import observation

from aegis_api.ai_routes import Feedback, feedback, generate, versions
from aegis_api.auth import now
from aegis_api.conventions import APIError
from aegis_api.db.enums import Role
from aegis_api.db.models import AIAnalysis, AIFeedback, Finding, PolicyEvaluation

pytestmark = pytest.mark.integration


def request(provider="mock"):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(config=SimpleNamespace(ai_provider=provider))
        )
    )


async def setup(db):
    context = await tenant(db)
    await observation(db, context)
    item = await db.scalar(select(Finding).where(Finding.target_id == context[2].id))
    return context, item


async def test_regeneration_versions_feedback_and_failure_isolation(db, monkeypatch):
    context, item = await setup(db)
    original = (item.scanner_severity, item.state, item.normalized.copy(), item.version)
    first = await generate(item.id, request(), context[1], db)
    assert first["status"] == "mock" and first["advisory"]
    with pytest.raises(APIError) as limited:
        await generate(item.id, request(), context[1], db)
    assert limited.value.status == 429
    monkeypatch.setattr(
        "aegis_api.ai_routes.now", lambda: now() + timedelta(seconds=61)
    )
    second = await generate(item.id, request(), context[1], db)
    assert first["id"] != second["id"] and first["output"] == second["output"]
    saved = await feedback(
        item.id,
        second["id"],
        Feedback(useful=False, note="token=private123"),
        context[1],
        db,
    )
    assert saved["id"]
    rows = await versions(item.id, context[1], db, offset=0)
    assert len(rows) == 2 and any(row["feedback"] for row in rows)
    assert "private123" not in str(rows)
    monkeypatch.setattr(
        "aegis_api.ai_routes.now", lambda: now() + timedelta(seconds=122)
    )
    monkeypatch.setattr(
        "aegis_api.ai_routes.enrich",
        AsyncMock(return_value=(None, "provider_or_validation_exhausted")),
    )
    failed = await generate(item.id, request(), context[1], db)
    assert failed["status"] == "degraded" and failed["output"] is None
    assert len(await versions(item.id, context[1], db, offset=0)) == 3
    assert (
        item.scanner_severity,
        item.state,
        item.normalized,
        item.version,
    ) == original
    assert not (await db.scalars(select(PolicyEvaluation))).all()
    for model in (AIAnalysis, AIFeedback):
        with pytest.raises(DBAPIError):
            async with db.begin_nested():
                await db.execute(update(model).values(updated_at=now()))


async def test_cross_tenant_project_and_role_denial_before_provider(db, monkeypatch):
    context, item = await setup(db)
    other = await tenant(db)
    provider = AsyncMock()
    monkeypatch.setattr("aegis_api.ai_routes.enrich", provider)
    with pytest.raises(APIError) as denied:
        await generate(item.id, request(), other[1], db)
    assert denied.value.status == 404
    with pytest.raises(APIError):
        await versions(item.id, other[1], db, offset=0)
    for role in (Role.VIEWER, Role.DEVELOPER):
        context[1].role = role
        await db.flush()
        with pytest.raises(APIError):
            await generate(item.id, request(), context[1], db)
        with pytest.raises(APIError):
            await feedback(item.id, uuid4(), Feedback(useful=True), context[1], db)
    provider.assert_not_called()


async def test_feedback_cannot_cross_analysis_or_tenant(db):
    context, item = await setup(db)
    first = await generate(item.id, request(), context[1], db)
    other, other_item = await setup(db)
    with pytest.raises(APIError):
        await feedback(other_item.id, first["id"], Feedback(useful=True), other[1], db)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                AIFeedback(
                    organization_id=other[0].id,
                    analysis_id=first["id"],
                    actor_id=other[1].id,
                    useful=True,
                    note="",
                )
            )
            await db.flush()


async def test_disabled_provider_no_fake_analysis(db):
    context, item = await setup(db)
    with pytest.raises(APIError) as error:
        await generate(item.id, request("none"), context[1], db)
    assert error.value.status == 409
    assert not (await db.scalars(select(AIAnalysis))).all()


@pytest.mark.parametrize(
    "provider_failure", ["outage", "invalid", "oversized", "citation"]
)
async def test_actual_retry_pipeline_preserves_scanner_on_failure(
    db, monkeypatch, provider_failure
):
    from aegis_api.ai import MockAIProvider

    context, item = await setup(db)
    before = (item.scanner_severity, item.state, item.version, item.normalized.copy())
    if provider_failure == "outage":
        call = AsyncMock(side_effect=TimeoutError("synthetic private detail"))
    else:
        invalid = {"invalid": "{", "oversized": "x" * 24001, "citation": "{}"}[
            provider_failure
        ]
        if provider_failure == "citation":
            from aegis_api.ai import prepare

            invalid = await MockAIProvider().generate(
                prepare(str(uuid4()), {"rule": "40018"})
            )
        call = AsyncMock(return_value=invalid)
    monkeypatch.setattr(MockAIProvider, "generate", call)
    monkeypatch.setattr("aegis_api.ai.asyncio.sleep", AsyncMock())
    result = await generate(item.id, request(), context[1], db)
    assert result["status"] == "degraded" and result["output"] is None
    assert call.await_count == 3
    assert (item.scanner_severity, item.state, item.version, item.normalized) == before
    assert len(await versions(item.id, context[1], db, offset=0)) == 1
