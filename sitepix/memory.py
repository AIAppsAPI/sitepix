"""Memory checks for macOS, so a generation does not push the machine into swap."""

from __future__ import annotations

import platform
import re
import subprocess

GB = 1024 ** 3


def is_apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def _run(cmd: list[str]) -> str | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def parse_vm_stat(text: str) -> int | None:
    """Return the bytes macOS can hand to a new process without swapping.

    Counts free, inactive, speculative and purgeable pages. Inactive pages are
    cached data the system gives up on demand, so they count as available.
    """
    size_match = re.search(r"page size of (\d+) bytes", text)
    if not size_match:
        return None
    page_size = int(size_match.group(1))
    pages = 0
    found = False
    for label in ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable"):
        match = re.search(rf"^{label}:\s+(\d+)\.", text, re.MULTILINE)
        if match:
            pages += int(match.group(1))
            found = True
    return pages * page_size if found else None


def total_bytes() -> int | None:
    out = _run(["sysctl", "-n", "hw.memsize"])
    try:
        return int(out.strip()) if out else None
    except ValueError:
        return None


def available_bytes() -> int | None:
    out = _run(["vm_stat"])
    return parse_vm_stat(out) if out else None


def swap_used_bytes() -> int | None:
    out = _run(["sysctl", "-n", "vm.swapusage"])
    if not out:
        return None
    match = re.search(r"used = ([\d.]+)([MG])", out)
    if not match:
        return None
    value = float(match.group(1))
    return int(value * (GB if match.group(2) == "G" else 1024 ** 2))


def format_gb(value: int | None) -> str:
    return "unknown" if value is None else f"{value / GB:.1f} GB"
