# Phase 10 commit inventory

This commit records the verified working state through Phase 10, including the previously uncommitted Phase 9 normalization/findings foundation and Phase 10 strict-review corrections. Its parent is `ac06859` (Phase 8). It does not claim a separate historical Phase 9 commit.

Git writes use the explicitly authorized escalation path, without ownership or permission changes. Local ignored environment files, credentials, build outputs, caches and runtime data are excluded. Live Gemini verification remains blocked on missing configured credentials.

The following 49 files are added or modified; this inventory includes itself.

- `.env.example`
- `README.md`
- `apps/api/migrations/versions/0007_finding_normalization.py`
- `apps/api/migrations/versions/0008_ai_guidance.py`
- `apps/api/pyproject.toml`
- `apps/api/src/aegis_api/ai.py`
- `apps/api/src/aegis_api/ai_routes.py`
- `apps/api/src/aegis_api/db/enums.py`
- `apps/api/src/aegis_api/db/models.py`
- `apps/api/src/aegis_api/finding_service.py`
- `apps/api/src/aegis_api/findings.py`
- `apps/api/src/aegis_api/main.py`
- `apps/api/src/aegis_api/normalization.py`
- `apps/api/src/aegis_api/scan_lifecycle.py`
- `apps/api/src/aegis_api/schema_docs.py`
- `apps/api/src/aegis_api/settings.py`
- `apps/api/src/aegis_api/zap/artifacts.py`
- `apps/api/src/aegis_api/zap/contracts.py`
- `apps/api/src/aegis_api/zap_dispatch.py`
- `apps/api/tests/fixtures/zap-normalization-v1.json`
- `apps/api/tests/test_ai.py`
- `apps/api/tests/test_ai_routes.py`
- `apps/api/tests/test_conventions.py`
- `apps/api/tests/test_database.py`
- `apps/api/tests/test_findings.py`
- `apps/api/tests/test_normalization.py`
- `apps/api/uv.lock`
- `apps/web/e2e/findings.spec.ts`
- `apps/web/playwright.config.ts`
- `apps/web/src/product/AIGuidance.test.tsx`
- `apps/web/src/product/AIGuidance.tsx`
- `apps/web/src/product/Findings.tsx`
- `apps/web/src/product/Workspace.tsx`
- `apps/web/src/product/product.css`
- `docker-compose.yml`
- `docs/AI_GUIDANCE.md`
- `docs/BUILD_PLAN.md`
- `docs/DECISIONS.md`
- `docs/FINDING_NORMALIZATION.md`
- `docs/PHASE10_COMMIT_MANIFEST.md`
- `docs/PHASE10_TEST_REPORT.md`
- `docs/PHASE9_TEST_REPORT.md`
- `docs/PHASE_STATUS.md`
- `docs/TEST_MATRIX.md`
- `docs/TEST_REPORT.md`
- `docs/generated/conventions.schema.json`
- `docs/generated/database-schema.md`
- `docs/generated/openapi.json`
- `docs/security/THREAT_MODEL.md`
