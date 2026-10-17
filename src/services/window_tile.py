"""Arrange browser windows in a grid, like nick-farming tools do.

macOS only (AppleScript via Finder/Chrome). Other platforms raise OSError
with a clear message instead of failing silently.
"""

from __future__ import annotations

import re
import subprocess
import sys

# Which app owns the windows, per engine. Override per call when needed.
APP_NAMES = {"chrome": "Chromium", "camoufox": "Camoufox"}

LAYOUTS = ("auto", "1x2", "2x2", "3x2", "3x3")


def compute_grid(n: int, layout: str = "auto", aspect: float = 16 / 10) -> tuple[int, int]:
    """(cols, rows) for n windows.

    Explicit layouts (1x2, 2x2, ...) are honored as-is. "auto" tries every
    cols x rows box that fits n and picks the grid whose shape is closest to
    the screen aspect with the fewest holes, so 10 windows on a wide screen
    become 5x2 instead of a 3x4 with two holes.
    """
    if layout and layout != "auto":
        m = re.fullmatch(r"(\d+)x(\d+)", layout)
        if m:
            return int(m.group(1)), int(m.group(2))
    if n <= 1:
        return 1, 1
    best: tuple[float, tuple[int, int]] | None = None
    for cols in range(1, n + 1):
        rows = (n + cols - 1) // cols
        holes = cols * rows - n
        score = holes * 1.5 + abs(cols / rows - aspect)
        if best is None or score < best[0]:
            best = (score, (cols, rows))
    assert best is not None
    return best[1]


def screen_work_area() -> tuple[int, int, int, int]:
    """(x, y, w, h) of the macOS desktop minus menu bar and dock."""
    if not sys.platform.startswith("darwin"):
        raise OSError("window tiling is only supported on macOS")
    try:
        out = subprocess.run(
            ["osascript", "-e", 'tell application "Finder" to get bounds of window of desktop'],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except subprocess.TimeoutExpired as e:
        raise OSError(
            "macOS did not answer window tiling (allow Automation for the terminal/app in System Settings)"
        ) from e
    m = re.search(r"(-?\d+)[,\s]+(-?\d+)[,\s]+(-?\d+)[,\s]+(-?\d+)", out)
    if not m:
        return 0, 25, 1512, 859
    x1, y1, x2, y2 = (int(m.group(i)) for i in range(1, 5))
    return x1, y1 + 25, x2 - x1, y2 - y1 - 25 - 60


def compute_rects(n: int, layout: str = "auto") -> list[tuple[int, int, int, int]]:
    """Window rects (x, y, w, h) for n windows in row-major order."""
    if n <= 0:
        return []
    x, y, w, h = screen_work_area()
    cols, rows = compute_grid(n, layout, aspect=(w / h if h else 16 / 10))
    cw, ch = w // cols, h // rows
    rects = []
    for i in range(n):
        c, r = i % cols, i // cols
        rects.append((x + c * cw, y + r * ch, cw, ch))
    return rects


def arrange_windows(app_name: str, rects: list[tuple[int, int, int, int]]) -> int:
    """Tile windows across every process of an app (one window per profile).

    Each profile runs in its own browser process, so addressing
    `application "Chromium"` only reaches the first one. System Events sees
    all of them. Needs Accessibility access; otherwise OSError explains it.
    Windows keep their enumeration order, so exact profile order is not
    guaranteed — launch-many already opens each window in its own cell.
    """
    if not rects:
        return 0
    if not sys.platform.startswith("darwin"):
        raise OSError("window tiling is only supported on macOS")
    script = [
        'tell application "System Events"',
        "set wins to {}",
        f"repeat with proc in (every process whose name is {quoted(app_name)})",
        "set wins to wins & (every window of proc)",
        "end repeat",
        "repeat with i from 1 to count of wins",
    ]
    for i, (x, y, w, h) in enumerate(rects, start=1):
        script.append(
            "if i is "
            + str(i)
            + " then set {position, size} of item i of wins to "
            + "{{"
            + f"{x}, {y}"
            + "}, {"
            + f"{w}, {h}"
            + "}}"
        )
    script += ["end repeat", "end tell"]
    args = []
    for line in script:
        args += ["-e", line]
    try:
        proc = subprocess.run(["osascript", *args], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as e:
        raise OSError(
            f"macOS did not arrange {app_name} windows (allow Accessibility in System Settings)"
        ) from e
    err = (proc.stderr or "").lower()
    if proc.returncode != 0 and (
        "assistive access" in err or "truy cập hỗ trợ" in err or "-25211" in err
    ):
        raise OSError(
            "macOS blocked window tiling: System Settings > Privacy & Security > "
            "Accessibility > enable FoxProfile, then retry"
        )
    if proc.returncode != 0:
        # Permission codes (-25211, -10003) sit at the END of the message.
        err = (proc.stderr or "").strip()
        raise OSError(f"could not arrange {app_name} windows: {err[-300:]}")
    # More rects than windows is fine (extra cells stay empty); fewer rects
    # than windows leaves the rest where they are.
    return len(rects)


def quoted(name: str) -> str:
    return '"' + name.replace('"', "") + '"'


def is_permission_error(exc: Exception) -> bool:
    """True when macOS refused window control (needs Accessibility access)."""
    msg = str(exc).lower()
    return (
        "accessibility" in msg
        or "-25211" in msg
        or "-10003" in msg
        or "assistive access" in msg
        or "truy cập hỗ trợ" in msg
        or "không được phép truy cập" in msg
        or "not permitted" in msg
    )
