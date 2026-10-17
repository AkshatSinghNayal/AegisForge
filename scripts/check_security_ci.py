"""Fail if an external workflow action drifts away from a reviewed commit pin."""

import re
from pathlib import Path

import yaml


def check(root: Path) -> None:
    for path in sorted((root / ".github/workflows").glob("*.yml")):
        workflow = yaml.safe_load(path.read_text())
        for job in workflow.get("jobs", {}).values():
            for step in job.get("steps", []):
                action = step.get("uses")
                if (
                    action
                    and not action.startswith("./")
                    and not re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", action)
                ):
                    raise ValueError(f"Unpinned external action in {path.name}")
    print("Workflow action commit pins verified")


if __name__ == "__main__":
    check(Path(__file__).resolve().parents[1])
