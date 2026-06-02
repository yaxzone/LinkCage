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
Generate the LinkCage extension icons (16/48/128) from a single source PNG.

DEV-ONLY tool — requires Pillow (`pip install Pillow`). Intentionally NOT
added to the project's `requirements.txt`: the runtime host stays stdlib-only.
Re-run this whenever the source icon changes.

Usage:
    python scripts/generate-icons.py --src ~/Downloads/icon-source.png
    python scripts/generate-icons.py --src icon.png --crop left|center|right
    python scripts/generate-icons.py --src brand-sheet.png --box X,Y,W,H

Outputs (overwritten in place):
    extension/icons/icon16.png
    extension/icons/icon48.png
    extension/icons/icon128.png

Notes:
  - Alpha is preserved (icons are PNG with transparency).
  - Non-square sources are center-cropped by default; --crop or --box override.
  - LANCZOS resampling for high-quality downscale.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow not installed. Run: pip install Pillow", file=sys.stderr)
    sys.exit(2)

PROJECT_DIR = Path(__file__).resolve().parent.parent
ICONS_DIR = PROJECT_DIR / "extension" / "icons"
SIZES = (16, 48, 128)


def square_from(img: Image.Image, crop: str) -> Image.Image:
    """Center- (or left/right-) crop to a square."""
    w, h = img.size
    if w == h:
        return img
    side = min(w, h)
    if w > h:
        if crop == "left":
            box = (0, 0, side, side)
        elif crop == "right":
            box = (w - side, 0, w, side)
        else:
            box = ((w - side) // 2, 0, (w + side) // 2, side)
    else:
        # taller than wide — center vertically by default
        if crop == "left":
            box = (0, 0, side, side)
        elif crop == "right":
            box = (0, h - side, side, h)
        else:
            box = (0, (h - side) // 2, side, (h + side) // 2)
    return img.crop(box)


def parse_box(s: str) -> tuple[int, int, int, int]:
    parts = [int(p.strip()) for p in s.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("--box must be X,Y,W,H")
    x, y, w, h = parts
    return (x, y, x + w, y + h)


def main() -> int:
    p = argparse.ArgumentParser(description="Generate extension icons from a source PNG.")
    p.add_argument("--src", required=True, help="Source image (PNG with alpha recommended).")
    p.add_argument("--crop", choices=("left", "center", "right"), default="center",
                   help="How to square a non-square source (default: center).")
    p.add_argument("--box", type=parse_box,
                   help="Crop to an explicit X,Y,W,H region before squaring (e.g. to extract one tile from a brand sheet).")
    args = p.parse_args()

    src = Path(os.path.expanduser(args.src))
    if not src.exists():
        print(f"ERROR: source not found: {src}", file=sys.stderr)
        return 1

    img = Image.open(src).convert("RGBA")
    print(f"  source: {src}  ({img.width}x{img.height})")

    if args.box:
        img = img.crop(args.box)
        print(f"  --box crop -> {img.width}x{img.height}")

    img = square_from(img, args.crop)
    if img.width != img.height:
        print(f"ERROR: post-crop image is not square ({img.width}x{img.height})", file=sys.stderr)
        return 1
    print(f"  squared:  {img.width}x{img.height}  (crop={args.crop})")

    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        out = ICONS_DIR / f"icon{size}.png"
        resized = img.resize((size, size), Image.LANCZOS)
        # Save with optimize to keep PNGs lean; preserves alpha.
        resized.save(out, format="PNG", optimize=True)
        print(f"  wrote:    {out}  ({size}x{size}, {out.stat().st_size} bytes)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
