"""Immutable, classification-only report snapshots and private object storage."""

import asyncio
import hashlib
import hmac
import io
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from aegis_api.auth import DB, Payload, csrf, now
from aegis_api.conventions import APIError
from aegis_api.db.enums import ReportState, Severity
from aegis_api.db.models import (
    AIAnalysis,
    FindingOccurrence,
    PolicyEvaluation,
    RawScanArtifact,
    Report,
    Scan,
    Target,
)
from aegis_api.organizations import Member, require
from aegis_api.scans import resource
from aegis_api.settings import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])
GENERATOR: Literal["report-v1"] = "report-v1"
NOTICE = (
    "Redacted: credentials, headers, cookies, response bodies and free-form "
    "scanner text are excluded. Evidence references require authorization "
    "in AegisForge."
)


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    finding_id: UUID
    occurrence_id: UUID
    artifact_id: UUID
    severity: Severity
    ai_analysis_ids: list[UUID]
    ai_label: Literal["Advisory AI guidance; not scanner evidence"] = (
        "Advisory AI guidance; not scanner evidence"
    )


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["report-v1"] = GENERATOR
    organization_id: UUID
    scan_id: UUID
    project_id: UUID
    target_id: UUID
    policy_id: UUID
    policy_version: int | None
    evaluation_id: UUID | None
    gate_policy_id: UUID | None = None
    evaluation_version: str | None = None
    evaluation_input_digest: str | None = None
    scanner_versions: list[str]
    scan_state: str
    completeness: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    captured_at: datetime
    severity_summary: dict[Severity, int]
    evidence: list[Evidence]
    policy_result: Literal["pass", "warn", "fail", "incomplete"]
    limitations: list[str]
    redaction_notice: str = NOTICE


class ReportInput(Payload):
    scan_id: UUID
    format: Literal["pdf", "json"]


class ReportView(BaseModel):
    id: UUID
    scan_id: UUID
    format: str
    version: int
    state: ReportState
    checksum: str | None
    generator_version: str
    content_type: str | None
    created_at: datetime
    expires_at: datetime
    failure_code: str | None


def report_view(row: Report) -> ReportView:
    return ReportView(
        id=row.id,
        scan_id=row.scan_id,
        format=row.format,
        version=row.version,
        state=row.state,
        checksum=row.content_hash,
        generator_version=row.generator_version,
        content_type=row.content_type,
        created_at=row.created_at,
        expires_at=row.expires_at,
        failure_code=row.failure_code,
    )


async def capture(db: AsyncSession, scan: Scan) -> Snapshot:
    target = await db.scalar(
        select(Target).where(
            Target.organization_id == scan.organization_id, Target.id == scan.target_id
        )
    )
    assert target
    evaluation = await db.scalar(
        select(PolicyEvaluation)
        .where(
            PolicyEvaluation.organization_id == scan.organization_id,
            PolicyEvaluation.scan_id == scan.id,
            PolicyEvaluation.gate_policy_id.is_not(None),
        )
        .order_by(PolicyEvaluation.created_at.desc(), PolicyEvaluation.id.desc())
        .limit(1)
    )
    occurrences = (
        await db.scalars(
            select(FindingOccurrence)
            .where(
                FindingOccurrence.organization_id == scan.organization_id,
                FindingOccurrence.scan_id == scan.id,
            )
            .order_by(FindingOccurrence.id)
        )
    ).all()
    analyses = (
        await db.execute(
            select(AIAnalysis.occurrence_id, AIAnalysis.id).where(
                AIAnalysis.organization_id == scan.organization_id,
                AIAnalysis.occurrence_id.in_([o.id for o in occurrences]),
            )
        )
    ).all()
    versions = (
        await db.scalars(
            select(RawScanArtifact.scanner_version)
            .where(
                RawScanArtifact.organization_id == scan.organization_id,
                RawScanArtifact.scan_id == scan.id,
            )
            .distinct()
        )
    ).all()
    # Version strings originate from the scanner boundary, never arbitrary URLs/text.
    import re

    safe_versions = [
        v if re.fullmatch(r"[0-9]{1,3}\.[0-9]{1,3}(?:\.[0-9]{1,3})?", v) else "withheld"
        for v in versions
    ]
    evidence = [
        Evidence(
            finding_id=o.finding_id,
            occurrence_id=o.id,
            artifact_id=o.artifact_id,
            severity=o.observed_severity,
            ai_analysis_ids=[a for occurrence, a in analyses if occurrence == o.id],
        )
        for o in occurrences
    ]
    summary = {
        severity: len({e.finding_id for e in evidence if e.severity == severity})
        for severity in Severity
    }
    outcome = evaluation.outcome.value if evaluation else "incomplete"
    if scan.state != "completed" or scan.completeness != "complete" or scan.is_demo:
        outcome = "incomplete"
    return Snapshot(
        organization_id=scan.organization_id,
        scan_id=scan.id,
        project_id=target.project_id,
        target_id=target.id,
        policy_id=scan.policy_id,
        policy_version=scan.config_snapshot.get("policy_version"),
        evaluation_id=evaluation.id if evaluation else None,
        gate_policy_id=evaluation.gate_policy_id if evaluation else None,
        evaluation_version=evaluation.evaluation_version if evaluation else None,
        evaluation_input_digest=evaluation.input_digest if evaluation else None,
        scanner_versions=sorted(safe_versions),
        scan_state=scan.state,
        completeness=scan.completeness,
        created_at=scan.created_at,
        started_at=scan.started_at,
        finished_at=scan.finished_at,
        captured_at=now(),
        severity_summary=summary,
        evidence=evidence,
        policy_result=outcome,
        limitations=[
            "Point-in-time snapshot; absence of findings is not proof of security.",
            "Names, target URLs, free-form evidence and AI prose are withheld; "
            "IDs link to authorized records.",
        ]
        + (["Demo scan; not security evidence."] if scan.is_demo else [])
        + (
            ["Scan is incomplete or not completed; no passing gate is reported."]
            if outcome == "incomplete"
            else []
        ),
    )


def render(snapshot: Snapshot, format: str) -> bytes:
    if format == "json":
        return (snapshot.model_dump_json(indent=2) + "\n").encode()
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    output = io.BytesIO()
    styles = getSampleStyleSheet()
    story = [Paragraph("AegisForge Scan Report", styles["Title"]), Spacer(1, 16)]
    for key, value in snapshot.model_dump(mode="json").items():
        story.append(
            Paragraph(escape(key.replace("_", " ").title()), styles["Heading2"])
        )
        values = value if isinstance(value, list) else [value]
        for item in values:
            text = (
                json.dumps(item, sort_keys=True)
                if isinstance(item, dict)
                else str(item)
            )
            story.append(Paragraph(escape(text), styles["BodyText"]))
            story.append(Spacer(1, 5))
    SimpleDocTemplate(
        output,
        title="AegisForge Scan Report",
        author="AegisForge",
        leftMargin=42,
        rightMargin=42,
        topMargin=42,
        bottomMargin=42,
    ).build(story)
    return output.getvalue()


class ReportStore:
    def __init__(self, config: Settings):
        self.config = config
        if config.profile == "prod" and config.report_storage != "s3":
            raise ValueError("Production reports require S3")

    def path(self, key: str) -> Path:
        root = Path(self.config.report_root).resolve()
        path = (root / key).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError("Invalid object key")
        return path

    def s3(self) -> "S3Client":
        import boto3
        from botocore.config import Config

        return boto3.client(
            "s3",
            config=Config(
                signature_version="s3v4",
                connect_timeout=5,
                read_timeout=10,
                retries={"max_attempts": 2},
            ),
        )

    def write(self, key: str, content: bytes, content_type: str) -> None:
        if self.config.report_storage == "s3":
            if not self.config.report_bucket or not self.config.report_kms_key_id:
                raise ValueError("S3 bucket and KMS key required")
            self.s3().put_object(
                Bucket=self.config.report_bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
                ServerSideEncryption="aws:kms",
                SSEKMSKeyId=self.config.report_kms_key_id,
                IfNoneMatch="*",
            )
        else:
            path = self.path(key)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)

    def delete(self, key: str) -> None:
        if self.config.report_storage == "s3":
            self.s3().delete_object(Bucket=self.config.report_bucket, Key=key)
        else:
            self.path(key).unlink(missing_ok=True)


def signature(
    config: Settings, organization_id: UUID, report_id: UUID, expires: int
) -> str:
    key = config.report_signing_key.get_secret_value()
    if len(key) < 32:
        raise APIError(
            503, "signing_unavailable", "Report signing key is not configured."
        )
    return hmac.new(
        key.encode(),
        f"report-v1:{organization_id}:{report_id}:{expires}".encode(),
        hashlib.sha256,
    ).hexdigest()


async def scoped_report(report_id: UUID, member: Member, db: DB) -> Report:
    row = await db.scalar(
        select(Report).where(
            Report.organization_id == member.organization_id, Report.id == report_id
        )
    )
    if not row:
        raise APIError(404, "not_found", "Report not found.")
    await resource(row.scan_id, member, db)
    return row


@router.post(
    "", response_model=ReportView, status_code=202, dependencies=[Depends(csrf)]
)
async def create(
    body: ReportInput, member: Member, db: DB, request: Request
) -> ReportView:
    require(member, "reports.write")
    scan = await resource(body.scan_id, member, db, True)
    snapshot = await capture(db, scan)
    version = (
        await db.scalar(
            select(func.max(Report.version)).where(
                Report.organization_id == member.organization_id,
                Report.scan_id == scan.id,
            )
        )
        or 0
    ) + 1
    row = Report(
        id=uuid4(),
        organization_id=member.organization_id,
        scan_id=scan.id,
        evaluation_id=snapshot.evaluation_id,
        format=body.format,
        snapshot=snapshot.model_dump(mode="json"),
        version=version,
        generator_version=GENERATOR,
        state=ReportState.PENDING,
        expires_at=now()
        + timedelta(days=request.app.state.config.report_retention_days),
    )
    scan.report_status = ReportState.PENDING
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return report_view(row)


@router.get("", response_model=list[ReportView])
async def listing(
    scan_id: UUID, member: Member, db: DB, offset: int = Query(0, ge=0)
) -> list[ReportView]:
    await resource(scan_id, member, db)
    rows = (
        await db.scalars(
            select(Report)
            .where(
                Report.organization_id == member.organization_id,
                Report.scan_id == scan_id,
            )
            .order_by(Report.version.desc(), Report.id)
            .offset(offset)
            .limit(100)
        )
    ).all()
    return [report_view(r) for r in rows]


@router.get("/{report_id}", response_model=ReportView)
async def detail(report_id: UUID, member: Member, db: DB) -> ReportView:
    return report_view(await scoped_report(report_id, member, db))


class Download(BaseModel):
    url: str
    expires_at: datetime


@router.post(
    "/{report_id}/download", response_model=Download, dependencies=[Depends(csrf)]
)
async def download(
    report_id: UUID, member: Member, db: DB, request: Request
) -> Download:
    row = await scoped_report(report_id, member, db)
    if (
        row.state != ReportState.COMPLETE
        or row.expires_at <= now()
        or not row.object_key
    ):
        raise APIError(409, "report_unavailable", "Report is not ready or has expired.")
    config = request.app.state.config
    seconds = min(
        config.report_url_seconds, int((row.expires_at - now()).total_seconds())
    )
    if seconds < 1:
        raise APIError(410, "report_expired", "Report has expired.")
    expires = int(now().timestamp()) + seconds
    if config.report_storage == "s3":
        url = await asyncio.to_thread(
            ReportStore(config).s3().generate_presigned_url,
            "get_object",
            Params={
                "Bucket": config.report_bucket,
                "Key": row.object_key,
                "ResponseContentDisposition": (
                    f'attachment; filename="aegis-{row.id}.{row.format}"'
                ),
            },
            ExpiresIn=seconds,
        )
    else:
        token = signature(config, row.organization_id, row.id, expires)
        url = (
            f"{config.app_origin}/api/v1/reports/{row.id}/content"
            f"?organization_id={row.organization_id}"
            f"&expires={expires}&signature={token}"
        )
    return Download(
        url=url, expires_at=datetime.fromtimestamp(expires, tz=now().tzinfo)
    )


@router.get("/{report_id}/content", response_class=Response)
async def content(
    report_id: UUID,
    organization_id: UUID,
    expires: int,
    signature: str,
    request: Request,
    db: DB,
) -> Response:
    config = request.app.state.config
    if (
        config.report_storage != "local"
        or expires <= int(now().timestamp())
        or expires > int(now().timestamp()) + config.report_url_seconds
    ):
        raise APIError(403, "download_invalid", "Download link is invalid or expired.")
    from aegis_api.reporting import signature as sign

    if not hmac.compare_digest(
        signature, sign(config, organization_id, report_id, expires)
    ):
        raise APIError(403, "download_invalid", "Download link is invalid or expired.")
    row = await db.scalar(
        select(Report).where(
            Report.organization_id == organization_id, Report.id == report_id
        )
    )
    if (
        not row
        or row.state != ReportState.COMPLETE
        or row.expires_at <= now()
        or not row.object_key
    ):
        raise APIError(404, "not_found", "Report unavailable.")
    data = await asyncio.to_thread(ReportStore(config).path(row.object_key).read_bytes)
    if hashlib.sha256(data).hexdigest() != row.content_hash:
        raise APIError(409, "checksum_mismatch", "Report integrity check failed.")
    return Response(
        data,
        media_type=row.content_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="aegis-{row.id}.{row.format}"'
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )
