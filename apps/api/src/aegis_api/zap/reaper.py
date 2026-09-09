"""Independent recovery loop for jobs whose worker was killed."""

import time
from uuid import uuid4

from aegis_api.settings import WorkerSettings
from aegis_api.zap.runtime import DockerRuntime


def main() -> None:
    config = WorkerSettings()
    while True:
        try:
            DockerRuntime(config, uuid4(), lambda: None).reap()
        except Exception:
            # No Docker output (which can contain sensitive metadata) is logged.
            pass
        time.sleep(15)


if __name__ == "__main__":
    main()
