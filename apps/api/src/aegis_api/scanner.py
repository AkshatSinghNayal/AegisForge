"""Provider contract plus a deterministic, network-free mock implementation."""

import time
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from aegis_api.db.enums import ScanState
from aegis_api.settings import WorkerSettings
from aegis_api.zap.contracts import ArtifactReceipt


class StageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    scan_id: UUID
    job_id: UUID
    fence: int
    stage: ScanState
    demo: bool
    execution: SecretStr | None = Field(default=None, repr=False)


class StageResult(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    scan_id: UUID
    job_id: UUID
    fence: int
    stage: ScanState
    status: Literal["ok", "scanner_unavailable", "provider_failed"]
    fixture_version: Literal["mock-v1", "zap-v1"] = "mock-v1"
    artifact: ArtifactReceipt | None = None


def mock_stage(request: StageRequest, config: WorkerSettings) -> StageResult:
    enabled = (
        config.scanner_provider == "mock"
        and request.demo
        and (config.demo_mode or config.profile == "test")
        and config.profile != "prod"
    )
    if enabled:
        time.sleep(config.mock_stage_seconds)
    return StageResult(
        **request.model_dump(exclude={"demo", "execution"}),
        status="ok" if enabled else "scanner_unavailable",
    )


class ScannerProvider(Protocol):
    def execute(self, request: StageRequest) -> StageResult: ...


class MockScannerProvider:
    def __init__(self, config: WorkerSettings):
        self.config = config

    def execute(self, request: StageRequest) -> StageResult:
        return mock_stage(request, self.config)
