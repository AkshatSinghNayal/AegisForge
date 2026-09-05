import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel
from starlette.middleware.base import RequestResponseEndpoint

from aegis_api.dependencies import DependencyProbe, InfrastructureProbe
from aegis_api.logging import configure_logging, correlation_id
from aegis_api.settings import Settings, get_settings


class Health(BaseModel):
    status: Literal["alive", "ready", "unavailable"]


def create_app(
    settings: Settings | None = None, probe: DependencyProbe | None = None
) -> FastAPI:
    config = settings or get_settings()
    configure_logging(config.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.probe = probe if probe is not None else InfrastructureProbe(config)
        try:
            yield
        finally:
            await app.state.probe.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

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
            return Response(status_code=500, headers={"X-Request-ID": request_id})
        finally:
            correlation_id.reset(token)

    @app.get("/health/live", response_model=Health)
    async def live() -> Health:
        return Health(status="alive")

    @app.get("/health/ready", response_model=Health)
    async def ready(request: Request, response: Response) -> Health:
        if not await request.app.state.probe.check():
            response.status_code = 503
            return Health(status="unavailable")
        return Health(status="ready")

    return app
