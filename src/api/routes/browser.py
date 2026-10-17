from __future__ import annotations

import contextlib
import subprocess
import threading
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ...core.config import LAUNCH_WAIT_TIMEOUT
from ...core.logging import get_logger
from ...services.browser.launcher import BrowserControlError, ProfileBusyError
from ...services.mirror import INJECT_JS, MirrorPoller, MirrorSession
from ...services.sync_ops import SYNC_ACTIONS, fan_out
from ...services.window_tile import (
    APP_NAMES,
    LAYOUTS,
    arrange_windows,
    compute_rects,
    is_permission_error,
)
from ..dependencies import get_browser_launcher, get_event_bus, get_profile_manager
from ..helpers import require_profile
from ..schemas.browser import (
    ArrangeRequest,
    ArrangeResponse,
    BrowserStatusResponse,
    LaunchManyRequest,
    LaunchManyResponse,
    LaunchManyResult,
    LaunchResponse,
    MirrorEventRequest,
    MirrorStartRequest,
    MirrorStatusResponse,
    RunningBrowsersResponse,
    SyncRequest,
    SyncResponse,
    SyncResult,
)
from ..schemas.common import ErrorResponse, SuccessResponse

if TYPE_CHECKING:
    from ...core.events import EventBus
    from ...interfaces import IBrowserLauncher, IProfileManager

logger = get_logger("api.browser")

router = APIRouter(prefix="/browser", tags=["browser"])


def _api_log(msg: str) -> None:
    logger.info("[browser] %s", msg)


# Mirror (follow-mode) routes come before /{name}/... routes: "/mirror/status"
# would otherwise match "/{name}/status" with name="mirror".
_mirror_session: MirrorSession | None = None
_mirror_poller: MirrorPoller | None = None
_mirror_lock = threading.Lock()


def _mirror_inject(bl: IBrowserLauncher, master: str) -> None:
    """(Re)install the gesture listener in the master's active tab."""
    try:
        bl.control(master, "evaluate", {"script": INJECT_JS}, timeout=20)
    except BrowserControlError as e:
        logger.warning("Mirror inject to %s failed: %s", master, e)


def _mirror_stop_locked() -> None:
    global _mirror_session, _mirror_poller
    if _mirror_poller is not None:
        _mirror_poller.stop()
        _mirror_poller = None
    _mirror_session = None


@router.post(
    "/mirror/start",
    response_model=MirrorStatusResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def mirror_start(
    body: MirrorStartRequest,
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
) -> MirrorStatusResponse:
    """Follow one master profile: its clicks/typing/scroll/navigations mirror
    to the followers. Only the master is instrumented, so nothing echoes back."""
    global _mirror_session
    require_profile(body.master, pm)
    if not bl.is_running(body.master):
        raise HTTPException(status_code=400, detail="Master browser is not running")
    followers = body.followers if body.followers is not None else sorted(bl.running_profile_names())
    followers = [f for f in followers if f != body.master]
    for f in followers:
        require_profile(f, pm)
    if not followers:
        raise HTTPException(status_code=400, detail="No followers running")
    _mirror_inject(bl, body.master)
    with _mirror_lock:
        _mirror_stop_locked()
        _mirror_session = MirrorSession(body.master, followers)
        _mirror_poller = MirrorPoller(bl, _mirror_session)
        _mirror_poller.start()
        status = _mirror_session.describe()
    return MirrorStatusResponse(**status)


@router.post("/mirror/stop", response_model=MirrorStatusResponse)
def mirror_stop() -> MirrorStatusResponse:
    with _mirror_lock:
        _mirror_stop_locked()
    return MirrorStatusResponse(active=False)


@router.get("/mirror/status", response_model=MirrorStatusResponse)
def mirror_status() -> MirrorStatusResponse:
    with _mirror_lock:
        if _mirror_session is None:
            return MirrorStatusResponse(active=False)
        return MirrorStatusResponse(**_mirror_session.describe())


@router.post("/mirror-event")
def mirror_event(
    body: MirrorEventRequest,
    bl: IBrowserLauncher = Depends(get_browser_launcher),
) -> dict:
    """Ingest gestures from API callers (the poller drives the page itself)."""
    with _mirror_lock:
        session = _mirror_session
    if session is None:
        return {"ok": False}
    result = session.ingest(bl, body.events)
    return {"ok": True, **result}


@router.get("", response_model=RunningBrowsersResponse)
def list_running(
    bl: IBrowserLauncher = Depends(get_browser_launcher),
) -> RunningBrowsersResponse:
    names = sorted(bl.running_profile_names())
    return RunningBrowsersResponse(running=names, count=len(names))


@router.get(
    "/{name}/status",
    response_model=BrowserStatusResponse,
    responses={404: {"model": ErrorResponse}},
)
def browser_status(
    name: str,
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
) -> BrowserStatusResponse:
    require_profile(name, pm)
    port = bl.cdp_port(name) if bl.is_running(name) else None
    return BrowserStatusResponse(
        name=name,
        is_running=bl.is_running(name),
        cdp_url=f"http://127.0.0.1:{port}/json" if port else None,
    )


@router.post(
    "/{name}/launch",
    response_model=LaunchResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        502: {"model": LaunchResponse},
    },
)
def launch_browser(
    name: str,
    response: Response,
    wait: bool = Query(
        True,
        description=(
            "If true (default), block until the browser is ready or has failed, "
            f"up to {LAUNCH_WAIT_TIMEOUT}s (FOXPROFILE_LAUNCH_TIMEOUT). "
            "Pass wait=false to return 202 immediately and poll GET /{name}/status."
        ),
    ),
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
    bus: EventBus = Depends(get_event_bus),
) -> LaunchResponse:
    profile = require_profile(name, pm)
    if bl.is_running(name):
        raise HTTPException(status_code=409, detail="Browser already running")

    def _on_ready() -> None:
        bus.emit()

    def _on_stop() -> None:
        bus.emit()

    try:
        started = bl.start_thread(profile, _api_log, on_ready=_on_ready, on_stop=_on_stop)
    except ProfileBusyError as e:
        raise HTTPException(status_code=409, detail="Profile is busy") from e
    if not started:
        raise HTTPException(status_code=409, detail="Browser already running")
    logger.info("API launched browser for: %s", name)
    bus.emit()

    if not wait:
        response.status_code = 202
        return LaunchResponse(success=True, message=f"Browser launching for '{name}'")

    ok, error = bl.wait_for_launch(name, LAUNCH_WAIT_TIMEOUT)
    if ok:
        return LaunchResponse(success=True, message=f"Browser started for '{name}'")
    if error == "timeout":
        response.status_code = 202
        return LaunchResponse(
            success=True,
            message=f"Browser for '{name}' is still starting",
        )
    response.status_code = 502
    return LaunchResponse(success=False, message=f"Launch failed: {error}")


@router.post(
    "/{name}/stop",
    response_model=SuccessResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def stop_browser(
    name: str,
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
    bus: EventBus = Depends(get_event_bus),
) -> SuccessResponse:
    require_profile(name, pm)
    if not bl.is_running(name):
        raise HTTPException(status_code=409, detail="Browser is not running")

    bl.stop_profile(name)
    logger.info("API stopped browser for: %s", name)
    bus.emit()
    return SuccessResponse(message=f"Browser stopped for '{name}'")


def _require_layout(layout: str) -> None:
    if layout not in LAYOUTS:
        raise HTTPException(status_code=400, detail=f"layout must be one of: {', '.join(LAYOUTS)}")


@router.post(
    "/launch-many",
    response_model=LaunchManyResponse,
    responses={400: {"model": ErrorResponse}},
)
def launch_many(
    body: LaunchManyRequest,
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
    bus: EventBus = Depends(get_event_bus),
) -> LaunchManyResponse:
    """Start many profiles at once, then tile their windows grid-style.

    Launches return as they settle (up to the launch timeout each); whatever
    is running at the end gets arranged. Slow profiles never block the batch.
    """
    _require_layout(body.layout)
    for name in body.names:
        require_profile(name, pm)

    # Tile at launch: every browser opens directly in its grid cell, so no
    # post-launch arranging (and no macOS permission) is needed.
    rects = compute_rects(len(body.names), body.layout)
    results: list[LaunchManyResult] = []
    for i, name in enumerate(body.names):
        if bl.is_running(name):
            results.append(LaunchManyResult(name=name, ok=True, message="already running"))
            continue
        try:
            started = bl.start_thread(
                pm.profiles[name],
                lambda msg, n=name: _api_log(f"[{n}] {msg}"),
                window_rect=rects[i] if i < len(rects) else None,
            )
        except ProfileBusyError:
            results.append(LaunchManyResult(name=name, ok=False, message="profile is busy"))
            continue
        if not started:
            results.append(LaunchManyResult(name=name, ok=False, message="already running"))
            continue
        ok, error = bl.wait_for_launch(name, LAUNCH_WAIT_TIMEOUT)
        results.append(
            LaunchManyResult(
                name=name, ok=ok, message="started" if ok else f"launch failed: {error}"
            )
        )
    bus.emit()

    arranged, arrange_error = 0, None
    running = [r.name for r in results if r.ok and bl.is_running(r.name)]
    if running:
        # Windows already opened in their grid cells (window_rect at launch);
        # the AppleScript pass is best-effort fine-tuning only.
        try:
            by_app: dict[str, list[str]] = {}
            for n in running:
                by_app.setdefault(APP_NAMES.get(pm.profiles[n].engine, "Chromium"), []).append(n)
            for app, group in by_app.items():
                arrange_windows(app, compute_rects(len(group), body.layout))
            arranged = len(running)
        except (OSError, subprocess.TimeoutExpired):
            arranged = len(running)
    return LaunchManyResponse(results=results, arranged=arranged, arrange_error=arrange_error)


@router.post(
    "/arrange",
    response_model=ArrangeResponse,
    responses={400: {"model": ErrorResponse}},
)
def arrange(
    body: ArrangeRequest,
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
    bus: EventBus = Depends(get_event_bus),
) -> ArrangeResponse:
    """Tile running browsers' windows. No names = all running profiles.

    Moving live windows needs Accessibility access. Without it, profiles are
    stopped and re-opened directly into the grid (tabs restore themselves),
    so the button always works.
    """
    _require_layout(body.layout)
    names = body.names if body.names is not None else sorted(bl.running_profile_names())
    for name in names:
        require_profile(name, pm)
    running = [n for n in names if bl.is_running(n)]
    try:
        by_app: dict[str, list[str]] = {}
        for n in running:
            by_app.setdefault(APP_NAMES.get(pm.profiles[n].engine, "Chromium"), []).append(n)
        arranged: list[str] = []
        for app, group in by_app.items():
            arrange_windows(app, compute_rects(len(group), body.layout))
            arranged.extend(group)
    except (OSError, subprocess.TimeoutExpired) as e:
        if not is_permission_error(e) or not running:
            raise HTTPException(status_code=400, detail=str(e)) from e
        relaunched = _relaunch_into_grid(pm, bl, sorted(running), body.layout)
        bus.emit()
        return ArrangeResponse(
            arranged=len(relaunched),
            names=relaunched,
            relaunched=True,
            note="No permission to move live windows; re-opened into the grid instead",
        )
    return ArrangeResponse(arranged=len(arranged), names=arranged)


def _relaunch_into_grid(
    pm: IProfileManager, bl: IBrowserLauncher, names: list[str], layout: str
) -> list[str]:
    """Stop profiles and open them again, each directly in its grid cell."""
    for n in names:
        with contextlib.suppress(Exception):
            bl.stop_profile(n)
    rects = compute_rects(len(names), layout)
    done: list[str] = []
    for i, name in enumerate(names):
        try:
            started = bl.start_thread(
                pm.profiles[name],
                lambda msg, n=name: _api_log(f"[{n}] {msg}"),
                window_rect=rects[i] if i < len(rects) else None,
            )
        except ProfileBusyError:
            continue
        if not started:
            continue
        ok, _ = bl.wait_for_launch(name, LAUNCH_WAIT_TIMEOUT)
        if ok and bl.is_running(name):
            done.append(name)
    return done


@router.post(
    "/sync",
    response_model=SyncResponse,
    responses={400: {"model": ErrorResponse}},
)
def sync(
    body: SyncRequest,
    pm: IProfileManager = Depends(get_profile_manager),
    bl: IBrowserLauncher = Depends(get_browser_launcher),
) -> SyncResponse:
    """Run one page action on many running profiles (same URL, same keystrokes...)."""
    if body.action not in SYNC_ACTIONS:
        raise HTTPException(
            status_code=400, detail=f"action must be one of: {', '.join(SYNC_ACTIONS)}"
        )
    for name in body.names:
        require_profile(name, pm)
    raw = fan_out(bl, body.names, body.action, body.params)
    results = [SyncResult(**r) for r in raw]
    ok_count = sum(1 for r in results if r.ok)
    return SyncResponse(results=results, ok_count=ok_count, fail_count=len(results) - ok_count)
