"""Pure table-driven rule/operator/outcome and replay invariants."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from aegis_api.policy_engine import (
    ApprovedException,
    Fact,
    Inputs,
    Match,
    Policy,
    Rule,
    evaluate,
)

AT = datetime(2026, 9, 10, tzinfo=UTC)


def fact(**changes):
    return Fact.model_validate(
        dict(
            finding_id=UUID(int=1),
            occurrence_id=UUID(int=2),
            severity="high",
            confidence="high",
            status="new",
            cwe=79,
            owasp=["A03:2021"],
            route="/api/users",
            is_new=True,
        )
        | changes
    )


def inputs(**changes):
    return Inputs.model_validate(
        dict(
            scan_id=UUID(int=3),
            state="completed",
            completeness="complete",
            normalized=True,
            is_demo=False,
            environment="production",
            baseline_scan_id=None,
            evaluated_at=AT,
            findings=[fact()],
        )
        | changes
    )


@pytest.mark.parametrize(
    "condition,expected",
    [
        ({}, "fail"),
        ({"severities": ["critical"]}, "pass"),
        ({"severities": ["high", "critical"]}, "fail"),
        ({"minimum_confidence": "confirmed"}, "pass"),
        ({"minimum_confidence": "high"}, "fail"),
        ({"statuses": ["resolved"]}, "pass"),
        ({"statuses": ["new"]}, "fail"),
        ({"cwes": [89]}, "pass"),
        ({"cwes": [79]}, "fail"),
        ({"owasp": ["A01:2021"]}, "pass"),
        ({"owasp": ["A03:2021"]}, "fail"),
        ({"environments": ["staging"]}, "pass"),
        ({"environments": ["production"]}, "fail"),
        ({"route": "/api"}, "pass"),
        ({"route": "/api/users"}, "fail"),
        ({"route": "/api/", "route_operator": "prefix"}, "fail"),
        ({"route": "/admin", "route_operator": "prefix"}, "pass"),
        ({"baseline": "new"}, "fail"),
        ({"baseline": "existing"}, "pass"),
        ({"severities": ["high"], "cwes": [89]}, "pass"),
    ],
)
def test_rule_operators(condition, expected):
    result = evaluate(
        Policy(rules=[Rule(id="threshold", match=Match(**condition))]), inputs()
    )
    assert result.outcome == expected
    if expected == "fail":
        assert result.matches[0].finding_ids == [UUID(int=1)]
        assert result.matches[0].occurrence_ids == [UUID(int=2)]


@pytest.mark.parametrize(
    "level", ["false_positive", "low", "medium", "high", "confirmed"]
)
def test_confidence_threshold(level):
    policy = Policy(
        rules=[Rule(id="confidence", match=Match(minimum_confidence=level))]
    )
    assert evaluate(policy, inputs(findings=[fact(confidence=level)])).outcome == "fail"


@pytest.mark.parametrize(
    "severity", ["informational", "low", "medium", "high", "critical"]
)
def test_severity_match(severity):
    assert (
        evaluate(
            Policy(rules=[Rule(id="severity", match=Match(severities=[severity]))]),
            inputs(findings=[fact(severity=severity)]),
        ).outcome
        == "fail"
    )


@pytest.mark.parametrize(
    "state",
    [
        "new",
        "recurring",
        "reopened",
        "changed",
        "resolved",
        "accepted_risk",
        "false_positive",
    ],
)
def test_explicit_status_match(state):
    assert (
        evaluate(
            Policy(rules=[Rule(id="state", match=Match(statuses=[state]))]),
            inputs(findings=[fact(status=state)]),
        ).outcome
        == "fail"
    )


@pytest.mark.parametrize(
    "maximum,count,expected",
    [(0, 0, "pass"), (0, 1, "warn"), (1, 1, "pass"), (1, 2, "warn")],
)
def test_counts_and_warning(maximum, count, expected):
    facts = [
        fact(finding_id=UUID(int=i + 10), occurrence_id=UUID(int=i + 100))
        for i in range(count)
    ]
    assert (
        evaluate(
            Policy(rules=[Rule(id="count", max_open=maximum, outcome="warn")]),
            inputs(findings=facts),
        ).outcome
        == expected
    )


def test_counts_deduplicate_findings_and_precedence():
    facts = [fact(), fact(occurrence_id=uuid4())]
    assert (
        evaluate(
            Policy(rules=[Rule(id="count", max_open=1)]), inputs(findings=facts)
        ).outcome
        == "pass"
    )
    result = evaluate(
        Policy(rules=[Rule(id="warn", outcome="warn"), Rule(id="fail")]),
        inputs(findings=facts),
    )
    assert result.outcome == "fail" and len(result.matches) == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "failed"},
        {"state": "cancelled"},
        {"state": "timed_out"},
        {"state": "normalizing"},
        {"completeness": "partial"},
        {"completeness": "unknown"},
        {"completeness": "none"},
        {"normalized": False},
        {"is_demo": True},
    ],
)
@pytest.mark.parametrize("outcome", ["fail", "incomplete"])
def test_incomplete_always_overrides(changes, outcome):
    assert (
        evaluate(Policy(incomplete_outcome=outcome), inputs(**changes)).outcome
        == outcome
    )


@pytest.mark.parametrize(
    "seconds,status,allowed,expected",
    [
        (1, "accepted_risk", True, "pass"),
        (0, "accepted_risk", True, "fail"),
        (-1, "accepted_risk", True, "fail"),
        (1, "new", True, "fail"),
        (1, "accepted_risk", False, "fail"),
    ],
)
def test_expiring_approved_exceptions(seconds, status, allowed, expected):
    exception = ApprovedException(
        finding_id=UUID(int=1),
        owner_id=uuid4(),
        reason="Tracked remediation",
        created_at=AT - timedelta(days=1),
        expires_at=AT + timedelta(seconds=seconds),
        approved_by=uuid4(),
    )
    policy = Policy(
        allow_exceptions=allowed, rules=[Rule(id="high")], exceptions=[exception]
    )
    assert evaluate(policy, inputs(findings=[fact(status=status)])).outcome == expected


def test_baseline_and_replay_are_independent_of_input_order():
    policy = Policy(rules=[Rule(id="new", match=Match(baseline="new"))])
    baseline = inputs(baseline_scan_id=uuid4(), findings=[fact(is_new=False)])
    assert evaluate(policy, baseline).outcome == "pass"
    current = inputs(
        findings=[fact(), fact(finding_id=UUID(int=5), occurrence_id=UUID(int=6))]
    )
    assert evaluate(policy, current) == evaluate(
        Policy.model_validate_json(policy.model_dump_json()),
        Inputs.model_validate_json(current.model_dump_json()),
    )
    assert evaluate(policy, current) == evaluate(
        policy,
        current.model_copy(update={"findings": list(reversed(current.findings))}),
    )


def test_llm_fields_and_executable_expressions_are_not_inputs():
    for extra in ({"ai_verdict": "pass"}, {"expression": "__import__('os')"}):
        with pytest.raises(ValidationError):
            Policy.model_validate(extra)
        with pytest.raises(ValidationError):
            Inputs.model_validate(inputs().model_dump() | extra)
    with pytest.raises(ValidationError):
        Policy(rules=[Rule(id="duplicate"), Rule(id="duplicate")])


def test_unknown_historical_environment_fails_closed_only_when_needed():
    assert (
        evaluate(
            Policy(
                rules=[Rule(id="production", match=Match(environments=["production"]))]
            ),
            inputs(environment=None),
        ).outcome
        == "incomplete"
    )
    assert evaluate(Policy(), inputs(environment=None)).outcome == "pass"
