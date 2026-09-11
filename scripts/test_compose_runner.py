"""Exercise E2E preflight and cleanup without starting Docker."""

import base64
import json
import runpy
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

RUNNER = Path(__file__).with_name("test_auth_e2e.py")


class ComposeRunnerTests(unittest.TestCase):
    def run_runner(self, key, browser_failure=False):
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            if "config" in args:
                self.assertTrue(kwargs["capture_output"])
                return subprocess.CompletedProcess(
                    args,
                    0,
                    stdout=json.dumps(
                        {
                            "services": {
                                "api": {"environment": {"AEGIS_LOCAL_SECRET_KEY": key}}
                            }
                        }
                    ),
                )
            if browser_failure and args[0] == "pnpm":
                raise subprocess.CalledProcessError(1, args)
            return subprocess.CompletedProcess(args, 0)

        with patch("subprocess.run", side_effect=run), patch("sys.argv", [str(RUNNER)]):
            try:
                runpy.run_path(str(RUNNER), run_name="__main__")
            except (SystemExit, subprocess.CalledProcessError) as exc:
                return calls, exc
        return calls, None

    def test_missing_or_invalid_key_stops_before_stack_mutation(self):
        for key in ("", "invalid", base64.urlsafe_b64encode(b"short").decode()):
            calls, error = self.run_runner(key)
            self.assertIsInstance(error, SystemExit)
            self.assertEqual(len(calls), 1)
            self.assertIn("config", calls[0])
            self.assertEqual(calls[0][calls[0].index("-p") + 1], "aegisforge")

    def test_success_and_browser_failure_preserve_shared_volumes(self):
        for fails in (False, True):
            calls, error = self.run_runner(
                base64.urlsafe_b64encode(b"x" * 32).decode(), fails
            )
            self.assertEqual(error is not None, fails)
            compose = [call for call in calls if call[0] != "pnpm"]
            self.assertEqual(len(compose), 3)
            self.assertEqual(compose[-1][-1], "down")
            for call in compose:
                self.assertEqual(call[call.index("-p") + 1], "aegisforge")
                self.assertNotIn("--volumes", call)
                self.assertNotIn("--remove-orphans", call)


if __name__ == "__main__":
    unittest.main()
