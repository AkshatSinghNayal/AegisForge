"""Remove only reproducible outputs; retain dependencies, .env and data volumes."""
import shutil
from pathlib import Path

for name in ("apps/web/dist", "apps/web/test-results", "apps/web/playwright-report", "apps/api/dist", "apps/api/.pytest_cache", "apps/api/.mypy_cache", "apps/api/.ruff_cache"):
    path = Path(name)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
        print(f"Removed {name}")
