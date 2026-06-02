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
Unit tests for the pre-sandbox splash page (host/splash.py).

Focus: the attacker-controlled display URL must be HTML-escaped so the splash
page (opened in the real host browser) can't be turned into an XSS vector.
Stdlib only.
"""

import os
import sys
import unittest

HOST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "host")
sys.path.insert(0, HOST_DIR)

import splash  # noqa: E402


class SplashEscapingTests(unittest.TestCase):
    def test_malicious_url_is_escaped(self):
        evil = 'https://x/"><script>alert(document.cookie)</script>'
        html = splash.build_splash_html(
            {"level": "MALICIOUS", "source": "urlhaus", "reason": "bad",
             "threat_types": ["MALWARE"], "confidence": "High"},
            display_url=evil,
            continue_url="https://localhost:3443",
        )
        # The raw script tag must not appear; the escaped form must.
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)

    def test_reason_field_escaped(self):
        html = splash.build_splash_html(
            {"level": "SUSPICIOUS", "source": "gsb",
             "reason": '<img src=x onerror=alert(1)>', "threat_types": []},
            display_url="https://example.com",
            continue_url="https://localhost:3443",
        )
        self.assertNotIn("<img src=x onerror=", html)
        self.assertIn("&lt;img", html)

    def test_continue_url_is_a_valid_document(self):
        html = splash.build_splash_html(
            {"level": "SAFE", "source": "urlhaus", "reason": "ok", "threat_types": []},
            display_url="https://example.com",
            continue_url="https://localhost:3443",
        )
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Content-Security-Policy", html)


if __name__ == "__main__":
    unittest.main()
