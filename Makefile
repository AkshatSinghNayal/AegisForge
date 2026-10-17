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
	$(COMPOSE) -p aegisforge up --build -d --wait

down:
	$(COMPOSE) -p aegisforge down

lint:
	$(PNPM) exec prettier --check .
	$(PNPM) --filter @aegisforge/web lint
	$(UV) run --project apps/api ruff check apps/api
	$(UV) run --project apps/api ruff format --check apps/api
	$(UV) run --project apps/api ruff check scripts/setup_local_scanner.py scripts/check_local_scanner.py scripts/test_local_scanner.py infra/local-scanner/server.py
	$(UV) run --project apps/api ruff format --check scripts/setup_local_scanner.py scripts/check_local_scanner.py scripts/test_local_scanner.py infra/local-scanner/server.py

typecheck:
	$(PNPM) --filter @aegisforge/web typecheck
	$(UV) run --project apps/api mypy --config-file apps/api/pyproject.toml apps/api/src

test:
	python3 scripts/test_compose_runner.py
	python3 scripts/test_local_scanner.py
	$(PNPM) --filter @aegisforge/web test
	$(UV) run --project apps/api pytest -c apps/api/pyproject.toml apps/api/tests -m 'not integration'

test-integration:
	$(COMPOSE) -p aegisforge -f docker-compose.yml -f docker-compose.test.yml run --rm --build api

test-e2e:
	$(PNPM) --filter @aegisforge/web test-e2e

migrate:
	$(COMPOSE) -p aegisforge run --rm api alembic upgrade head

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

.PHONY: security-static security-audit test-security
security-static:
	$(UV) run --project apps/api python scripts/check_security_ci.py
	$(UV) run --project apps/api bandit -r apps/api/src scripts/aegisforge_ci.py scripts/aegisforge_ci_local_test.py -ll

security-audit:
	$(PNPM) audit --audit-level low
	@audit_file=$$(mktemp); trap 'rm -f "$$audit_file"' EXIT; \
	$(UV) export --project apps/api --frozen --no-emit-project --no-hashes -o "$$audit_file" && \
	$(UV) run --project apps/api pip-audit --no-deps --disable-pip -r "$$audit_file"

test-security: test test-integration compose-config test-security-browser

.PHONY: test-security-browser
test-security-browser:
	$(PNPM) --filter @aegisforge/web exec playwright test --project production security.spec.ts findings.spec.ts reporting.spec.ts policies.spec.ts github.spec.ts administration.spec.ts
