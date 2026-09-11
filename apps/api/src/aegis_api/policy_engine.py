"""Pure versioned evaluator. No provider, clock or expression execution."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from aegis_api.db.enums import (
    Completeness,
    FindingState,
    PolicyOutcome,
    ScanState,
    Severity,
)

ENGINE = "deterministic-v1"
Confidence = Literal["false_positive", "low", "medium", "high", "confirmed"]
CONFIDENCE = ["false_positive", "low", "medium", "high", "confirmed"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Match(Strict):
    severities: list[Severity] = Field(default_factory=list, max_length=5)
    minimum_confidence: Confidence = "low"
    statuses: list[FindingState] = Field(
        default_factory=lambda: [
            FindingState.NEW,
            FindingState.RECURRING,
            FindingState.REOPENED,
            FindingState.CHANGED,
            FindingState.ACCEPTED_RISK,
        ],
        max_length=7,
    )
    cwes: list[Annotated[int, Field(ge=1, le=999999)]] = Field(
        default_factory=list, max_length=100
    )
    owasp: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=100
    )
    route: str = Field(default="", max_length=2048)
    route_operator: Literal["exact", "prefix"] = "exact"
    environments: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=20
    )
    baseline: Literal["any", "new", "existing"] = "any"


class Rule(Strict):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    match: Match = Field(default_factory=Match)
    max_open: int = Field(default=0, ge=0, le=100000)
    outcome: Literal["warn", "fail"] = "fail"


class ExceptionScope(Strict):
    finding_id: UUID
    owner_id: UUID
    reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ]
    expires_at: AwareDatetime


class ApprovedException(ExceptionScope):
    created_at: AwareDatetime
    approved_by: UUID

    @model_validator(mode="after")
    def lifetime(self) -> "ApprovedException":
        if self.expires_at <= self.created_at:
            raise ValueError("Expiry must follow creation")
        return self


class Policy(Strict):
    schema_version: Literal["gate-v1"] = "gate-v1"
    incomplete_outcome: Literal["incomplete", "fail"] = "incomplete"
    allow_exceptions: bool = False
    rules: list[Rule] = Field(default_factory=list, max_length=100)
    exceptions: list[ApprovedException] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_ids(self) -> "Policy":
        if any(r.id.startswith("system_") for r in self.rules):
            raise ValueError("System rule IDs are reserved")
        if len({r.id for r in self.rules}) != len(self.rules):
            raise ValueError("Rule IDs must be unique")
        if len({e.finding_id for e in self.exceptions}) != len(self.exceptions):
            raise ValueError("Exception finding scopes must be unique")
        return self


class Fact(Strict):
    finding_id: UUID
    occurrence_id: UUID
    severity: Severity
    confidence: Confidence
    status: FindingState
    cwe: int | None
    owasp: list[str]
    route: str
    is_new: bool


class Inputs(Strict):
    scan_id: UUID
    state: ScanState
    completeness: Completeness
    normalized: bool
    is_demo: bool
    environment: str | None
    baseline_scan_id: UUID | None
    evaluated_at: AwareDatetime
    findings: list[Fact]


class MatchedRule(Strict):
    rule_id: str
    outcome: PolicyOutcome
    reason: str
    finding_ids: list[UUID]
    occurrence_ids: list[UUID]


class Result(Strict):
    reason: str = "No policy thresholds exceeded."
    outcome: PolicyOutcome
    matches: list[MatchedRule]
    excluded_finding_ids: list[UUID]


def matches(rule: Match, fact: Fact, inputs: Inputs) -> bool:
    return (
        (not rule.severities or fact.severity in rule.severities)
        and CONFIDENCE.index(fact.confidence)
        >= CONFIDENCE.index(rule.minimum_confidence)
        and (not rule.statuses or fact.status in rule.statuses)
        and (not rule.cwes or fact.cwe in rule.cwes)
        and (not rule.owasp or bool(set(rule.owasp) & set(fact.owasp)))
        and (not rule.environments or inputs.environment in rule.environments)
        and (rule.baseline == "any" or fact.is_new == (rule.baseline == "new"))
        and (
            not rule.route
            or (
                fact.route == rule.route
                if rule.route_operator == "exact"
                else fact.route.startswith(rule.route)
            )
        )
    )


def evaluate(policy: Policy, inputs: Inputs) -> Result:
    if (
        inputs.state
        not in {
            ScanState.COMPLETED,
            ScanState.EVALUATING_POLICY,
            ScanState.GENERATING_REPORT,
        }
        or inputs.completeness != Completeness.COMPLETE
        or not inputs.normalized
        or inputs.is_demo
        or (
            inputs.environment is None
            and any(r.match.environments for r in policy.rules)
        )
    ):
        outcome = PolicyOutcome(policy.incomplete_outcome)
        return Result(
            outcome=outcome,
            reason="Scanner evidence is incomplete or unavailable.",
            matches=[
                MatchedRule(
                    rule_id="system_completeness",
                    outcome=outcome,
                    reason=(
                        "Complete normalized scanner evidence is required; "
                        "demo or unfinished scans cannot pass."
                    ),
                    finding_ids=[],
                    occurrence_ids=[],
                )
            ],
            excluded_finding_ids=[],
        )
    waived = {
        e.finding_id
        for e in policy.exceptions
        if policy.allow_exceptions
        and e.created_at <= inputs.evaluated_at < e.expires_at
    }
    excluded = {
        f.finding_id
        for f in inputs.findings
        if f.status == FindingState.ACCEPTED_RISK and f.finding_id in waived
    }
    output: list[MatchedRule] = []
    for rule in sorted(policy.rules, key=lambda r: r.id):
        contributing = [
            f
            for f in inputs.findings
            if f.finding_id not in excluded and matches(rule.match, f, inputs)
        ]
        ids = sorted({f.finding_id for f in contributing}, key=str)
        if len(ids) > rule.max_open:
            output.append(
                MatchedRule(
                    rule_id=rule.id,
                    outcome=PolicyOutcome(rule.outcome),
                    reason=(
                        f"{len(ids)} matching findings exceed the allowed "
                        f"count of {rule.max_open}."
                    ),
                    finding_ids=ids,
                    occurrence_ids=sorted(
                        {f.occurrence_id for f in contributing}, key=str
                    ),
                )
            )
    outcome = (
        PolicyOutcome.FAIL
        if any(m.outcome == PolicyOutcome.FAIL for m in output)
        else PolicyOutcome.WARN
        if output
        else PolicyOutcome.PASS
    )
    return Result(
        outcome=outcome,
        reason=(
            "One or more policy thresholds exceeded."
            if output
            else "No policy thresholds exceeded."
        ),
        matches=output,
        excluded_finding_ids=sorted(excluded, key=str),
    )
