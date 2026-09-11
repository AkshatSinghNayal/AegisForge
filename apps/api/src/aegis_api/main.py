import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from starlette.exceptions import HTTPException
from starlette.middleware.base import RequestResponseEndpoint

from aegis_api.ai_routes import router as ai_router
from aegis_api.analytics import router as analytics_router
from aegis_api.conventions import (
    APIError,
    ErrorResponse,
    api_error_handler,
    error_response,
    http_error_handler,
    validation_error_handler,
)
from aegis_api.dependencies import DependencyProbe, InfrastructureProbe
from aegis_api.findings import router as finding_router
from aegis_api.logging import configure_logging, correlation_id
from aegis_api.settings import Settings, get_settings
from aegis_api.workspace import router as workspace_router


class Health(BaseModel):
    status: Literal["alive", "ready", "unavailable"]


def create_app(
    settings: Settings | None = None, probe: DependencyProbe | None = None
) -> FastAPI:
    from redis.asyncio import Redis

    from aegis_api.auth import router as auth_router
    from aegis_api.configuration import router as configuration_router
    from aegis_api.db.session import database
    from aegis_api.organizations import router as organization_router
    from aegis_api.scan_coordinator import coordinate
    from aegis_api.scans import router as scan_router

    config = settings or get_settings()
    configure_logging(config.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine, app.state.sessions = database(config)
        app.state.redis = Redis.from_url(config.redis_url.get_secret_value())
        app.state.probe = probe if probe is not None else InfrastructureProbe(config)
        coordinator = (
            asyncio.create_task(coordinate(app.state.sessions, config))
            if config.scan_coordinator_enabled
            else None
        )
        try:
            yield
        finally:
            if coordinator:
                coordinator.cancel()
                with suppress(asyncio.CancelledError):
                    await coordinator
            await app.state.probe.close()
            await app.state.redis.aclose()
            await app.state.engine.dispose()

    app = FastAPI(
        title="AegisForge API",
        version="0.6.0",
        lifespan=lifespan,
        docs_url="/api/v1/docs" if config.profile != "prod" else None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json" if config.profile != "prod" else None,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )
    from aegis_api.body_limit import ConfigurationBodyLimit

    app.add_middleware(ConfigurationBodyLimit)
    app.state.config = config
    app.include_router(auth_router)
    app.include_router(organization_router)
    app.include_router(configuration_router)
    app.include_router(scan_router)
    app.include_router(finding_router)
    from aegis_api.policies import router as policy_router

    app.include_router(policy_router)
    app.include_router(ai_router)
    app.include_router(analytics_router)
    app.include_router(workspace_router)
    app.add_exception_handler(APIError, api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, http_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]

    @app.middleware("http")
    async def correlate(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Generate server-owned IDs; do not trust or log incoming header values.
        request_id = str(uuid4())
        token = correlation_id.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            response.headers["Cache-Control"] = "no-store"
            logging.getLogger("aegis.requests").info(
                "",
                extra={
                    "event": "request_complete",
                    "status_code": response.status_code,
                },
            )
            return response
        except Exception:
            logging.getLogger("aegis.requests").error(
                "", extra={"event": "request_failed", "status_code": 500}
            )
            response = error_response(
                500, "internal_error", "Request could not be completed."
            )
            response.headers["X-Request-ID"] = request_id
            response.headers["Cache-Control"] = "no-store"
            return response
        finally:
            correlation_id.reset(token)

    @app.get("/health/live", response_model=Health)
    async def live() -> Health:
        return Health(status="alive")

    @app.get(
        "/health/ready",
        response_model=Health,
        responses={
            200: {"content": {"application/json": {"example": {"status": "ready"}}}},
            503: {
                "model": Health,
                "description": "Dependencies unavailable",
                "content": {"application/json": {"example": {"status": "unavailable"}}},
            },
        },
    )
    async def ready(request: Request, response: Response) -> Health:
        if not await request.app.state.probe.check():
            response.status_code = 503
            return Health(status="unavailable")
        return Health(status="ready")

    return app
