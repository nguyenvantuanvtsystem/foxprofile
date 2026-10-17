"""Run one page action on many running profiles and collect the results.

Thin fan-out over BrowserLauncher.control: sequential, so a slow profile
cannot starve the others' control channels, and every profile reports its
own ok/error instead of one failure aborting the batch.
"""

from __future__ import annotations

from typing import Any

# Actions safe to broadcast: same-site, same-DOM operations. `evaluate` runs
# caller-supplied JS and is only exposed to the local user, never to MCP.
SYNC_ACTIONS = ("navigate", "back", "keyboard_type", "press", "click_at", "evaluate")


def fan_out(
    launcher: Any,
    names: list[str],
    action: str,
    params: dict[str, Any] | None = None,
    timeout: float = 60,
) -> list[dict[str, Any]]:
    """Run action on each running profile. Skips profiles that are stopped."""
    results = []
    for name in names:
        if not launcher.is_running(name):
            results.append({"name": name, "ok": False, "error": "browser is not running"})
            continue
        try:
            result = launcher.control(name, action, params or {}, timeout=timeout)
            results.append({"name": name, "ok": True, "result": result})
        except Exception as e:
            status = getattr(e, "status", None)
            message = f"HTTP {status}: {e}" if status else str(e)
            results.append({"name": name, "ok": False, "error": message})
    return results
