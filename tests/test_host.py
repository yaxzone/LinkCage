# Copyright 2026 Luis Yax
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Unit tests for the native messaging host (host/launcher.py).

Security- and correctness-focused: command-injection safety, native-messaging
framing round-trip, config trust boundary, and the debug-log privacy default.

Run:  python -m unittest discover -s tests
Stdlib only (unittest) — no third-party test deps.
"""

import io
import json
import os
import struct
import sys
import tempfile
import unittest

HOST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "host")
sys.path.insert(0, HOST_DIR)

import launcher  # noqa: E402


class CommandInjectionTests(unittest.TestCase):
    def test_url_passed_as_separate_argv_never_in_script_body(self):
        captured = {}
        orig_run = launcher.subprocess.run
        launcher.subprocess.run = lambda args, *a, **k: captured.__setitem__("args", args) or type("R", (), {"returncode": 0, "stdout": b"", "stderr": b""})()
        try:
            evil = 'http://x/$(touch /tmp/pwned)";id;"`whoami`'
            launcher.open_url_in_container({"containerName": "chromium-browser"}, evil)
        finally:
            launcher.subprocess.run = orig_run
        args = captured["args"]
        self.assertIsInstance(args, list)         # argv form, no shell
        # docker exec <container> /lsiopy/bin/python -c <SCRIPT> <URL>
        # The URL must be the FINAL argv element, exactly the input string.
        self.assertEqual(args[-1], evil)
        # The script body comes right after the -c flag and must NOT contain
        # the user URL anywhere (no string concatenation / interpolation).
        idx = args.index("-c")
        script_body = args[idx + 1]
        self.assertNotIn(evil, script_body)
        # Inside the script the URL is read via sys.argv[1] and json.dumps'd
        # into the CDP params — bulletproof escaping. The test just confirms
        # the script reads from argv rather than embedding the URL.
        self.assertIn("sys.argv[1]", script_body)


class ConfigTrustTests(unittest.TestCase):
    def test_protected_keys_not_overridable_by_user_config(self):
        orig = launcher.USER_CONFIG_PATH
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"composePath": "/evil", "composeFile": "evil.yml",
                   "containerName": "attacker", "debug_log": True}, tmp)
        tmp.close()
        launcher.USER_CONFIG_PATH = tmp.name
        try:
            cfg = launcher.load_config()
        finally:
            launcher.USER_CONFIG_PATH = orig
            os.unlink(tmp.name)
        self.assertNotEqual(cfg["composePath"], "/evil")
        self.assertNotEqual(cfg["composeFile"], "evil.yml")
        self.assertNotEqual(cfg["containerName"], "attacker")
        # non-protected keys DO merge
        self.assertTrue(cfg["debug_log"])


class FramingTests(unittest.TestCase):
    def test_send_then_read_roundtrip(self):
        msg = {"action": "open", "url": "https://example.com/a?b=1"}
        out = io.BytesIO()
        orig_out = sys.stdout
        sys.stdout = type("S", (), {"buffer": out})()
        try:
            launcher.send_message(msg)
        finally:
            sys.stdout = orig_out
        raw = out.getvalue()
        # 4-byte little-endian length prefix
        self.assertEqual(struct.unpack("=I", raw[:4])[0], len(raw) - 4)
        inp = io.BytesIO(raw)
        orig_in = sys.stdin
        sys.stdin = type("S", (), {"buffer": inp})()
        try:
            parsed = launcher.read_message()
        finally:
            sys.stdin = orig_in
        self.assertEqual(parsed, msg)


class DebugDefaultTests(unittest.TestCase):
    def test_debug_log_path_is_per_user_not_tmp(self):
        norm = launcher.DEBUG_LOG_PATH.replace("\\", "/")
        self.assertTrue(launcher.DEBUG_LOG_PATH.startswith(launcher.LINKCAGE_DIR))
        self.assertNotIn("/tmp/", norm)


if __name__ == "__main__":
    unittest.main()
