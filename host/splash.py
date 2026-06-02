#!/usr/bin/env python3
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
LinkCage Splash — pre-sandbox verdict splash screen.

Builds a self-contained HTML5 document that is opened by Chrome via
`--app=file://...` so the user sees the verdict *inside* the sandbox window
before being auto-redirected (or button-advanced) to the Selkies container URL.

Pure stdlib only. No external templating.

Public API:
  - build_splash_html(verdict: dict, display_url: str, continue_url: str) -> str
  - write_splash_file(verdict: dict, display_url: str, continue_url: str, out_dir: str = None) -> str
  - cleanup_old_splashes(out_dir: str = None, max_age_seconds: int = 3600) -> None

The verdict dict MAY include a pre-computed human-readable "confidence" field
(string). The launcher is expected to inject it via `urlcheck.compute_confidence`
before calling these functions. If it's missing we fall back to an empty string.
"""

from __future__ import annotations

import glob
import html
import os
import tempfile
import time


DISCLAIMER = (
    "URL reputation checks are based on public threat feeds and cannot catch every "
    "malicious link. A SAFE result means the URL was not flagged \u2014 not that it has "
    "been proven safe. Use your own judgment."
)


LEVEL_CONFIG = {
    "SAFE":       {"bg": "#1B5E20", "icon": "\u2713", "auto_ms": 3000, "primary": "Skip",                         "secondary": None},
    "UNKNOWN":    {"bg": "#424242", "icon": "?",     "auto_ms": 4000, "primary": "Continue",                     "secondary": None},
    "SUSPICIOUS": {"bg": "#E65100", "icon": "\u26A0", "auto_ms": 0,    "primary": "I understand, continue",       "secondary": "Cancel"},
    "MALICIOUS":  {"bg": "#B71C1C", "icon": "\u2715", "auto_ms": 0,    "primary": "I accept the risk, continue", "secondary": "Cancel"},
    "SKIP":       {"bg": "#37474F", "icon": "\u00B7", "auto_ms": 1000, "primary": "Continue",                     "secondary": None},
}


def _truncate_url(url: str, limit: int = 120) -> str:
    """Shorten a URL for display: first 60 + '...' + last 40 when over limit."""
    if url is None:
        return ""
    if len(url) <= limit:
        return url
    return url[:60] + "..." + url[-40:]


def _pick_config(verdict: dict) -> dict:
    """Resolve the LEVEL_CONFIG entry, honoring the source=='skip' override."""
    if (verdict or {}).get("source") == "skip":
        return LEVEL_CONFIG["SKIP"]
    level = (verdict or {}).get("level", "UNKNOWN")
    return LEVEL_CONFIG.get(level, LEVEL_CONFIG["UNKNOWN"])


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';">
<title>LinkCage verdict: __LEVEL__</title>
<style>
  html, body { margin: 0; padding: 0; height: 100%; width: 100%; }
  body {
    background: __BG__;
    color: #fff;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    display: flex; align-items: center; justify-content: center;
    min-height: 100vh; padding: 24px; box-sizing: border-box;
  }
  .card {
    background: rgba(0,0,0,0.35);
    border-radius: 14px;
    padding: 32px 36px;
    max-width: 720px; width: 100%;
    box-shadow: 0 10px 30px rgba(0,0,0,0.4);
    text-align: center;
  }
  .icon { font-size: 72px; line-height: 1; margin-bottom: 8px; }
  .title { font-size: 34px; font-weight: 700; letter-spacing: 1px; margin: 4px 0 4px; }
  .conf { font-size: 15px; opacity: 0.85; margin-bottom: 18px; }
  .url { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 14px;
         background: rgba(255,255,255,0.1); padding: 10px 12px; border-radius: 8px;
         word-break: break-all; margin: 8px 0 16px; }
  .meta { text-align: left; font-size: 14px; opacity: 0.95; margin: 10px 0; }
  .meta .row { margin: 6px 0; }
  .meta .label { opacity: 0.7; display: inline-block; min-width: 90px; }
  .disclaimer { font-size: 12px; opacity: 0.8; margin: 16px 0 18px; line-height: 1.45; }
  .buttons { display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }
  button {
    font: inherit; font-size: 15px; font-weight: 600;
    padding: 12px 22px; border-radius: 8px; border: 0;
    cursor: pointer;
  }
  .primary { background: #fff; color: #111; }
  .secondary { background: transparent; color: #fff; border: 1px solid rgba(255,255,255,0.6); }
  .countdown { margin-top: 14px; font-size: 13px; opacity: 0.8; min-height: 1em; }
</style>
</head>
<body>
  <div class="card" role="alert" aria-live="assertive">
    <div class="icon" aria-hidden="true">__ICON__</div>
    <div class="title">__LEVEL__</div>
    <div class="conf">Confidence: __CONFIDENCE__</div>
    <div class="url" title="__URL_FULL__">__URL_DISPLAY__</div>
    <div class="meta">
      <div class="row"><span class="label">Reason:</span> __REASON__</div>
      <div class="row"><span class="label">Source:</span> __SOURCE__</div>
      __THREATS_ROW__
    </div>
    <div class="disclaimer">__DISCLAIMER__</div>
    <div class="buttons">
      <button class="primary" id="primaryBtn">__PRIMARY_LABEL__</button>
      __SECONDARY_BTN__
    </div>
    <div class="countdown" id="countdown"></div>
  </div>
<script>
(function(){
  var TARGET = "__TARGET_URL__";
  var AUTO_MS = __AUTO_MS__;
  var remaining = Math.floor(AUTO_MS / 1000);
  var cd = document.getElementById("countdown");
  var primary = document.getElementById("primaryBtn");
  var secondary = document.getElementById("secondaryBtn");
  var timerId = null;
  function go(){ window.location.replace(TARGET); }
  function cancel(){ try { window.close(); } catch(e) {} }
  primary.addEventListener("click", function(){
    if (timerId) { clearInterval(timerId); }
    go();
  });
  if (secondary) {
    secondary.addEventListener("click", function(){
      if (timerId) { clearInterval(timerId); }
      cancel();
    });
  }
  if (AUTO_MS > 0) {
    cd.textContent = "Continuing in " + remaining + "s...";
    timerId = setInterval(function(){
      remaining -= 1;
      if (remaining <= 0) {
        clearInterval(timerId);
        go();
        return;
      }
      cd.textContent = "Continuing in " + remaining + "s...";
    }, 1000);
  }
})();
</script>
</body>
</html>
"""


def build_splash_html(verdict: dict, display_url: str, continue_url: str) -> str:
    """
    Build a self-contained HTML5 splash page for the given verdict.

    `display_url` is shown to the user in the card (the original link the
    user clicked). `continue_url` is the URL the splash redirects to when
    the countdown elapses or the primary button is clicked (typically the
    Selkies container URL).

    The verdict dict is the one emitted by urlcheck.Verdict.to_dict(), optionally
    with a pre-computed "confidence" field (string) injected by the launcher.
    Unknown levels fall back to LEVEL_CONFIG["UNKNOWN"]. If verdict["source"] is
    "skip", LEVEL_CONFIG["SKIP"] is used regardless of the level field.

    All user-controllable strings are HTML-escaped via html.escape(..., quote=True).
    """
    verdict = verdict or {}
    cfg = _pick_config(verdict)

    raw_level = str(verdict.get("level", "UNKNOWN"))
    level_display = "SKIPPED" if verdict.get("source") == "skip" else raw_level

    confidence = str(verdict.get("confidence", "") or "N/A")
    reason = str(verdict.get("reason", "") or "(no reason provided)")
    source = str(verdict.get("source", "") or "none")
    threat_types = verdict.get("threat_types") or []
    if not isinstance(threat_types, (list, tuple)):
        threat_types = [str(threat_types)]

    url_full = str(display_url or "")
    url_display = _truncate_url(url_full)

    # Escape everything that gets interpolated into the HTML body.
    e_level = html.escape(level_display, quote=True)
    e_icon = html.escape(str(cfg["icon"]), quote=True)
    e_bg = html.escape(str(cfg["bg"]), quote=True)
    e_confidence = html.escape(confidence, quote=True)
    e_reason = html.escape(reason, quote=True)
    e_source = html.escape(source, quote=True)
    e_url_full = html.escape(url_full, quote=True)
    e_url_display = html.escape(url_display, quote=True)
    e_disclaimer = html.escape(DISCLAIMER, quote=True)
    e_primary_label = html.escape(str(cfg["primary"]), quote=True)

    if threat_types:
        safe_types = ", ".join(html.escape(str(t), quote=True) for t in threat_types)
        threats_row = (
            '<div class="row"><span class="label">Threats:</span> '
            + safe_types
            + "</div>"
        )
    else:
        threats_row = ""

    if cfg.get("secondary"):
        e_secondary_label = html.escape(str(cfg["secondary"]), quote=True)
        secondary_btn = (
            '<button class="secondary" id="secondaryBtn">'
            + e_secondary_label
            + "</button>"
        )
    else:
        secondary_btn = ""

    auto_ms = int(cfg.get("auto_ms", 0) or 0)

    # For JS, the continue URL is embedded as a string literal. Escape HTML
    # sensitive chars AND backslashes/quotes for the JS string. This is the
    # URL the splash redirects to (e.g. the Selkies container URL), NOT the
    # display URL shown in the card.
    continue_full = str(continue_url or "")
    js_target = (
        continue_full.replace("\\", "\\\\")
                     .replace('"', '\\"')
                     .replace("</", "<\\/")
    )
    e_js_target = html.escape(js_target, quote=True)

    out = _TEMPLATE
    out = out.replace("__BG__", e_bg)
    out = out.replace("__ICON__", e_icon)
    out = out.replace("__LEVEL__", e_level)
    out = out.replace("__CONFIDENCE__", e_confidence)
    out = out.replace("__URL_FULL__", e_url_full)
    out = out.replace("__URL_DISPLAY__", e_url_display)
    out = out.replace("__REASON__", e_reason)
    out = out.replace("__SOURCE__", e_source)
    out = out.replace("__THREATS_ROW__", threats_row)
    out = out.replace("__DISCLAIMER__", e_disclaimer)
    out = out.replace("__PRIMARY_LABEL__", e_primary_label)
    out = out.replace("__SECONDARY_BTN__", secondary_btn)
    out = out.replace("__AUTO_MS__", str(auto_ms))
    out = out.replace("__TARGET_URL__", e_js_target)
    return out


def write_splash_file(verdict: dict, display_url: str, continue_url: str, out_dir: str = None) -> str:
    """
    Write the splash HTML to `{out_dir}/linkcage-splash-{pid}-{ts}.html` and
    return the absolute path. The filename includes the current process pid and
    a nanosecond timestamp to make the file path unguessable across users.

    `display_url` is the URL shown in the card; `continue_url` is the URL the
    splash auto-redirects to (typically the Selkies container URL).
    """
    if out_dir is None:
        out_dir = tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)
    html_text = build_splash_html(verdict, display_url, continue_url)
    pid = os.getpid()
    ts = time.time_ns() if hasattr(time, "time_ns") else int(time.time() * 1e9)
    name = "linkcage-splash-{pid}-{ts}.html".format(pid=pid, ts=ts)
    path = os.path.abspath(os.path.join(out_dir, name))
    # Write with restrictive permissions (best effort on POSIX).
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(html_text)
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
        raise
    return path


def cleanup_old_splashes(out_dir: str = None, max_age_seconds: int = 3600) -> None:
    """
    Delete stale splash HTML files matching `linkcage-splash-*.html` in out_dir.
    Only files owned by the current user (best effort via os.stat) and older
    than max_age_seconds are removed. Silently ignores errors.
    """
    if out_dir is None:
        out_dir = tempfile.gettempdir()
    try:
        pattern = os.path.join(out_dir, "linkcage-splash-*.html")
        now = time.time()
        my_uid = None
        try:
            my_uid = os.getuid()  # type: ignore[attr-defined]
        except AttributeError:
            my_uid = None
        for path in glob.glob(pattern):
            try:
                st = os.stat(path)
                if my_uid is not None and hasattr(st, "st_uid") and st.st_uid != my_uid:
                    continue
                if (now - st.st_mtime) < max_age_seconds:
                    continue
                os.remove(path)
            except OSError:
                continue
    except Exception:
        return
