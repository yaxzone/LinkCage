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
Unit tests for the verdict engine (host/urlcheck.py).

Covers URL skip rules, canonicalization, URLhaus host/parent matching, and the
UrlChecker verdict + cache flow. Stdlib only.
"""

import os
import sys
import tempfile
import unittest

HOST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "host")
sys.path.insert(0, HOST_DIR)

import urlcheck  # noqa: E402


class SkipUrlTests(unittest.TestCase):
    def test_skips_local_and_nonweb(self):
        for u in ["file:///etc/passwd", "javascript:alert(1)", "about:blank",
                  "http://localhost/x", "http://127.0.0.1/x", "http://10.0.0.5/x",
                  "http://192.168.1.1/", "http://printer.local/", "chrome://settings"]:
            self.assertTrue(urlcheck.is_skip_url(u), u)

    def test_does_not_skip_public_web(self):
        for u in ["https://example.com/path", "http://93.184.216.34.nip.io/"]:
            self.assertFalse(urlcheck.is_skip_url(u), u)


class CanonicalizeTests(unittest.TestCase):
    def test_lowercases_host_sorts_query_strips_fragment(self):
        c = urlcheck.canonicalize("HTTPS://Example.COM/Path?b=2&a=1#frag")
        self.assertTrue(c.startswith("https://example.com/Path"))
        self.assertIn("a=1", c)
        self.assertIn("b=2", c)
        self.assertNotIn("frag", c)


class URLhausProviderTests(unittest.TestCase):
    def _provider(self, hosts):
        f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
        f.write("# comment\n")
        for h in hosts:
            f.write(f"127.0.0.1 {h}\n")
        f.close()
        self.addCleanup(os.unlink, f.name)
        return urlcheck.URLhausProvider(f.name)

    def test_exact_host_match_is_malicious(self):
        p = self._provider(["bad.example.com"])
        v = p.check("http://bad.example.com/x")
        self.assertIsNotNone(v)
        self.assertEqual(v.level, urlcheck.VERDICT_MALICIOUS)

    def test_parent_domain_match(self):
        p = self._provider(["evil.test"])
        v = p.check("http://a.b.evil.test/x")
        self.assertIsNotNone(v)
        self.assertEqual(v.level, urlcheck.VERDICT_MALICIOUS)

    def test_unlisted_host_no_match(self):
        p = self._provider(["bad.example.com"])
        self.assertIsNone(p.check("http://good.example.com/x"))


class UrlCheckerTests(unittest.TestCase):
    def _checker(self, hosts):
        feed = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
        for h in hosts:
            feed.write(f"127.0.0.1 {h}\n")
        feed.close()
        self.addCleanup(os.unlink, feed.name)
        return urlcheck.UrlChecker(cache_path=None, urlhaus_feed_path=feed.name, gsb_api_key=None)

    def test_malicious_listed_host(self):
        c = self._checker(["malware.test"])
        self.assertEqual(c.check("http://malware.test/x").level, urlcheck.VERDICT_MALICIOUS)

    def test_safe_when_feed_present_and_unlisted(self):
        c = self._checker(["malware.test"])
        self.assertEqual(c.check("https://example.com/").level, urlcheck.VERDICT_SAFE)

    def test_skip_url_returns_unknown_skip(self):
        c = self._checker(["malware.test"])
        v = c.check("file:///etc/passwd")
        self.assertEqual(v.level, urlcheck.VERDICT_UNKNOWN)
        self.assertEqual(v.source, "skip")

    def test_lru_cache_hit(self):
        c = self._checker(["malware.test"])
        first = c.check("https://example.com/")
        second = c.check("https://example.com/")
        self.assertFalse(first.cached)
        self.assertTrue(second.cached)


if __name__ == "__main__":
    unittest.main()
