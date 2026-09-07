.PHONY: setup dev down lint typecheck test test-integration test-e2e migrate seed-demo clean-generated check build compose-config
UV ?= uv
PNPM ?= pnpm
COMPOSE ?= docker compose

setup:
	python3 scripts/setup_env.py
	$(PNPM) install --frozen-lockfile
	$(UV) sync --project apps/api --frozen
	$(PNPM) --filter @aegisforge/web exec playwright install chromium

dev:
	$(COMPOSE) up --build -d --wait

down:
	$(COMPOSE) down

lint:
	$(PNPM) exec prettier --check .
	$(PNPM) --filter @aegisforge/web lint
	$(UV) run --project apps/api ruff check apps/api
	$(UV) run --project apps/api ruff format --check apps/api

typecheck:
	$(PNPM) --filter @aegisforge/web typecheck
	$(UV) run --project apps/api mypy --config-file apps/api/pyproject.toml apps/api/src

test:
	$(PNPM) --filter @aegisforge/web test
	$(UV) run --project apps/api pytest -c apps/api/pyproject.toml apps/api/tests -m 'not integration'

test-integration:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.test.yml run --rm --build api

test-e2e:
	$(PNPM) --filter @aegisforge/web test-e2e

migrate:
	$(COMPOSE) run --rm api alembic upgrade head

seed-demo:
	@echo "No demo seed is implemented in Phase 4. Test factories are synthetic; no changes made."

clean-generated:
	python3 scripts/clean_generated.py

check: lint typecheck test schema-check

build:
	$(PNPM) --filter @aegisforge/web build
	$(UV) build --project apps/api

compose-config:
	COMPOSE="$(COMPOSE)" python3 scripts/check_compose.py

.PHONY: schema-docs schema-check
schema-docs:
	$(UV) run --project apps/api python -m aegis_api.schema_docs

schema-check:
	$(UV) run --project apps/api python -m aegis_api.schema_docs --check

.PHONY: test-auth-e2e
test-auth-e2e:
	COMPOSE="$(COMPOSE)" python3 scripts/test_auth_e2e.py
