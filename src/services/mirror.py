"""Follow mode: drive one master profile, the rest mirror it.

Transport is the tab title, not fetch: pages (especially https ones) cannot
reliably POST back to localhost (private-network checks hang or drop the
request), but any page may set document.title and the server already polls
tab titles. The injected listener encodes gestures as
"FOXM:<seq>:<base64-json>"; the poller consumes, mirrors, and restores the
real title. Only the master is ever injected, so nothing echoes back.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import json
import threading
import time
from typing import Any

from ..core.logging import get_logger
from .browser.launcher import BrowserControlError

logger = get_logger("mirror")

# At most this many mirror events per second per follower; bursts above it
# are dropped (scroll storms) instead of queuing up behind a slow profile.
MAX_RATE_PER_SEC = 8.0
POLL_SECONDS = 0.3
TITLE_PREFIX = "FOXM:"

# Tabs with other schemes (chrome://newtab, ...) cannot be opened through the
# control channel, so they are mirrored as a blank placeholder tab instead.
# This keeps visible tab parity without reopen loops.
BLANK_TAB_URL = "about:blank"


def _norm_tab_url(url: object) -> str:
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        return url
    return BLANK_TAB_URL


def plan_tab_sync(
    master_urls: list[str], follower_urls: list[str], active_url: str | None
) -> list[tuple[str, dict[str, object]]]:
    """Control actions bringing ONE follower's strip to the master's.

    Returns `tab_new` (appended first, so old indices stay valid),
    `tab_close` (descending indices) and at most one `tab_select_url`
    (resolved to a fresh index at execution time).
    """
    master = [_norm_tab_url(u) for u in master_urls]
    follower = [_norm_tab_url(u) for u in follower_urls]
    actions: list[tuple[str, dict[str, object]]] = []

    missing: dict[str, int] = {}
    for url in master:
        missing[url] = missing.get(url, 0) + 1
    for url in follower:
        if missing.get(url, 0):
            missing[url] -= 1
    for url in master:
        if missing.get(url, 0):
            missing[url] -= 1
            actions.append(("tab_new", {"url": url}))

    keep: dict[str, int] = {}
    for url in master:
        keep[url] = keep.get(url, 0) + 1
    closable: list[int] = []
    for i, url in enumerate(follower):
        if keep.get(url, 0):
            keep[url] -= 1
        else:
            closable.append(i)
    for i in sorted(closable, reverse=True):
        actions.append(("tab_close", {"index": i}))

    if active_url is not None and _norm_tab_url(active_url) in set(master):
        actions.append(("tab_select_url", {"url": _norm_tab_url(active_url)}))
    return actions


def _is_inplace_nav(prev_urls: list[str], urls: list[str], active_url: str | None) -> int | None:
    """Index of the navigated tab, or None.

    Same tab count with exactly the ACTIVE tab's URL replaced. The index
    matters: with duplicated URLs (two Facebook tabs) a blind "navigate the
    active tab" can land on the wrong tab on followers.
    """
    if len(prev_urls) != len(urls):
        return None
    diffs = [i for i, (a, b) in enumerate(zip(prev_urls, urls, strict=True)) if a != b]
    if len(diffs) == 1 and urls[diffs[0]] == active_url:
        return diffs[0]
    return None


def _select_index(
    master_urls: list[str], active_idx: int | None, follower_urls: list[str]
) -> int | None:
    """Which follower tab should become active.

    Same strip order: same index (exact even with duplicated URLs).
    Otherwise: first tab showing the master's active URL.
    """
    master = [_norm_tab_url(u) for u in master_urls]
    follower = [_norm_tab_url(u) for u in follower_urls]
    if (
        active_idx is not None
        and [u for u in follower] == master
        and 0 <= active_idx < len(follower)
    ):
        return active_idx
    if active_idx is not None and 0 <= active_idx < len(master):
        wanted = master[active_idx]
        return next((i for i, u in enumerate(follower) if u == wanted), None)
    return None


class MirrorSession:
    """One active follow session. All methods are thread-safe."""

    def __init__(self, master: str, followers: list[str]) -> None:
        self.master = master
        self.followers = [f for f in followers if f != master]
        self.started_at = time.time()
        self.events_in = 0
        self.events_dropped = 0
        self._lock = threading.Lock()
        self._last_sent: dict[str, float] = {}

    def describe(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active": True,
                "master": self.master,
                "followers": list(self.followers),
                "events_in": self.events_in,
                "events_dropped": self.events_dropped,
            }

    def _allow(self, name: str) -> bool:
        now = time.monotonic()
        last = self._last_sent.get(name, 0.0)
        if now - last < 1.0 / MAX_RATE_PER_SEC:
            self.events_dropped += 1
            return False
        self._last_sent[name] = now
        return True

    def ingest(self, launcher: Any, events: list[dict[str, Any]]) -> dict[str, int]:
        """Fan out gesture events to followers. Returns {sent, dropped}."""
        sent = 0
        with self._lock:
            self.events_in += len(events)
        for ev in events:
            action, params = _to_action(ev)
            if action is None:
                continue
            for name in self.followers:
                if not launcher.is_running(name):
                    continue
                with self._lock:
                    ok_rate = self._allow(name)
                if not ok_rate:
                    continue
                try:
                    launcher.control(name, action, params, timeout=20)
                    sent += 1
                except BrowserControlError as e:
                    logger.warning("Mirror to %s failed: %s", name, e)
                except Exception as e:  # noqa: BLE001 - one slow profile must not stop the batch
                    logger.warning("Mirror to %s failed: %s", name, e)
        return {"sent": sent, "dropped": self.events_dropped}

    def navigate_tab(
        self, launcher: Any, prev_urls: list[str], urls: list[str], index: int
    ) -> dict[str, int]:
        """Mirror an in-place navigation of the tab at index.

        Targets the SAME index when the follower's strip otherwise matches;
        otherwise falls back to a full strip sync so a duplicated URL can
        never send the navigation to the wrong tab.
        """
        sent = 0
        new_url = urls[index]
        for name in self.followers:
            if not launcher.is_running(name):
                continue
            try:
                current = self._strip_of(launcher, name)
            except Exception:  # noqa: BLE001 - retry next poll
                continue
            if current is None:
                continue
            aligned = (
                len(current) == len(urls)
                and all(
                    _norm_tab_url(c) == _norm_tab_url(u)
                    for i, (c, u) in enumerate(zip(current, urls, strict=True))
                    if i != index
                )
                and _norm_tab_url(current[index]) == _norm_tab_url(prev_urls[index])
            )
            try:
                if aligned:
                    launcher.control(name, "tab_select", {"index": index}, timeout=20)
                    launcher.control(name, "navigate", {"url": new_url}, timeout=30)
                    sent += 2
                else:
                    sent += self._sync_one(launcher, name, urls, new_url, index)
            except Exception as e:  # noqa: BLE001 - reported, batch continues
                logger.warning("Mirror to %s failed: %s", name, e)
        return {"sent": sent, "dropped": self.events_dropped}

    def sync_tabs(
        self,
        launcher: Any,
        master_urls: list[str],
        active_url: str | None,
        active_idx: int | None = None,
    ) -> dict[str, int]:
        """Bring every follower's tab strip to the master's. Returns counts."""
        if active_idx is None and active_url in master_urls:
            active_idx = master_urls.index(active_url)
        sent = 0
        for name in self.followers:
            if not launcher.is_running(name):
                continue
            try:
                sent += self._sync_one(launcher, name, master_urls, active_url, active_idx)
            except Exception as e:  # noqa: BLE001 - one slow profile must not stop the batch
                logger.warning("Mirror tabs to %s failed: %s", name, e)
        return {"sent": sent, "dropped": self.events_dropped}

    @staticmethod
    def _strip_of(launcher: Any, name: str) -> list[str] | None:
        try:
            tabs = launcher.control(name, "tabs", {}, timeout=10)
        except Exception:  # noqa: BLE001 - retry next poll
            return None
        pages = tabs.get("tabs", []) if isinstance(tabs, dict) else []
        return [t.get("url", "") for t in pages if isinstance(t, dict)]

    def _sync_one(
        self,
        launcher: Any,
        name: str,
        master_urls: list[str],
        active_url: str | None,
        active_idx: int | None = None,
    ) -> int:
        sent = 0
        current = self._strip_of(launcher, name)
        if current is None:
            return 0
        # Opens first (appends keep old indices valid), then re-read the
        # strip so closes and the active-tab lookup never go stale.
        for action, params in plan_tab_sync(master_urls, current, active_url):
            if action != "tab_new":
                continue
            with self._lock:
                ok_rate = self._allow(name)
            if not ok_rate:
                continue
            try:
                launcher.control(name, action, params, timeout=30)
                sent += 1
            except Exception as e:  # noqa: BLE001 - reported, batch continues
                logger.warning("Mirror to %s failed: %s", name, e)
        current = self._strip_of(launcher, name)
        if current is None:
            return sent
        for action, params in plan_tab_sync(master_urls, current, active_url):
            if action == "tab_new":
                continue
            if action == "tab_select_url":
                idx = _select_index(master_urls, active_idx, current)
                if idx is None:
                    continue
                action, params = "tab_select", {"index": idx}
                # Selects are cheap and decisive: never rate-limited, so a
                # follower cannot get stuck on the wrong tab with no retry
                # (sync only re-runs when the master's strip changes).
                select = True
            else:
                select = False
            if not select:
                with self._lock:
                    ok_rate = self._allow(name)
                if not ok_rate:
                    continue
            try:
                launcher.control(name, action, params, timeout=30)
                sent += 1
            except Exception as e:  # noqa: BLE001 - e.g. closing the last tab
                logger.debug("Mirror to %s skipped: %s", name, e)
        return sent


def _to_action(ev: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """A gesture from the page -> a control action for followers."""
    kind = ev.get("kind")
    if kind == "navigate":
        url = ev.get("url", "")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            return None, {}
        return "navigate", {"url": url}
    if kind == "click":
        try:
            return "click_at", {"x": float(ev["x"]), "y": float(ev["y"])}
        except (KeyError, TypeError, ValueError):
            return None, {}
    if kind == "input":
        selector = ev.get("selector", "")
        value = ev.get("value", "")
        if not isinstance(selector, str) or not selector or not isinstance(value, str):
            return None, {}
        return "type", {"selector": selector, "text": value}
    if kind == "scroll":
        try:
            return "evaluate", {"script": f"window.scrollTo({float(ev['x'])}, {float(ev['y'])})"}
        except (KeyError, TypeError, ValueError):
            return None, {}
    return None, {}


def parse_title(title: str) -> tuple[int, list[dict[str, Any]]] | None:
    """Decode a FOXM title. Returns (seq, events) or None when not ours."""
    if not isinstance(title, str) or not title.startswith(TITLE_PREFIX):
        return None
    try:
        seq_s, payload = title[len(TITLE_PREFIX) :].split(":", 1)
        events = json.loads(base64.b64decode(payload.encode()).decode())
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None
    if not isinstance(events, list):
        return None
    return int(seq_s), [e for e in events if isinstance(e, dict)][:10]


class MirrorPoller(threading.Thread):
    """Polls the master's active tab and mirrors gestures + URL changes.

    Runs as a daemon; stops when the session is replaced or stop() is called.
    Owns a token so a stale poller (replaced session) exits on its own.
    """

    def __init__(self, launcher: Any, session: MirrorSession) -> None:
        super().__init__(daemon=True)
        self._launcher = launcher
        self._session = session
        self._stop = threading.Event()
        self._last_seq = -1
        self._last_url: str | None = None
        self._last_urls: list[str] | None = None
        self._last_active: str | None = None
        self._real_title = ""

    def stop(self) -> None:
        self._stop.set()

    def _tab_list(self) -> list[dict[str, Any]]:
        try:
            tabs = self._launcher.control(self._session.master, "tabs", {}, timeout=10)
        except Exception as e:  # noqa: BLE001 - master busy/closed: retry next poll
            logger.debug("Mirror poll tabs failed: %s", e)
            return []
        pages = tabs.get("tabs", []) if isinstance(tabs, dict) else []
        return [t for t in pages if isinstance(t, dict)]

    def _active_tab(self) -> dict[str, Any] | None:
        pages = self._tab_list()
        for tab in pages:
            if tab.get("active"):
                return tab
        return pages[0] if pages else None

    def _ensure_injected(self) -> None:
        try:
            flag = self._launcher.control(
                self._session.master, "evaluate", {"script": "!!window.__fox_mirror"}, timeout=10
            )
        except Exception:  # noqa: BLE001 - retry next poll
            return
        # Control wraps the value as {"result": ...}.
        if flag is True or (isinstance(flag, dict) and flag.get("result") is True):
            return
        try:
            self._launcher.control(
                self._session.master, "evaluate", {"script": INJECT_JS}, timeout=20
            )
        except Exception as e:  # noqa: BLE001 - retry next poll
            logger.debug("Mirror inject failed: %s", e)

    def _restore_title(self) -> None:
        with contextlib.suppress(Exception):
            self._launcher.control(
                self._session.master,
                "evaluate",
                {"script": "document.title = window.__fox_title || ''"},
                timeout=10,
            )

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:  # noqa: BLE001 - poller never dies on one bad poll
                logger.debug("Mirror poll failed: %s", e)
            self._stop.wait(POLL_SECONDS)

    def _tick(self) -> None:
        if not self._launcher.is_running(self._session.master):
            return
        self._ensure_injected()
        tabs = self._tab_list()
        if not tabs:
            return
        urls = [t.get("url", "") for t in tabs]
        active = next((t for t in tabs if t.get("active")), tabs[0])
        active_url = active.get("url", "")
        active_idx = next((i for i, t in enumerate(tabs) if t.get("active")), 0)
        if self._last_urls is None:
            self._last_urls = urls
            self._last_active = active_url
            self._last_url = active_url
        elif (urls, active_url) != (self._last_urls, self._last_active):
            prev = self._last_urls
            self._last_urls = urls
            self._last_active = active_url
            self._last_url = active_url
            nav_idx = _is_inplace_nav(prev, urls, active_url)
            if (
                nav_idx is not None
                and isinstance(active_url, str)
                and active_url.startswith(("http://", "https://"))
            ):
                # Same tabs, active one went somewhere: navigate the same
                # index in place so history, scroll and tab count survive.
                self._session.navigate_tab(self._launcher, prev, urls, nav_idx)
            else:
                # Opened / closed / switched tabs: reconcile whole strips.
                self._session.sync_tabs(self._launcher, urls, active_url, active_idx)
            return
        tab = active
        if self._last_url is None:
            self._last_url = active_url
        title = tab.get("title", "")
        parsed = parse_title(title)
        if parsed is None:
            if isinstance(title, str) and title:
                self._real_title = title
            return
        seq, events = parsed
        if seq <= self._last_seq:
            return
        self._last_seq = seq
        if events:
            self._session.ingest(self._launcher, events)
        self._restore_title()


INJECT_JS = r"""
(function () {
  if (window.__fox_mirror) return "already";
  window.__fox_mirror = true;
  window.__fox_title = document.title;
  window.__fox_seq = 0;
  var queue = [];
  function b64(s) {
    return btoa(unescape(encodeURIComponent(JSON.stringify(s))));
  }
  function flush() {
    if (!queue.length) return;
    window.__fox_seq += 1;
    var batch = queue.splice(0, 5);
    try {
      document.title = "FOXM:" + window.__fox_seq + ":" + b64(batch);
    } catch (e) {}
  }
  setInterval(flush, 300);
  var lastScroll = 0;
  document.addEventListener("click", function (e) {
    queue.push({kind: "click", x: e.clientX, y: e.clientY});
    flush();
  }, true);
  document.addEventListener("change", function (e) {
    var t = e.target;
    if (!t || (t.tagName !== "INPUT" && t.tagName !== "TEXTAREA")) return;
    if (t.type === "password" || t.type === "file") return;
    queue.push({kind: "input", selector: cssPath(t), value: t.value});
    flush();
  }, true);
  document.addEventListener("scroll", function () {
    var now = Date.now();
    if (now - lastScroll < 800) return;
    lastScroll = now;
    queue.push({kind: "scroll", x: window.scrollX, y: window.scrollY});
    flush();
  }, true);
  function cssPath(el) {
    var parts = [];
    while (el && el.nodeType === 1 && parts.length < 5) {
      var name = el.tagName.toLowerCase();
      if (el.id) { parts.unshift(name + "#" + el.id); break; }
      var sib = el, n = 1;
      while ((sib = sib.previousElementSibling)) {
        if (sib.tagName === el.tagName) n++;
      }
      parts.unshift(name + ":nth-of-type(" + n + ")");
      el = el.parentElement;
    }
    return parts.join(" > ");
  }
  return "injected";
})();
"""
