"""Prepare local scanner images/settings; never scan or register a target."""

import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOCKET = Path(f"/run/user/{os.getuid()}/docker.sock")


def command(*args, capture=False):
    return subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=capture)


def main():
    if os.getuid() == 0:
        raise SystemExit("Run as the local desktop user, not sudo.")
    if not SOCKET.exists() or not stat.S_ISSOCK(SOCKET.stat().st_mode):
        raise SystemExit("Dedicated rootless daemon socket is missing.")
    info = json.loads(
        command(
            "docker",
            "--context",
            "rootless",
            "info",
            "--format",
            "{{json .}}",
            capture=True,
        ).stdout
    )
    if "name=rootless" not in info["SecurityOptions"]:
        raise SystemExit("Scanner daemon must be rootless.")
    if (
        not info.get("CPUCfsQuota")
        or not info.get("MemoryLimit")
        or not info.get("PidsLimit")
    ):
        raise SystemExit(
            "Required rootless CPU/memory/PID limits unavailable. Follow docs/LOCAL_SCANNER.md before continuing."
        )
    endpoint = command(
        "docker",
        "context",
        "inspect",
        "rootless",
        "--format",
        "{{.Endpoints.docker.Host}}",
        capture=True,
    ).stdout.strip()
    if endpoint != f"unix://{SOCKET}":
        raise SystemExit("Rootless context does not match the local socket.")
    env = ROOT / ".env"
    if not env.exists():
        raise SystemExit("Run make setup first.")
    lines = env.read_text().splitlines()
    if any(
        line.startswith("AEGIS_PROFILE=")
        and line.split("=", 1)[1].strip().strip("\"'") != "dev"
        for line in lines
    ):
        raise SystemExit("This setup requires the development profile.")
    if not (ROOT / "apps/web/dist/index.html").is_file():
        raise SystemExit(
            "Build the web application first: pnpm --filter @aegisforge/web build"
        )
    bridge = ROOT / ".local-scanner/bridge"
    bridge.mkdir(parents=True, exist_ok=True, mode=0o700)
    bridge.chmod(0o700)
    values = {
        "AEGIS_SCANNER_SOCKET": str(SOCKET),
        "AEGIS_SCANNER_SOCKET_GID": str(SOCKET.stat().st_gid),
        "AEGIS_LOCAL_UID": str(os.getuid()),
        "AEGIS_LOCAL_GID": str(os.getgid()),
        "AEGIS_ZAP_ALLOWLIST": '["http://aegis-local-target:8080"]',
        "AEGIS_ZAP_EGRESS_NETWORK": "aegis-local-scan-target",
    }
    for key, value in values.items():
        lines = [line for line in lines if line.split("=", 1)[0].strip() != key]
        lines.append(f"{key}={value}")
    env.write_text("\n".join(lines) + "\n")
    env.chmod(0o600)
    command(str(ROOT / "apps/api/.venv/bin/python"), "scripts/configure_scanner.py")
    for image, dockerfile in (
        ("aegisforge-local-target:phase14", "infra/local-scanner/Dockerfile"),
        ("aegisforge-scanner-worker:phase8", "apps/api/Dockerfile.scanner"),
    ):
        with tempfile.TemporaryDirectory(prefix="aegis-local-build-") as directory:
            if image == "aegisforge-local-target:phase14":
                context = Path(directory)
                shutil.copytree(ROOT / "apps/web/dist", context / "site")
                shutil.copy(
                    ROOT / "infra/local-scanner/server.py", context / "server.py"
                )
                shutil.copy(ROOT / dockerfile, context / "Dockerfile")
                command(
                    "docker", "--context", "default", "build", "-t", image, str(context)
                )
            else:
                command(
                    "docker",
                    "--context",
                    "default",
                    "build",
                    "-f",
                    dockerfile,
                    "-t",
                    image,
                    ".",
                )
        with subprocess.Popen(
            ["docker", "--context", "default", "save", image], stdout=subprocess.PIPE
        ) as source:
            subprocess.run(
                ["docker", "--context", "rootless", "load"],
                stdin=source.stdout,
                check=True,
            )
            source.stdout.close()
            if source.wait():
                raise SystemExit("Image transfer failed.")
    command(
        "docker",
        "--context",
        "rootless",
        "pull",
        "ghcr.io/zaproxy/zaproxy:2.17.0@sha256:781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef",
    )
    print("Local images and settings ready. No target registered or scan started.")


if __name__ == "__main__":
    main()
