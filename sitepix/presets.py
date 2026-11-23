"""Named image sizes and the math that turns a target size into a generation size."""

from __future__ import annotations

import math
import re

# Target sizes in pixels, the size of the file you end up with.
SIZES = {
    "hero": (1600, 900),
    "og": (1200, 630),
    "square": (1024, 1024),
    "thumb": (640, 360),
    "banner": (1920, 640),
    "portrait": (832, 1216),
    "icon": (512, 512),
}

SIZE_NOTES = {
    "hero": "wide page header, 16:9",
    "og": "social share image (Open Graph)",
    "square": "general purpose square",
    "thumb": "small card thumbnail, 16:9",
    "banner": "very wide strip, 3:1",
    "portrait": "tall image",
    "icon": "small square",
}

# Image models work best near 1 megapixel. Far above it they slow down a lot,
# far below it they lose detail, so the generation size is pulled into this range
# and the result is resized to the exact target afterward.
MIN_PIXELS = 600_000
MAX_PIXELS = 1_600_000
MULTIPLE = 16
MIN_SIDE = 256
MAX_TARGET_SIDE = 4096


class SizeError(ValueError):
    pass


def parse_size(value: str) -> tuple[int, int]:
    """Accept a preset name ("hero") or an explicit size ("1200x630")."""
    text = (value or "").strip().lower()
    if text in SIZES:
        return SIZES[text]
    match = re.fullmatch(r"(\d{2,5})\s*[x*]\s*(\d{2,5})", text)
    if not match:
        names = ", ".join(sorted(SIZES))
        raise SizeError(f"unknown size '{value}', use WIDTHxHEIGHT or one of: {names}")
    width, height = int(match.group(1)), int(match.group(2))
    if not (64 <= width <= MAX_TARGET_SIDE and 64 <= height <= MAX_TARGET_SIDE):
        raise SizeError(f"size {width}x{height} is out of range, each side must be 64 to {MAX_TARGET_SIDE}")
    return width, height


def _round_up(value: float, multiple: int = MULTIPLE) -> int:
    return max(MIN_SIDE, int(math.ceil(value / multiple)) * multiple)


def plan_generation(width: int, height: int) -> tuple[int, int]:
    """Return the size to generate at for a given target size.

    The generated image always covers the target after scaling, so the final
    step is a resize plus a small center crop, never a stretch.
    """
    pixels = width * height
    scale = 1.0
    if pixels > MAX_PIXELS:
        scale = math.sqrt(MAX_PIXELS / pixels)
    elif pixels < MIN_PIXELS:
        scale = math.sqrt(MIN_PIXELS / pixels)
    return _round_up(width * scale), _round_up(height * scale)
