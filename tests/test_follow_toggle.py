import flet as ft

from src.services.follow_toggle import pick_follow_group
from src.ui.components.bulk_bar import _build_container
from src.ui.state import AppState
from src.ui.theme.styles import ACCENT_STYLE, OUTLINE_STYLE


def test_master_is_first_ticked_running():
    assert pick_follow_group(["b", "a", "c"], ["a", "b", "c"]) == ("b", ["a", "c"])


def test_skips_ticked_but_stopped():
    assert pick_follow_group(["a", "b", "c"], ["b", "c"]) == ("b", ["c"])


def test_falls_back_to_sorted_running_when_nothing_ticked():
    assert pick_follow_group([], ["c", "a", "b"]) == ("a", ["b", "c"])


def test_none_when_fewer_than_two_running():
    assert pick_follow_group(["a"], ["a"]) is None
    assert pick_follow_group([], ["a"]) is None
    assert pick_follow_group([], []) is None


def test_selection_order_tracks_ticks():
    state = AppState()
    state.toggle_selection("b")
    state.toggle_selection("a")
    state.toggle_selection("b")  # untick
    state.toggle_selection("c")
    assert state.selection_order() == ["a", "c"]


def test_selection_order_select_all_appends_in_page_order():
    state = AppState()
    state.toggle_selection("a")
    state.select_all(["b", "c"])
    state.select_all(["c", "d"])
    assert state.selection_order() == ["a", "b", "c", "d"]


def test_selection_order_cleared():
    state = AppState()
    state.toggle_selection("a")
    state.clear_selection()
    assert state.selection_order() == []


def _follow_button(container: ft.Container) -> ft.Control:
    row = container.content
    assert isinstance(row, ft.Row)
    for ctl in row.controls:
        if getattr(ctl, "icon", None) == ft.Icons.VISIBILITY_ROUNDED:
            return ctl
    raise AssertionError("follow button not found")


def test_follow_button_lit_when_active():
    btn = _follow_button(_build_container(2, {}, follow_active=True))
    assert isinstance(btn, ft.Button)
    assert btn.style is ACCENT_STYLE


def test_follow_button_plain_when_idle():
    btn = _follow_button(_build_container(2, {}, follow_active=False))
    assert isinstance(btn, ft.OutlinedButton)
    assert btn.style is OUTLINE_STYLE


class _FakeLauncher:
    def __init__(self, running: set[str]) -> None:
        self._running = running

    def is_running(self, name: str) -> bool:
        return name in self._running

    def running_profile_names(self) -> list[str]:
        return sorted(self._running)


def _make_handlers(state: AppState, running: set[str], logs: list[str]):
    from src.ui.handlers import AppHandlers

    return AppHandlers(
        pm=object(),
        bl=_FakeLauncher(running),
        ps=object(),
        state=state,
        get_page=lambda: None,
        get_refs=lambda: None,
        log_fn=logs.append,
        refresh_fn=lambda: None,
        get_page_profiles=lambda: (None, [], None),
    )


def _wait_for(logs: list[str], timeout: float = 5.0) -> None:
    import time

    deadline = time.monotonic() + timeout
    while not logs and time.monotonic() < deadline:
        time.sleep(0.05)
    assert logs, "toggle produced no log output"


def test_on_bulk_follow_starts_with_first_ticked_master(monkeypatch):
    from src.ui.dialogs import follow as follow_mod

    calls: list[tuple] = []
    monkeypatch.setattr(follow_mod, "mirror_status", lambda: {"active": False})
    monkeypatch.setattr(
        follow_mod,
        "mirror_start",
        lambda master, followers: calls.append((master, followers)) or {},
    )
    state = AppState()
    state.toggle_selection("b")
    state.toggle_selection("a")
    logs: list[str] = []
    _make_handlers(state, {"a", "b", "c"}, logs).on_bulk_follow()
    _wait_for(logs)
    assert calls == [("b", ["a"])]
    assert state.follow_active and state.follow_master == "b"


def test_on_bulk_follow_second_tap_stops(monkeypatch):
    from src.ui.dialogs import follow as follow_mod

    calls: list[tuple] = []
    monkeypatch.setattr(follow_mod, "mirror_status", lambda: {"active": True})
    monkeypatch.setattr(follow_mod, "mirror_stop", lambda: calls.append(("stop",)) or {})
    state = AppState()
    state.follow_active = True
    state.follow_master = "b"
    logs: list[str] = []
    _make_handlers(state, {"a", "b"}, logs).on_bulk_follow()
    _wait_for(logs)
    assert calls == [("stop",)]
    assert not state.follow_active and state.follow_master == ""


def test_on_bulk_follow_needs_two_running(monkeypatch):
    from src.ui.dialogs import follow as follow_mod

    monkeypatch.setattr(follow_mod, "mirror_status", lambda: {"active": False})
    state = AppState()
    state.toggle_selection("a")
    logs: list[str] = []
    _make_handlers(state, {"a"}, logs).on_bulk_follow()
    _wait_for(logs)
    assert not state.follow_active
