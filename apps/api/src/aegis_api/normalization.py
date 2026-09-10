"""Pure worker-side ZAP normalization. Raw documents are never mutated."""

import hashlib
import json
import re
from typing import Any, Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from aegis_api.db.enums import Severity

NORMALIZER = "zap-normalizer-v1"
FINGERPRINT = "zap-fingerprint-v1"


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    index: int = Field(ge=0, le=20000)
    rule: str = Field(pattern=r"^\d+$", max_length=64)
    route: str = Field(max_length=2048)
    method: str = Field(pattern=r"^[A-Z]{1,20}$")
    parameter: str = Field(max_length=256)
    location: Literal["query", "header", "body", "cookie", "unknown"]
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    title: str = Field(max_length=300)
    severity: Severity
    confidence: Literal["false_positive", "low", "medium", "high", "confirmed"]
    cwe: int | None
    wasc: int | None
    owasp: list[str] = Field(max_length=100)
    references: list[str] = Field(max_length=100)
    request: str = Field(max_length=8192)
    response: str = Field(max_length=8192)
    sources: dict[str, list[str]]
    redaction: dict[str, str]


def canonical_route(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Invalid alert URL")

    # Decode only unreserved bytes. Encoded slashes, case, IDs and trailing slashes
    # remain distinct. Query values and fragment never identify an endpoint.
    def unreserved(match: re.Match[str]) -> str:
        char = chr(int(match[1], 16))
        return char if re.fullmatch(r"[A-Za-z0-9._~-]", char) else match[0].upper()

    return re.sub(r"%([0-9a-fA-F]{2})", unreserved, parsed.path or "/")


def normalize(
    raw: dict[str, Any], secrets: list[str], patterns: list[str]
) -> list[Observation]:
    from aegis_api.zap.artifacts import redact

    def clean(value: Any, limit: int = 1024) -> str:
        return str(redact(str(value), secrets, patterns))[:limit]

    def number(value: Any) -> int | None:
        return int(value) if str(value).isdigit() and 0 < int(value) < 1000000 else None

    output = []
    for index, alert in enumerate(raw["alerts"]):
        root = f"/alerts/{index}"
        rule = str(int(alert["pluginId"]))
        route = canonical_route(alert["url"])
        parameter = str(alert.get("param", ""))
        location = str(alert.get("location", "unknown")).lower()
        if location not in {"query", "header", "body", "cookie"}:
            location = (
                "query"
                if parameter in dict(parse_qsl(urlsplit(alert["url"]).query))
                else "unknown"
            )
        if location == "header":
            parameter = parameter.strip().lower()
        method = str(alert["method"]).upper()
        # Hash original invariant identifiers before masking them for display.
        fingerprint = digest([FINGERPRINT, rule, route, method, parameter, location])
        severity = {
            "Informational": "informational",
            "Low": "low",
            "Medium": "medium",
            "High": "high",
        }[alert["risk"]]
        confidence = {
            "False Positive": "false_positive",
            "Low": "low",
            "Medium": "medium",
            "High": "high",
            "Confirmed": "confirmed",
        }[alert["confidence"]]
        message_id = str(alert["messageId"])
        message = raw.get("messages", {}).get(message_id, {})

        def excerpt(key: str, message: dict[str, Any] = message) -> str:
            # All header values and bodies are restricted. Keeping header names
            # supplies useful structure without guessing whether a value is secret.
            lines = str(message.get(key, "")).splitlines()[1:65]
            names = [line.split(":", 1)[0] for line in lines if ":" in line]
            return (
                "\n".join(
                    (
                        name
                        if name.lower()
                        in {
                            "authorization",
                            "cookie",
                            "set-cookie",
                            "host",
                            "content-type",
                            "content-length",
                            "cache-control",
                            "server",
                            "accept",
                            "user-agent",
                            "location",
                            "x-frame-options",
                            "content-security-policy",
                        }
                        else "[Header]"
                    )
                    + ": [REDACTED]"
                    for name in names
                )[:5000]
                + "\n[Body withheld]"
            )

        tags = alert.get("tags", {})
        owasp = (
            [clean(k, 120) for k in tags if re.fullmatch(r"OWASP_\d{4}_A\d{1,2}", k)]
            if isinstance(tags, dict)
            else []
        )
        references = []
        for link in str(alert.get("reference", "")).splitlines()[:100]:
            parts = urlsplit(link.strip())
            if (
                parts.scheme == "https"
                and parts.hostname
                and not parts.username
                and not parts.query
                and not parts.fragment
            ):
                references.append(clean(link.strip(), 500))
        values: dict[str, Any] = dict(
            index=index,
            rule=rule,
            route=clean(route, 2048),
            method=method,
            parameter=clean(parameter, 256),
            location=location,
            fingerprint=fingerprint,
            title=clean(alert["alert"], 300),
            severity=severity,
            confidence=confidence,
            cwe=number(alert.get("cweid")),
            wasc=number(alert.get("wascid")),
            owasp=sorted(owasp)[:100],
            references=references,
            request=f"{method} {clean(route, 2048)}\n" + excerpt("requestHeader"),
            response=excerpt("responseHeader"),
        )
        field_sources = {
            "index": [root],
            "rule": [root + "/pluginId"],
            "route": [root + "/url"],
            "method": [root + "/method"],
            "parameter": [root + "/param"],
            "location": [root + "/location", root + "/url", root + "/param"],
            "fingerprint": [
                root + "/" + k
                for k in ("pluginId", "url", "method", "param", "location")
            ],
            "title": [root + "/alert"],
            "severity": [root + "/risk"],
            "confidence": [root + "/confidence"],
            "cwe": [root + "/cweid"],
            "wasc": [root + "/wascid"],
            "owasp": [root + "/tags"],
            "references": [root + "/reference"],
            "request": [
                f"/messages/{message_id}/requestHeader",
                f"/messages/{message_id}/requestBody",
                root + "/url",
            ],
            "response": [
                f"/messages/{message_id}/responseHeader",
                f"/messages/{message_id}/responseBody",
            ],
        }
        output.append(
            Observation(
                **values,
                sources=field_sources,
                redaction={
                    "version": "finding-redaction-v1",
                    "headers": "all values masked",
                    "bodies": "withheld",
                    "query": "values omitted",
                    "bounds": "8192 characters per excerpt",
                },
            )
        )
    return output
