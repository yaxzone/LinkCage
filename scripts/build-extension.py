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
Build a store-ready zip of the LinkCage extension.

Produces `dist/linkcage-<browser>-<version>.zip` containing the contents of
`extension/` with `manifest.json` at the zip root (as stores require).

Per-browser manifests:
  - chrome / edge : use `extension/manifest.json` (Chromium MV3, service worker).
  - firefox       : use `extension/manifest.firefox.json` (gecko settings,
                    background.scripts event page).

The `manifest.json` "key" field is stripped from the Chromium packaged copy:
  - The FIRST upload of a new item must NOT contain "key" (the Web Store
    rejects it with "key field not allowed in manifest").
  - After the item is published you may keep "key" in the repo manifest so
    locally-loaded (unpacked) builds share the same extension ID as the store
    version — but it must still be stripped from the uploaded package.
The Firefox manifest keeps its gecko settings untouched.

The repo copies of the manifests are never modified; the per-browser manifest
is written into a temporary staging copy.

Usage:
    python scripts/build-extension.py [--browser chrome|edge|firefox]

With no --browser, builds all three.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
EXTENSION_DIR = PROJECT_DIR / "extension"
DIST_DIR = PROJECT_DIR / "dist"
CHROME_MANIFEST = EXTENSION_DIR / "manifest.json"
FIREFOX_MANIFEST = EXTENSION_DIR / "manifest.firefox.json"

BROWSERS = ("chrome", "edge", "firefox")

# Files/dirs never shipped in a store package.
EXCLUDE_NAMES = {
    ".DS_Store",
    "Thumbs.db",
    "__pycache__",
    "manifest.firefox.json",
}


def manifest_path_for(browser: str) -> Path:
    return FIREFOX_MANIFEST if browser == "firefox" else CHROME_MANIFEST


def load_manifest(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def stage(manifest: dict, browser: str, staging: Path) -> None:
    """Copy extension/ into staging, then write the per-browser manifest."""
    shutil.copytree(
        EXTENSION_DIR,
        staging,
        ignore=shutil.ignore_patterns(*EXCLUDE_NAMES),
        dirs_exist_ok=True,
    )
    out = dict(manifest)
    if browser in ("chrome", "edge"):
        had_key = out.pop("key", None) is not None
        if had_key:
            print('  note: stripped "key" from packaged manifest (kept in repo)')
    with open(staging / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
        f.write("\n")


def zip_dir(src: Path, out_zip: Path) -> None:
    """Zip the contents of src so manifest.json sits at the archive root."""
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    if out_zip.exists():
        out_zip.unlink()
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(src).as_posix())


def build(browser: str) -> int:
    manifest_path = manifest_path_for(browser)
    if not manifest_path.exists():
        print(f"ERROR: {manifest_path} not found", file=sys.stderr)
        return 1

    manifest = load_manifest(manifest_path)
    version = manifest.get("version", "0.0.0")
    out_zip = DIST_DIR / f"linkcage-{browser}-{version}.zip"

    with tempfile.TemporaryDirectory(prefix="linkcage-build-") as tmp:
        staging = Path(tmp) / "extension"
        stage(manifest, browser, staging)
        zip_dir(staging, out_zip)

    size_kb = out_zip.stat().st_size / 1024
    print(f"  built: {out_zip}  ({size_kb:.1f} KB)")
    print(f"  browser: {browser}  version: {version}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the LinkCage extension.")
    parser.add_argument(
        "--browser",
        choices=BROWSERS,
        help="target browser; omit to build all",
    )
    args = parser.parse_args()

    targets = [args.browser] if args.browser else list(BROWSERS)
    rc = 0
    for browser in targets:
        rc |= build(browser)
    return rc


if __name__ == "__main__":
    sys.exit(main())
