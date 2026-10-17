import contextlib
import json
import threading
import urllib.request
from collections.abc import Callable

import flet as ft

from ...core.config import API_PORT
from ...core.strings import get_string
from ..theme.colors import COLORS, FONT_SEMIBOLD
from ..theme.styles import ACCENT_STYLE, OUTLINE_STYLE

_BASE = f"http://127.0.0.1:{API_PORT}/api/v1/browser/mirror"


def _api(method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload or {}).encode() if payload is not None else None
    req = urllib.request.Request(
        _BASE + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"{}")


def mirror_status() -> dict:
    """Current follow session, e.g. {"active": False} when off."""
    return _api("GET", "/status")


def mirror_start(master: str, followers: list[str]) -> dict:
    return _api("POST", "/start", {"master": master, "followers": followers})


def mirror_stop() -> dict:
    return _api("POST", "/stop", {})


def open_follow_dialog(
    page: ft.Page,
    running: list[str],
    log: Callable[[str], None],
    refresh: Callable[[], None],
) -> None:
    """Pick a master; its clicks/typing/scroll/navigations mirror to the rest."""
    status = ft.Text("", size=12, visible=False)
    master_drop = ft.Dropdown(
        value=running[0] if running else None,
        options=[ft.dropdown.Option(n, n) for n in running],
        width=260,
    )
    followers_text = ft.Text("", size=12, color=COLORS["text_sub"])
    busy = {"on": False}

    def show(msg: str, ok: bool) -> None:
        status.value = msg
        status.color = COLORS["success"] if ok else COLORS["error"]
        status.visible = True
        with contextlib.suppress(Exception):
            page.update()

    def current_status() -> None:
        try:
            s = _api("GET", "/status")
            if s.get("active"):
                show(
                    get_string(
                        "follow_active",
                        master=s.get("master"),
                        count=len(s.get("followers", [])),
                    ),
                    True,
                )
            else:
                show(get_string("follow_idle"), True)
        except Exception as e:  # noqa: BLE001 - status is best-effort
            show(str(e)[:200], False)

    def do_start(_: ft.ControlEvent) -> None:
        if busy["on"] or not master_drop.value:
            return
        busy["on"] = True

        def work() -> None:
            try:
                followers = [n for n in running if n != master_drop.value]
                _api("POST", "/start", {"master": master_drop.value, "followers": followers})
                log(get_string("follow_started", master=master_drop.value))
                show(
                    get_string("follow_active", master=master_drop.value, count=len(followers)),
                    True,
                )
                refresh()
            except Exception as e:  # noqa: BLE001 - report, don't crash the dialog
                show(str(e)[:200], False)
            finally:
                busy["on"] = False

        threading.Thread(target=work, daemon=True).start()

    def do_stop(_: ft.ControlEvent) -> None:
        def work() -> None:
            try:
                _api("POST", "/stop", {})
                log(get_string("follow_stopped"))
                show(get_string("follow_idle"), True)
                refresh()
            except Exception as e:  # noqa: BLE001 - report, don't crash the dialog
                show(str(e)[:200], False)

        threading.Thread(target=work, daemon=True).start()

    def on_master(_: ft.ControlEvent) -> None:
        rest = [n for n in running if n != master_drop.value]
        followers_text.value = get_string("follow_followers", names=", ".join(rest) or "-")
        with contextlib.suppress(Exception):
            page.update()

    master_drop.on_select = on_master
    on_master(None)  # type: ignore[arg-type]

    dlg = ft.AlertDialog(
        modal=True,
        bgcolor=COLORS["card_bg"],
        shape=ft.RoundedRectangleBorder(radius=18),
        title=ft.Text(
            get_string("follow_title"),
            size=17,
            font_family=FONT_SEMIBOLD,
            color=COLORS["text_main"],
        ),
        content=ft.Container(
            width=460,
            content=ft.Column(
                tight=True,
                spacing=10,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.Text(get_string("follow_hint"), size=12, color=COLORS["text_dim"]),
                    ft.Row(
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Text(get_string("follow_master"), size=13),
                            master_drop,
                        ],
                    ),
                    followers_text,
                    ft.Row(
                        spacing=8,
                        controls=[
                            ft.Button(
                                get_string("follow_start"),
                                icon=ft.Icons.PLAY_ARROW_ROUNDED,
                                style=ACCENT_STYLE,
                                on_click=do_start,
                            ),
                            ft.OutlinedButton(
                                get_string("follow_stop"),
                                icon=ft.Icons.STOP_ROUNDED,
                                style=OUTLINE_STYLE,
                                on_click=do_stop,
                            ),
                        ],
                    ),
                    status,
                ],
            ),
        ),
        actions=[
            ft.TextButton(
                get_string("close_btn"),
                style=ft.ButtonStyle(color=COLORS["text_sub"]),
                on_click=lambda _: page.pop_dialog(),
            ),
        ],
    )
    current_status()
    page.show_dialog(dlg)
