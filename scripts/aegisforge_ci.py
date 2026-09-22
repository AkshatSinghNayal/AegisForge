#!/usr/bin/env python3
"""Dependency-free Python 3.12+ CI client. Secrets are read only from environment."""

import argparse
import hashlib
import json
import os
import re
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from uuid import UUID

TERMINAL = {"completed", "failed", "cancelled", "timed_out"}
STATES = TERMINAL | {
    "draft",
    "queued",
    "validating_target",
    "preparing_scanner",
    "spidering",
    "passive_scanning",
    "active_scanning",
    "collecting_results",
    "normalizing",
    "enriching",
    "evaluating_policy",
    "generating_report",
}
SEVERITIES = ("critical", "high", "medium", "low", "informational")


class Failure(Exception):
    pass


class Cancelled(BaseException):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise Failure("Redirect refused")


def origin(value):
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or not re.fullmatch(r"https://[A-Za-z0-9.:-]+/?", value)
    ):
        raise Failure("Invalid origin")
    return value.rstrip("/")


class Client:
    def __init__(self, base, token, deadline):
        self.base, self.token, self.deadline = origin(base), token, deadline
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()
        )

    def call(self, method, path, body=None, key=None, retry=True):
        headers = {
            "Authorization": "Bearer " + self.token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if key:
            headers["Idempotency-Key"] = key
        for attempt in range(4 if retry else 1):
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            request = urllib.request.Request(
                self.base + path,
                method=method,
                headers=headers,
                data=json.dumps(body).encode() if body is not None else None,
            )
            try:
                with self.opener.open(request, timeout=min(15, remaining)) as response:
                    raw = response.read(2 * 1024 * 1024 + 1)
                    if len(raw) > 2 * 1024 * 1024:
                        raise Failure("Response too large")
                    return json.loads(raw)
            except urllib.error.HTTPError as error:
                if error.code not in {429, 500, 502, 503, 504}:
                    raise Failure("Request rejected") from None
            except (urllib.error.URLError, OSError):
                pass
            if attempt == (3 if retry else 0):
                raise Failure("Request unavailable")
            time.sleep(min(2**attempt, max(0, self.deadline - time.monotonic())))
        raise Failure("Request unavailable")


def uuid(value):
    return str(UUID(value))


def context(data, selection):
    if not isinstance(data, dict) or any(
        data.get(k) != v for k, v in selection.items()
    ):
        raise Failure("Configuration mismatch")
    clean = dict(selection)
    clean["gate_policy_id"] = uuid(data["gate_policy_id"])
    for key in ("target_version", "policy_version", "gate_policy_version"):
        if type(data.get(key)) is not int or data[key] < 1:
            raise Failure("Invalid version")
        clean[key] = data[key]
    return clean


def idempotency(repository, run, job, commit, config):
    return hashlib.sha256(
        json.dumps(
            [repository.lower(), run, job, commit, config],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def summary(data, scan_id):
    if (
        not isinstance(data, dict)
        or data.get("scan_id") != scan_id
        or data.get("state") not in STATES
        or type(data.get("terminal")) is not bool
        or data["terminal"] != (data["state"] in TERMINAL)
        or data.get("outcome") not in {"pass", "warn", "fail", "incomplete"}
    ):
        raise Failure("Invalid summary")
    counts = data.get("counts")
    if counts is not None:
        if not isinstance(counts, dict) or any(
            type(counts.get(k)) is not int or not 0 <= counts[k] <= 10000000
            for k in SEVERITIES
        ):
            raise Failure("Invalid counts")
        counts = {k: counts[k] for k in SEVERITIES}
    path = data.get("path", "")
    if not re.fullmatch(
        r"/app/scans/" + re.escape(scan_id) + r"\?organization=[0-9a-f-]{36}", path
    ):
        raise Failure("Invalid link")
    outcome = data["outcome"]
    if data["state"] != "completed" and outcome != "fail":
        outcome = "incomplete"
    return {
        "scan_id": scan_id,
        "state": data["state"],
        "terminal": data["terminal"],
        "outcome": outcome,
        "counts": counts,
        "path": path,
    }


def exit_code(outcome, warn_exit=2, fail_exit=1, incomplete_exit=3):
    return {
        "pass": 0,
        "warn": warn_exit,
        "fail": fail_exit,
        "incomplete": incomplete_exit,
    }[outcome]


def markdown(result, app_origin):
    # Deliberate allowlist: no finding names, URLs, evidence, branch text or API errors.
    lines = ["### AegisForge scan", "", "Result: **" + result["outcome"] + "**", ""]
    if result.get("counts") is None:
        lines.append("Finding counts unavailable; this is not a clean result.")
    else:
        lines.extend(
            ["| Severity | Findings |", "| --- | ---: |"]
            + [f"| {s} | {result['counts'][s]} |" for s in SEVERITIES]
        )
    if result.get("path"):
        lines.extend(
            [
                "",
                f"[View authorized scan details]({origin(app_origin)}{result['path']})",
            ]
        )
    return "\n".join(lines) + "\n"


def save(result, path, app_origin):
    Path(path).write_text(json.dumps(result, indent=2) + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(markdown(result, app_origin))


def update_comment(client, repository, pr, project, target, result, app_origin):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or pr < 1:
        raise Failure("Invalid PR")
    marker = (
        "<!-- aegisforge:"
        + hashlib.sha256(f"{uuid(project)}:{uuid(target)}".encode()).hexdigest()
        + " -->"
    )
    body = marker + "\n" + markdown(result, app_origin)
    path = f"/repos/{repository}/issues/{pr}/comments"
    matches = []
    for page in range(1, 101):
        rows = client.call("GET", path + f"?per_page=100&page={page}")
        if not isinstance(rows, list):
            raise Failure("Invalid comments")
        for row in rows:
            if (
                isinstance(row, dict)
                and isinstance(row.get("body"), str)
                and row["body"].startswith(marker + "\n")
                and row.get("user", {}).get("login") == "github-actions[bot]"
                and row.get("user", {}).get("type") == "Bot"
                and type(row.get("id")) is int
                and row["id"] > 0
            ):
                matches.append(row["id"])
        if len(rows) < 100:
            break
    else:
        raise Failure("Comment pagination exceeded")
    if matches:
        client.call(
            "PATCH",
            f"/repos/{repository}/issues/comments/{min(matches)}",
            {"body": body},
        )
    else:
        # Never retry a POST whose response may have been lost; next run re-lists.
        client.call("POST", path, {"body": body}, retry=False)


def run(args):
    result = {
        "scan_id": None,
        "state": "unavailable",
        "terminal": False,
        "outcome": "incomplete",
        "counts": None,
        "path": None,
    }
    client = None
    scan_id = None
    try:
        app_origin = origin(args.app_url)
        if args.comment_only:
            data = json.loads(Path(args.output).read_text())
            if data.get("scan_id") is None and data.get("outcome") == "incomplete":
                result = {
                    "scan_id": None,
                    "state": "unavailable",
                    "terminal": False,
                    "outcome": "incomplete",
                    "counts": None,
                    "path": None,
                }
            else:
                result = summary(data, uuid(data["scan_id"]))
            client = Client(
                "https://api.github.com",
                os.environ["GITHUB_TOKEN"],
                time.monotonic() + 120,
            )
            update_comment(
                client,
                args.repository,
                args.pull_request,
                args.project,
                args.target,
                result,
                app_origin,
            )
            return 0
        save(result, args.output, app_origin)
        selection = {
            "project_id": uuid(args.project),
            "target_id": uuid(args.target),
            "policy_id": uuid(args.policy),
            "environment": args.environment,
        }
        if (
            not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository)
            or not re.fullmatch(r"[a-fA-F0-9]{40}", args.commit)
            or not re.fullmatch(r"[A-Za-z0-9._/\-]{1,120}", args.branch)
            or not 1 <= args.timeout <= 21000
            or not 1 <= args.poll_interval <= 300
            or not 0 <= args.warn_exit <= 125
            or not 1 <= args.fail_exit <= 125
            or not 1 <= args.incomplete_exit <= 125
            or args.pull_request < 0
            or not args.run_id
            or not args.job
        ):
            raise Failure("Invalid input")
        client = Client(
            args.api_url,
            os.environ["AEGISFORGE_API_KEY"],
            time.monotonic() + args.timeout,
        )
        config = context(
            client.call("POST", "/api/public/v1/ci/context", selection), selection
        )
        trigger = {
            "source": "ci",
            "repository": args.repository,
            "commit": args.commit,
            "branch": args.branch,
            "pull_request": args.pull_request or None,
        }
        key = idempotency(args.repository, args.run_id, args.job, args.commit, config)
        created = client.call(
            "POST", "/api/public/v1/ci/scans", {**config, "trigger": trigger}, key
        )
        scan_id = uuid(created["id"])
        # Retain an incomplete artifact even if the process is killed abruptly.
        save(result, args.output, app_origin)
        while True:
            result = summary(
                client.call("GET", f"/api/public/v1/ci/scans/{scan_id}/summary"),
                scan_id,
            )
            save(result, args.output, app_origin)
            if result["terminal"]:
                break
            remaining = client.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            time.sleep(min(args.poll_interval, remaining))
    except (Cancelled, KeyboardInterrupt, TimeoutError):
        result.update(
            state="cancelled"
            if sys.exc_info()[0] in {Cancelled, KeyboardInterrupt}
            else "timed_out",
            terminal=True,
            outcome="incomplete",
        )
        if client and scan_id:
            client.deadline = time.monotonic() + 5
            try:
                client.call(
                    "POST", f"/api/public/v1/ci/scans/{scan_id}/cancel", {}, retry=False
                )
            except Exception:  # noqa: BLE001, S110 - never log transport secrets
                pass
    except Exception:  # noqa: BLE001 - emit only a fixed public failure
        result.update(outcome="incomplete")
        print(
            "AegisForge integration could not complete; details withheld.",
            file=sys.stderr,
        )
    finally:
        if not args.comment_only:
            save(result, args.output, args.app_url)
    return (
        exit_code(
            result["outcome"],
            args.warn_exit if 0 <= args.warn_exit <= 125 else 2,
            args.fail_exit if 1 <= args.fail_exit <= 125 else 1,
            args.incomplete_exit if 1 <= args.incomplete_exit <= 125 else 3,
        )
        if not args.comment_only
        else 3
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name, env in [
        ("api-url", "AEGISFORGE_API_URL"),
        ("app-url", "AEGISFORGE_APP_URL"),
        ("project", "AEGISFORGE_PROJECT"),
        ("target", "AEGISFORGE_TARGET"),
        ("policy", "AEGISFORGE_POLICY"),
        ("environment", "AEGISFORGE_ENVIRONMENT"),
        ("commit", "AEGISFORGE_COMMIT"),
        ("branch", "AEGISFORGE_BRANCH"),
        ("repository", "GITHUB_REPOSITORY"),
        ("run-id", "GITHUB_RUN_ID"),
        ("job", "GITHUB_JOB"),
    ]:
        parser.add_argument("--" + name, default=os.environ.get(env, ""))
    for name, default in [
        ("timeout", 900),
        ("poll-interval", 5),
        ("warn-exit", 2),
        ("fail-exit", 1),
        ("incomplete-exit", 3),
        ("pull-request", 0),
    ]:
        parser.add_argument(
            "--" + name,
            type=int,
            default=os.environ.get(
                "AEGISFORGE_" + name.upper().replace("-", "_"), default
            ),
        )
    parser.add_argument("--output", default="aegisforge-summary.json")
    parser.add_argument("--comment-only", action="store_true")

    def cancel(signum, frame):
        raise Cancelled()

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
