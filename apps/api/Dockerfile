FROM ghcr.io/astral-sh/uv:0.12.10 AS uv
FROM python:3.12.14-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/api/src ./src
COPY apps/api/alembic.ini ./alembic.ini
COPY apps/api/migrations ./migrations
RUN uv sync --frozen --no-dev && useradd --uid 10001 --create-home aegis && mkdir -p /var/lib/aegis/reports && chown aegis:aegis /var/lib/aegis/reports
USER aegis
EXPOSE 8000
CMD ["uvicorn", "aegis_api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
