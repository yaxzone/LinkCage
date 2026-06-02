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
Unit tests for cross-browser packaging (scripts/build-extension.py).

Verifies each per-browser zip is correct: Chrome/Edge get the service-worker
manifest with no gecko block; Firefox gets the event-page manifest with the
pinned gecko id; the Firefox-only manifest never leaks into Chromium zips; and
all three keep exactly the original three permissions. Stdlib only.
"""

import importlib.util
import json
import os
import unittest
import zipfile

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_SCRIPT = os.path.join(PROJECT, "scripts", "build-extension.py")
EXPECTED_PERMS = ["contextMenus", "nativeMessaging", "notifications"]
EXPECTED_GECKO_ID = "linkcage@yaxzone"


def _load_build_module():
    spec = importlib.util.spec_from_file_location("build_extension", BUILD_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_build_module()
        for browser in ("chrome", "edge", "firefox"):
            assert cls.mod.build(browser) == 0, f"build {browser} failed"

    def _manifest_from_zip(self, browser):
        with open(os.path.join(PROJECT, "extension", "manifest.json"), encoding="utf-8") as fh:
            version = json.load(fh)["version"]
        zpath = os.path.join(self.mod.DIST_DIR, f"linkcage-{browser}-{version}.zip")
        self.assertTrue(os.path.exists(zpath), zpath)
        zf = zipfile.ZipFile(zpath)
        names = zf.namelist()
        self.assertIn("manifest.json", names)
        self.assertNotIn("manifest.firefox.json", names)  # never leak
        return json.loads(zf.read("manifest.json")), names

    def test_chrome_and_edge_are_service_worker_no_gecko(self):
        for browser in ("chrome", "edge"):
            m, _ = self._manifest_from_zip(browser)
            self.assertIn("service_worker", m.get("background", {}))
            self.assertNotIn("browser_specific_settings", m)
            self.assertNotIn("key", m)
            self.assertEqual(m.get("permissions"), EXPECTED_PERMS)

    def test_firefox_is_event_page_with_pinned_gecko_id(self):
        m, _ = self._manifest_from_zip("firefox")
        self.assertIn("scripts", m.get("background", {}))
        self.assertEqual(
            m.get("browser_specific_settings", {}).get("gecko", {}).get("id"),
            EXPECTED_GECKO_ID,
        )
        self.assertEqual(m.get("permissions"), EXPECTED_PERMS)

    def test_all_browsers_have_manifest_at_zip_root(self):
        for browser in ("chrome", "edge", "firefox"):
            _, names = self._manifest_from_zip(browser)
            self.assertIn("background.js", names)
            self.assertTrue(any(n.startswith("icons/") for n in names))


if __name__ == "__main__":
    unittest.main()
