"""On-demand enrichment; authorization precedes any provider call."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import Select, select

from aegis_api.ai import (
    PROMPT_VERSION,
    SAMPLING,
    SCHEMA_VERSION,
    GeminiAIProvider,
    Guidance,
    MockAIProvider,
    enrich,
    prepare,
    redact_text,
)
from aegis_api.auth import DB, Payload, csrf, now
from aegis_api.conventions import APIError
from aegis_api.db.enums import EnrichmentState
from aegis_api.db.models import AIAnalysis, AIFeedback, AuditLog, FindingOccurrence
from aegis_api.findings import scoped
from aegis_api.normalization import digest
from aegis_api.organizations import Member, require
from aegis_api.settings import Settings

router = APIRouter(prefix="/api/v1/findings", tags=["AI guidance"])


class FeedbackView(BaseModel):
    id: UUID
    useful: bool
    note: str


class AnalysisView(BaseModel):
    id: UUID
    occurrence_id: UUID
    provider: str
    model: str
    schema_version: str
    prompt_version: str
    sampling: dict[str, float | int]
    status: EnrichmentState
    output: Guidance | None
    generated_at: datetime | None
    failure_code: str | None
    advisory: bool
    feedback: list[FeedbackView] = Field(default_factory=list)


def view(row: AIAnalysis) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "occurrence_id": str(row.occurrence_id),
        "provider": row.provider,
        "model": row.model,
        "schema_version": row.schema_version,
        "prompt_version": row.prompt_version,
        "sampling": row.sampling,
        "status": row.status,
        "output": row.output,
        "generated_at": row.generated_at,
        "failure_code": row.failure_code,
        "advisory": row.advisory,
    }


def analysis_query(
    finding_id: UUID, organization_id: UUID
) -> Select[tuple[AIAnalysis]]:
    return (
        select(AIAnalysis)
        .join(
            FindingOccurrence,
            (FindingOccurrence.id == AIAnalysis.occurrence_id)
            & (FindingOccurrence.organization_id == AIAnalysis.organization_id),
        )
        .where(
            AIAnalysis.organization_id == organization_id,
            FindingOccurrence.finding_id == finding_id,
        )
    )


@router.get("/{finding_id}/analyses", response_model=list[AnalysisView])
async def versions(
    finding_id: UUID, member: Member, db: DB, offset: int = Query(default=0, ge=0)
) -> list[dict[str, Any]]:
    await scoped(finding_id, member, db)
    rows = (
        await db.scalars(
            analysis_query(finding_id, member.organization_id)
            .order_by(AIAnalysis.created_at.desc(), AIAnalysis.id)
            .offset(offset)
            .limit(20)
        )
    ).all()
    result = []
    for row in rows:
        feedback = (
            await db.scalars(
                select(AIFeedback)
                .where(
                    AIFeedback.organization_id == member.organization_id,
                    AIFeedback.analysis_id == row.id,
                )
                .order_by(AIFeedback.created_at.desc())
                .limit(100)
            )
        ).all()
        result.append(
            {
                **view(row),
                "feedback": [
                    {"id": str(f.id), "useful": f.useful, "note": f.note}
                    for f in feedback
                ],
            }
        )
    return result


@router.post(
    "/{finding_id}/analyses", dependencies=[Depends(csrf)], response_model=AnalysisView
)
async def generate(
    finding_id: UUID, request: Request, member: Member, db: DB
) -> dict[str, Any]:
    require(member, "findings.write")
    await scoped(finding_id, member, db)
    config: Settings = request.app.state.config
    if config.ai_provider == "none":
        raise APIError(409, "ai_disabled", "AI enrichment is disabled by the operator.")
    recent = await db.scalar(
        analysis_query(finding_id, member.organization_id)
        .where(AIAnalysis.created_at > now() - timedelta(seconds=60))
        .limit(1)
    )
    if recent:
        raise APIError(
            429, "ai_rate_limit", "Wait one minute before requesting another version."
        )
    occurrence = await db.scalar(
        select(FindingOccurrence)
        .where(
            FindingOccurrence.organization_id == member.organization_id,
            FindingOccurrence.finding_id == finding_id,
        )
        .order_by(FindingOccurrence.created_at.desc(), FindingOccurrence.id)
        .limit(1)
    )
    if occurrence is None:
        raise APIError(409, "evidence_required", "No normalized evidence is available.")
    prompt = prepare(str(occurrence.id), occurrence.normalized)
    provider = (
        MockAIProvider()
        if config.ai_provider == "mock"
        else GeminiAIProvider(config.gemini_api_key.get_secret_value(), config.ai_model)
    )
    output, failure = await enrich(provider, prompt, {str(occurrence.id)})
    row = AIAnalysis(
        id=uuid4(),
        organization_id=member.organization_id,
        occurrence_id=occurrence.id,
        provider=provider.name,
        model=provider.model,
        schema_version=SCHEMA_VERSION,
        prompt_version=PROMPT_VERSION,
        input_digest=digest(prompt),
        sampling=SAMPLING,
        output=output.model_dump(mode="json") if output else None,
        status=(
            EnrichmentState.MOCK
            if provider.name == "mock"
            else EnrichmentState.COMPLETE
        )
        if output
        else EnrichmentState.DEGRADED,
        generated_at=now(),
        failure_code=failure,
        advisory=True,
    )
    db.add(row)
    db.add(
        AuditLog(
            organization_id=member.organization_id,
            actor_id=member.id,
            action="ai.generate",
            resource_type="ai_analysis",
            resource_id=row.id,
            changed_fields=["output", "status"],
            request_id=uuid4(),
        )
    )
    await db.commit()
    return view(row)


class Feedback(Payload):
    useful: bool
    note: str = Field(default="", max_length=2000)


@router.post(
    "/{finding_id}/analyses/{analysis_id}/feedback", dependencies=[Depends(csrf)]
)
async def feedback(
    finding_id: UUID, analysis_id: UUID, body: Feedback, member: Member, db: DB
) -> dict[str, str]:
    require(member, "findings.write")
    await scoped(finding_id, member, db)
    row = await db.scalar(
        analysis_query(finding_id, member.organization_id).where(
            AIAnalysis.id == analysis_id
        )
    )
    if row is None:
        raise APIError(404, "not_found", "Analysis not found.")
    item = AIFeedback(
        id=uuid4(),
        organization_id=member.organization_id,
        analysis_id=row.id,
        actor_id=member.id,
        useful=body.useful,
        note=redact_text(body.note, 2000),
    )
    db.add(item)
    db.add(
        AuditLog(
            organization_id=member.organization_id,
            actor_id=member.id,
            action="ai.feedback",
            resource_type="ai_analysis",
            resource_id=row.id,
            changed_fields=["feedback"],
            request_id=uuid4(),
        )
    )
    await db.commit()
    return {"id": str(item.id)}
