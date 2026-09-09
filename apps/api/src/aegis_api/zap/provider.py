"""ZAP provider runs only in a worker; scanner observations remain untrusted."""

import json
import re
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict, Field

from aegis_api.db.enums import ScanMode, ScanState
from aegis_api.scanner import StageRequest, StageResult
from aegis_api.settings import WorkerSettings
from aegis_api.target_validation import sanitize_openapi
from aegis_api.zap.artifacts import LocalArtifactStore
from aegis_api.zap.contracts import (
    Alerts,
    Execution,
    Messages,
    OpenApiImport,
    ScannerRules,
)
from aegis_api.zap.gateway import Scope
from aegis_api.zap.runtime import RuntimeFailure


class Runtime(Protocol):
    def resolve(self, host: str, port: int, allow_private: bool) -> list[str]: ...
    def start(self, scope: Scope, api_key: str) -> None: ...
    def call(
        self, component: str, kind: str, operation: str, **params: str
    ) -> dict[str, Any]: ...
    def configure_proxy(self) -> None: ...
    def file(self, path: str, content: str) -> None: ...
    def stats(self) -> dict[str, Any]: ...
    def close(self) -> None: ...


class GatewayStats(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    count: int = Field(ge=1)
    denied: int = Field(ge=0)
    exhausted: bool
    failed: bool


class Interrupted(Exception):
    pass


def context_pattern(origin: str, path: str) -> str:
    # User scope is glob data, never a supplied regular expression.
    return (
        re.escape(origin)
        + re.escape(path).replace(r"\*", ".*").replace(r"\?", ".")
        + r"(?:\?.*)?$"
    )


class ZapScannerProvider:
    def __init__(
        self,
        config: WorkerSettings,
        execution: Execution,
        runtime: Runtime,
        alive: Callable[[], bool],
        emit: Callable[[ScanState], None],
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.config, self.execution, self.runtime = config, execution, runtime
        self.alive, self.emit, self.sleep = alive, emit, sleeper
        self.until = min(execution.deadline, execution.authorized_until)
        self.wall_deadline = time.monotonic() + max(
            0,
            (self.until - datetime.now(UTC)).total_seconds(),
        )

    def check(self) -> None:
        if datetime.now(UTC) >= self.until or time.monotonic() >= self.wall_deadline:
            raise TimeoutError("scanner_deadline")
        if not self.alive():
            raise Interrupted("scanner_cancelled")

    def value(
        self, component: str, kind: str, operation: str, key: str, **params: str
    ) -> str:
        self.check()
        value = self.runtime.call(component, kind, operation, **params)
        if set(value) != {key} or not isinstance(value[key], str):
            raise RuntimeFailure("invalid_scanner_response")
        return str(value[key])

    def action(self, component: str, operation: str, **params: str) -> None:
        if self.value(component, "action", operation, "Result", **params) != "OK":
            raise RuntimeFailure("scanner_action_failed")

    def wait(
        self, component: str, operation: str, key: str, goal: str, **params: str
    ) -> None:
        while True:
            value = self.value(component, "view", operation, key, **params)
            if value == goal:
                return
            if component == "ajaxSpider":
                if value != "running":
                    raise RuntimeFailure("invalid_scanner_response")
            elif not value.isdigit() or (key == "status" and int(value) > 100):
                raise RuntimeFailure("invalid_scanner_response")
            self.sleep(self.config.zap_poll_seconds)

    def execute(self, request: StageRequest) -> StageResult:
        e, policy = self.execution, self.execution.policy
        if (request.scan_id, request.job_id, request.fence) != (
            e.scan_id,
            e.job_id,
            e.fence,
        ):
            raise RuntimeFailure("invalid_execution_binding")
        if request.demo or request.stage != ScanState.VALIDATING_TARGET:
            raise RuntimeFailure("invalid_execution_stage")
        self.check()
        if not e.kind.startswith("openapi") and (
            policy.spider == "none" or policy.max_depth == 0
        ):
            # Never turn a no-crawl policy into traffic or depth zero into ZAP's
            # unlimited-depth sentinel. URL scans require bounded discovery.
            raise RuntimeFailure("incompatible_crawl_policy")
        target = urlsplit(e.target_url)
        origin = f"{target.scheme}://{target.netloc}"
        # Operator allowlist is independent of tenant-controlled declarations.
        if origin not in self.config.zap_allowlist:
            raise RuntimeFailure("target_not_allowlisted")
        addresses = self.runtime.resolve(
            str(target.hostname),
            target.port or (443 if target.scheme == "https" else 80),
            policy.allow_private,
        )
        import ipaddress

        if policy.mode == ScanMode.ACTIVE and (
            not e.active_confirmation_digest
            or not policy.active_warning_acknowledged
            or any(ipaddress.ip_address(ip).is_global for ip in addresses)
        ):
            # Internet active scanning intentionally has no enable switch.
            raise RuntimeFailure("active_not_authorized")
        # Validate/resanitize even persisted documents. External refs never reach ZAP.
        spec = (
            sanitize_openapi(json.dumps(e.spec).encode(), "spec.json")
            if e.spec
            else None
        )
        if e.kind.startswith("openapi") and spec is None:
            raise RuntimeFailure("spec_unavailable")
        headers: dict[str, str] = {}
        if e.credentials:
            if self.config.profile == "prod":
                raise RuntimeFailure("secret_provider_unavailable")
            cipher = Fernet(self.config.zap_secret_key.get_secret_value())
            for credential in e.credentials:
                plaintext = cipher.decrypt(
                    credential.ciphertext.get_secret_value().encode()
                ).decode()
                prefix = f"{e.organization_id}:{credential.id}:"
                if not plaintext.startswith(prefix):
                    raise RuntimeFailure("secret_scope_mismatch")
                value = plaintext[len(prefix) :]
                if any(
                    c in value for c in "\r\n\x00"
                ) or credential.header_name.lower() in {
                    "host",
                    "cookie",
                    "connection",
                    "content-length",
                    "transfer-encoding",
                    "proxy-authorization",
                    "forwarded",
                    "x-forwarded-for",
                }:
                    raise RuntimeFailure("invalid_secret_header")
                headers[credential.header_name] = value
        scope = Scope(
            target_url=e.target_url,
            address=addresses[0],
            require_lease=True,
            includes=e.includes,
            excludes=e.excludes + policy.excluded_paths,
            methods=e.methods,
            max_requests=policy.max_requests,
            rate=policy.rate_limit,
            seconds=max(
                1,
                min(
                    policy.max_duration_seconds,
                    int((self.until - datetime.now(UTC)).total_seconds()),
                ),
            ),
        )
        self.check()
        try:
            self.emit(ScanState.PREPARING_SCANNER)
            self.runtime.start(scope, secrets.token_urlsafe(32))
            for attempt in range(60):
                self.check()
                try:
                    version = self.value("core", "view", "version", "version")
                    break
                except RuntimeFailure:
                    if attempt == 59:
                        raise
                    self.sleep(self.config.zap_poll_seconds)
            if version != "2.17.0":
                raise RuntimeFailure("unexpected_scanner_version")
            self.runtime.configure_proxy()
            self.action("core", "setMode", mode="protect")
            context = self.value(
                "context", "action", "newContext", "contextId", contextName="aegis"
            )
            if not context.isdigit():
                raise RuntimeFailure("invalid_scanner_response")
            for pattern in e.includes:
                self.action(
                    "context",
                    "includeInContext",
                    contextName="aegis",
                    regex=context_pattern(origin, pattern),
                )
            for pattern in scope.excludes:
                self.action(
                    "context",
                    "excludeFromContext",
                    contextName="aegis",
                    regex=context_pattern(origin, pattern),
                )
            self.action(
                "context",
                "setContextInScope",
                contextName="aegis",
                booleanInScope="true",
            )
            for index, (name, value) in enumerate(headers.items()):
                self.action(
                    "replacer",
                    "addRule",
                    description=f"credential-{index}",
                    enabled="true",
                    matchType="REQ_HEADER",
                    matchRegex="false",
                    matchString=name,
                    replacement=value,
                    url=re.escape(origin) + r"/.*",
                )
            self.emit(ScanState.SPIDERING)
            if spec:
                self.runtime.file("/tmp/openapi.json", json.dumps(spec))
                OpenApiImport.model_validate(
                    self.runtime.call(
                        "openapi",
                        "action",
                        "importFile",
                        file="/tmp/openapi.json",
                        target=e.target_url,
                        contextId=context,
                        maxMessages=str(policy.max_requests),
                    )
                )
            else:
                self.action(
                    "spider", "setOptionMaxDepth", Integer=str(policy.max_depth)
                )
                scan = self.value(
                    "spider",
                    "action",
                    "scan",
                    "scan",
                    url=e.target_url,
                    contextName="aegis",
                    recurse="true",
                    subtreeOnly="true",
                )
                if not scan.isdigit():
                    raise RuntimeFailure("invalid_scanner_response")
                self.wait("spider", "status", "status", "100", scanId=scan)
                if policy.spider == "ajax":
                    self.action(
                        "ajaxSpider",
                        "setOptionMaxCrawlDepth",
                        Integer=str(policy.max_depth),
                    )
                    self.action(
                        "ajaxSpider",
                        "scan",
                        url=e.target_url,
                        inScope="true",
                        contextName="aegis",
                        subtreeOnly="true",
                    )
                    self.wait("ajaxSpider", "status", "status", "stopped")
                    observed = self.value(
                        "ajaxSpider", "view", "numberOfResults", "numberOfResults"
                    )
                    if not observed.isdigit() or int(observed) == 0:
                        raise RuntimeFailure("scanner_discovery_failed")
            self.emit(ScanState.PASSIVE_SCANNING)
            self.wait("pscan", "recordsToScan", "recordsToScan", "0")
            if policy.mode == ScanMode.ACTIVE:
                self.check()
                self.emit(ScanState.ACTIVE_SCANNING)
                inventory = ScannerRules.model_validate(
                    self.runtime.call("ascan", "view", "scanners")
                )
                if not set(policy.active_rule_allowlist) <= {
                    r.id for r in inventory.scanners
                }:
                    raise RuntimeFailure("scanner_rule_unavailable")
                self.action("ascan", "disableAllScanners")
                self.action(
                    "ascan",
                    "enableScanners",
                    ids=",".join(policy.active_rule_allowlist),
                )
                scan = self.value(
                    "ascan",
                    "action",
                    "scan",
                    "scan",
                    recurse="true",
                    inScopeOnly="true",
                    contextId=context,
                )
                if not scan.isdigit():
                    raise RuntimeFailure("invalid_scanner_response")
                self.wait("ascan", "status", "status", "100", scanId=scan)
                self.wait("pscan", "recordsToScan", "recordsToScan", "0")
            self.emit(ScanState.COLLECTING_RESULTS)
            alerts: list[dict[str, Any]] = []
            messages: dict[str, Any] = {}
            total_bytes = 0
            for start in range(0, 20001, 500):
                page = Alerts.model_validate(
                    self.runtime.call(
                        "core",
                        "view",
                        "alerts",
                        start=str(start),
                        count="500",
                    )
                )
                if start == 20000 and page.alerts:
                    raise RuntimeFailure("artifact_limit")
                for alert in page.alerts:
                    item = alert.model_dump()
                    total_bytes += len(json.dumps(item))
                    alerts.append(item)
                    if alert.messageId not in messages:
                        message = Messages.model_validate(
                            self.runtime.call(
                                "core",
                                "view",
                                "message",
                                id=alert.messageId,
                            )
                        ).message.model_dump()
                        total_bytes += len(json.dumps(message))
                        messages[alert.messageId] = message
                    if total_bytes > 250000000:
                        raise RuntimeFailure("artifact_limit")
                if len(page.alerts) < 500:
                    break
            stats = GatewayStats.model_validate(self.runtime.stats())
            if stats.exhausted or stats.failed:
                raise RuntimeFailure("incomplete_scan")
            self.check()
            receipt = LocalArtifactStore(
                Path(self.config.zap_artifact_root),
                self.config.zap_artifact_key.get_secret_value(),
            ).export(
                e,
                {
                    "schema": "zap-raw-v1",
                    "scanner_version": version,
                    "alerts": alerts,
                    "messages": messages,
                    "egress": stats.model_dump(),
                },
                list(headers.values()),
                self.config.zap_redaction_patterns,
            )
            return StageResult(
                **request.model_dump(exclude={"demo", "execution"}),
                status="ok",
                fixture_version="zap-v1",
                artifact=receipt,
            )
        finally:
            self.runtime.close()
