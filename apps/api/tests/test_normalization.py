"""Golden scanner observations, stable identity and conservative masking."""

import copy
import json
from pathlib import Path

import pytest

from aegis_api.db.enums import FindingState
from aegis_api.finding_service import state_for
from aegis_api.normalization import canonical_route, normalize


def golden():
    return json.loads(
        (Path(__file__).parent / "fixtures/zap-normalization-v1.json").read_text()
    )


def test_golden_traceability_and_redaction():
    raw = golden()
    original = copy.deepcopy(raw)
    item = normalize(raw, ["credential-canary"], [])[0]
    assert raw == original
    assert item.severity == "high" and item.confidence == "medium"
    assert (item.cwe, item.wasc, item.owasp) == (89, 19, ["OWASP_2021_A03"])
    assert (
        item.fingerprint
        == "540c9a735f7ec86cb3c5afb9a14402a763a2bad8b158734e83c0098ed132d0e3"
    )
    assert "canary" not in item.model_dump_json()
    assert set(item.sources) == set(type(item).model_fields) - {"sources", "redaction"}
    for paths in item.sources.values():
        assert all(path.startswith(("/alerts/0", "/messages/7/")) for path in paths)
    assert "Authorization: [REDACTED]" in item.request


@pytest.mark.parametrize(
    "field,value",
    [
        ("evidence", "another response"),
        ("messageId", "17"),
        ("url", "https://fixture.example.invalid/search?q=changed#fragment"),
        ("alert", "Changed wording"),
        ("risk", "Low"),
        ("confidence", "Confirmed"),
    ],
)
def test_harmless_evidence_does_not_change_identity(field, value):
    raw = golden()
    before = normalize(raw, [], [])[0]
    raw["alerts"][0][field] = value
    assert normalize(raw, [], [])[0].fingerprint == before.fingerprint


@pytest.mark.parametrize(
    "field,value",
    [
        ("url", "https://fixture.example.invalid/Search?q=x"),
        ("url", "https://fixture.example.invalid/search/?q=x"),
        ("url", "https://fixture.example.invalid/users/123?q=x"),
        ("param", "other"),
        ("param", " q"),
        ("location", "body"),
        ("method", "POST"),
        ("pluginId", "40019"),
    ],
)
def test_distinct_invariants_remain_distinct(field, value):
    raw = golden()
    before = normalize(raw, [], [])[0]
    raw["alerts"][0][field] = value
    assert normalize(raw, [], [])[0].fingerprint != before.fingerprint


def test_route_percent_encoding_and_reserved_slashes():
    assert canonical_route("https://example.invalid/%73earch?q=x") == "/search"
    assert canonical_route("https://example.invalid/a%2fb") == "/a%2Fb"
    assert canonical_route("https://example.invalid/a/b") != "/a%2Fb"


@pytest.mark.parametrize(
    "previous,changed,expected",
    [
        (FindingState.RESOLVED, False, FindingState.REOPENED),
        (FindingState.NEW, True, FindingState.CHANGED),
        (FindingState.NEW, False, FindingState.RECURRING),
        (FindingState.ACCEPTED_RISK, True, FindingState.ACCEPTED_RISK),
        (FindingState.FALSE_POSITIVE, False, FindingState.FALSE_POSITIVE),
    ],
)
def test_review_dispositions_survive_scan(previous, changed, expected):
    assert state_for(previous, changed) == expected
