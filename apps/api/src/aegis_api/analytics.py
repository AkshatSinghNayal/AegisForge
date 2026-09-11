"""Read-only analytics: bounded responses, SQL aggregation, tenant/project scoping."""

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import text

from aegis_api.auth import DB
from aegis_api.conventions import APIError
from aegis_api.organizations import Member, project_ids

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


class Metric(BaseModel):
    label: str
    value: float | None
    unit: str = "count"


class Series(BaseModel):
    label: str
    value: float


class Risk(BaseModel):
    project_id: UUID
    target_id: UUID
    project: str
    target: str
    open_findings: int
    high_critical: int


class Activity(BaseModel):
    id: UUID
    target_id: UUID
    state: str
    completeness: str
    created_at: datetime


class ActionItem(BaseModel):
    label: str
    path: str


class Dashboard(BaseModel):
    generated_at: datetime
    date_from: datetime
    date_to: datetime
    timezone: str
    excluded_scans: int
    metrics: list[Metric]
    severity: list[Series]
    categories: list[Series]
    owasp: list[Series]
    exclusions: list[Metric]
    lifecycle: list[Series]
    duration: list[Series]
    completion: list[Series]
    risk: list[Risk]
    risk_total: int
    activity: list[Activity]
    actions: list[Metric]
    action_items: list[ActionItem]


def window(
    start: datetime | None, end: datetime | None, timezone: str
) -> tuple[datetime, datetime]:
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise APIError(422, "invalid_timezone", "Select an IANA timezone.") from exc
    end = end or datetime.now(UTC)
    start = start or end - timedelta(days=30)
    if (
        start.tzinfo is None
        or end.tzinfo is None
        or start >= end
        or end - start > timedelta(days=366)
    ):
        raise APIError(
            422, "invalid_window", "Use aware dates spanning at most 366 days."
        )
    return start, end


# Aggregates share scoped CTEs. Evidence/configuration is never selected.
SCOPE = """
WITH targets_scope AS (
 SELECT t.id, t.project_id, t.display_name, p.name AS project_name FROM
targets t
 JOIN projects p ON p.id=t.project_id AND p.organization_id=t.organization_id
 WHERE t.organization_id=:org AND t.project_id=ANY(CAST(:projects AS uuid[]))
 AND (CAST(:project AS uuid) IS NULL OR t.project_id=CAST(:project AS uuid))
 AND (CAST(:target AS uuid) IS NULL OR t.id=CAST(:target AS uuid))
), scans_scope AS (
 SELECT
s.id,s.target_id,s.state,s.completeness,s.created_at,s.started_at,s.finished_at
 FROM scans s JOIN targets_scope t ON t.id=s.target_id
 WHERE s.organization_id=:org AND s.created_at>=:start AND s.created_at<:end
 AND NOT s.is_demo
), complete_scans AS (
 SELECT * FROM scans_scope WHERE state='completed' AND completeness='complete'
), all_findings AS (
 SELECT f.id,f.target_id,f.state,f.scanner_severity,f.cwe,f.first_seen_at,
 f.last_seen_at,f.resolved_at,f.normalized->'owasp' AS owasp
 FROM findings f JOIN targets_scope t ON t.id=f.target_id
 WHERE f.organization_id=:org
), findings_scope AS (
 SELECT * FROM all_findings WHERE last_seen_at>=:start AND last_seen_at<:end
), open_findings AS (
 SELECT * FROM findings_scope WHERE state IN
('new','recurring','reopened','changed')
), latest_evaluations AS (
 SELECT DISTINCT ON (e.scan_id) e.scan_id,e.outcome FROM policy_evaluations e
 JOIN complete_scans s ON s.id=e.scan_id WHERE e.organization_id=:org
 ORDER BY e.scan_id,e.created_at DESC,e.id DESC
)"""


@router.get("/dashboard", response_model=Dashboard)
async def dashboard(
    member: Member,
    db: DB,
    project: UUID | None = None,
    target: UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    timezone: str = Query(default="UTC", max_length=100),
    page: int = Query(default=1, ge=1, le=100000),
) -> Dashboard:
    start, end = window(date_from, date_to, timezone)
    ids = await project_ids(member, db)
    params = dict(
        org=member.organization_id,
        projects=ids,
        project=project,
        target=target,
        start=start,
        end=end,
        timezone=timezone,
        offset=(page - 1) * 50,
    )
    queries = {
        "totals": """
SELECT (SELECT count(*) FROM complete_scans) AS completed,
 (SELECT count(*) FROM scans_scope)-(SELECT count(*) FROM complete_scans) AS
excluded,
 (SELECT count(*) FROM open_findings) AS opened,
 (SELECT count(*) FROM all_findings WHERE first_seen_at>=:start AND
first_seen_at<:end
 AND scanner_severity IN ('high','critical')) AS new_high,
 (SELECT count(DISTINCT target_id) FROM complete_scans) AS recent_targets,
 (SELECT 100.0*count(*) FILTER (WHERE outcome='pass')/NULLIF(count(*),0)
 FROM latest_evaluations WHERE outcome IN ('pass','warn','fail')) AS
pass_rate,
 (SELECT avg(extract(epoch FROM (resolved_at-first_seen_at)))/3600
 FROM all_findings WHERE state='resolved' AND resolved_at>=first_seen_at
 AND resolved_at>=:start AND resolved_at<:end) AS mttr,
 (SELECT count(*) FROM scans_scope WHERE state IN ('failed','timed_out')) AS
failed,
 (SELECT count(*) FROM targets_scope t WHERE NOT EXISTS
 (SELECT 1 FROM scans s WHERE s.organization_id=:org AND s.target_id=t.id
 AND s.state='completed' AND s.completeness='complete' AND NOT s.is_demo
 AND s.finished_at>=:end-interval '30 days' AND s.finished_at<:end)) AS
overdue,
 (SELECT count(*) FROM open_findings WHERE scanner_severity IN
('high','critical')) AS high,
 (SELECT count(*) FROM (
 SELECT DISTINCT (exception->>'finding_id') FROM gate_activations a
 JOIN gate_policies g ON g.id=a.gate_policy_id AND
g.organization_id=a.organization_id
 CROSS JOIN LATERAL
jsonb_array_elements(COALESCE(g.snapshot->'exceptions','[]'::jsonb)) exception
 JOIN all_findings f ON f.id::text=exception->>'finding_id'
 WHERE a.organization_id=:org AND g.project_id IN (SELECT project_id FROM
targets_scope)
 AND a.sequence=(SELECT max(a2.sequence) FROM gate_activations a2
 WHERE a2.organization_id=:org AND a2.project_id=a.project_id)
 AND (exception->>'expires_at')::timestamptz<:end
 ) expired) AS expired,
 (SELECT count(*) FROM complete_scans WHERE started_at IS NULL
 OR finished_at IS NULL OR finished_at<started_at) AS invalid_duration,
 (SELECT count(*) FROM complete_scans)-(SELECT count(*) FROM latest_evaluations
 WHERE outcome IN ('pass','warn','fail')) AS no_gate
""",
        "severity": """
SELECT scanner_severity AS label,count(*) AS value FROM open_findings GROUP BY
1 ORDER BY 1
""",
        "categories": """
SELECT COALESCE('CWE-'||cwe::text,'Unclassified') AS label,count(*) AS value
FROM open_findings GROUP BY 1 ORDER BY value DESC,label LIMIT 30
""",
        "owasp": """
SELECT category AS label,count(DISTINCT f.id) AS value FROM open_findings f
CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(f.owasp,'[]'::jsonb)) category
GROUP BY category ORDER BY value DESC,category LIMIT 30
""",
        "lifecycle": """
SELECT to_char(date_trunc('day',r.created_at AT TIME ZONE
:timezone),'YYYY-MM-DD')||' · '||r.state AS label,count(DISTINCT
(r.finding_id,r.scan_id)) AS value FROM finding_reviews r JOIN all_findings f
ON f.id=r.finding_id JOIN scans s ON s.id=r.scan_id AND
s.organization_id=r.organization_id WHERE r.organization_id=:org AND
r.created_at>=:start AND r.created_at<:end AND r.state IN
('new','recurring','resolved') AND s.state='completed' AND
s.completeness='complete' AND NOT s.is_demo GROUP BY 1 ORDER BY 1
""",
        "duration": """
SELECT to_char(date_trunc('day',finished_at AT TIME ZONE
:timezone),'YYYY-MM-DD') AS label,avg(extract(epoch FROM
(finished_at-started_at)))/60 AS value FROM complete_scans WHERE
finished_at>=started_at GROUP BY 1 ORDER BY 1
""",
        "completion": """
SELECT to_char(date_trunc('day',created_at AT TIME ZONE
:timezone),'YYYY-MM-DD') AS label,100.0*count(*) FILTER (WHERE
state='completed' AND completeness='complete')/count(*) AS value FROM
scans_scope GROUP BY 1 ORDER BY 1
""",
        "risk_rows": """
SELECT t.project_id,t.id AS target_id,t.project_name AS project,t.display_name
AS target,count(f.id) AS open_findings,count(f.id) FILTER (WHERE
f.scanner_severity IN ('high','critical')) AS high_critical FROM targets_scope
t LEFT JOIN open_findings f ON f.target_id=t.id GROUP BY
t.project_id,t.id,t.project_name,t.display_name ORDER BY high_critical
DESC,open_findings DESC,t.id LIMIT 50 OFFSET :offset
""",
        "total": """
SELECT count(*) FROM targets_scope
""",
        "activity_rows": """
SELECT id,target_id,state,completeness,created_at FROM scans_scope ORDER BY
created_at DESC,id DESC LIMIT 15
""",
    }
    queries["action_items"] = """
(SELECT 'Review '||state::text||' scan '||left(id::text,8) AS label,
'/app/scans/'||id::text AS path FROM scans_scope
WHERE state IN ('failed','timed_out') ORDER BY created_at DESC,id LIMIT 10)
UNION ALL
(SELECT 'Scan overdue target: '||display_name AS label,
'/app/targets/'||t.id::text AS path FROM targets_scope t WHERE NOT EXISTS
(SELECT 1 FROM scans s WHERE s.organization_id=:org AND s.target_id=t.id
AND s.state='completed' AND s.completeness='complete' AND NOT s.is_demo
AND s.finished_at>=:end-interval '30 days' AND s.finished_at<:end)
ORDER BY t.id LIMIT 10)
UNION ALL
(SELECT 'Review '||scanner_severity::text||' finding '||left(id::text,8) AS label,
'/app/findings?finding='||id::text AS path FROM open_findings
WHERE scanner_severity IN ('high','critical') ORDER BY id LIMIT 10)
UNION ALL
(SELECT DISTINCT 'Review expired exception '||left(f.id::text,8) AS label,
'/app/gates?project='||g.project_id::text AS path FROM gate_activations a
JOIN gate_policies g ON g.id=a.gate_policy_id
AND g.organization_id=a.organization_id
CROSS JOIN LATERAL
jsonb_array_elements(COALESCE(g.snapshot->'exceptions','[]'::jsonb)) exception
JOIN all_findings f ON f.id::text=exception->>'finding_id'
WHERE a.organization_id=:org
AND g.project_id IN (SELECT project_id FROM targets_scope)
AND a.sequence=(SELECT max(a2.sequence) FROM gate_activations a2
WHERE a2.organization_id=:org AND a2.project_id=a.project_id)
AND (exception->>'expires_at')::timestamptz<:end ORDER BY label,path LIMIT 10)
"""
    # One PostgreSQL statement gives every panel the same MVCC snapshot.
    parts = []
    for name, sql in queries.items():
        if name in {"totals", "total"}:
            value = f"(SELECT to_jsonb(row) FROM ({sql}) row)"
        else:
            value = f"COALESCE((SELECT jsonb_agg(row) FROM ({sql}) row),'[]'::jsonb)"
        parts.append(f"'{name}',{value}")
    result = await db.scalar(
        text(SCOPE + " SELECT jsonb_build_object(" + ",".join(parts) + ")"), params
    )
    assert isinstance(result, dict)
    totals = result["totals"]
    severity, categories, owasp, lifecycle, duration, completion = (
        [Series.model_validate(row) for row in result[key]]
        for key in [
            "severity",
            "categories",
            "owasp",
            "lifecycle",
            "duration",
            "completion",
        ]
    )
    risk = [Risk.model_validate(row) for row in result["risk_rows"]]
    total = result["total"]["count"]
    activity_rows = result["activity_rows"]
    return Dashboard(
        generated_at=datetime.now(UTC),
        date_from=start,
        date_to=end,
        timezone=timezone,
        excluded_scans=int(totals["excluded"]),
        metrics=[
            Metric(label=label, value=totals[key], unit=unit)
            for label, key, unit in [
                ("Completed scans", "completed", "count"),
                ("Open findings", "opened", "count"),
                ("New high / critical", "new_high", "count"),
                ("Targets recently scanned", "recent_targets", "count"),
                ("Policy pass rate", "pass_rate", "%"),
                ("Mean time to resolution", "mttr", "hours"),
            ]
        ],
        severity=severity,
        categories=categories,
        owasp=owasp,
        exclusions=[
            Metric(
                label="Complete scans without valid duration",
                value=totals["invalid_duration"],
            ),
            Metric(
                label="Complete scans without a conclusive gate",
                value=totals["no_gate"],
            ),
        ],
        lifecycle=lifecycle,
        duration=duration,
        completion=completion,
        risk=risk,
        risk_total=int(total or 0),
        activity=[Activity.model_validate(dict(r)) for r in activity_rows],
        action_items=[ActionItem.model_validate(row) for row in result["action_items"]],
        actions=[
            Metric(label=label, value=totals[key])
            for label, key in [
                ("Failed or timed-out scans", "failed"),
                ("Targets overdue for a complete scan", "overdue"),
                ("Unresolved high / critical findings", "high"),
                ("Expired exceptions in active gates", "expired"),
            ]
        ],
    )
