import contextlib
import threading
from collections.abc import Callable

import flet as ft

from ...core.strings import get_string
from ...interfaces.protocols import IBrowserLauncher
from ...services.sync_ops import fan_out
from ..theme.colors import COLORS, FONT_DATA, FONT_SEMIBOLD
from ..theme.styles import ACCENT_STYLE, OUTLINE_STYLE


def open_sync_dialog(
    page: ft.Page,
    names: list[str],
    bl: IBrowserLauncher,
    log: Callable[[str], None],
) -> None:
    """Broadcast one action to ticked running profiles."""
    picked: set[str] = set(names)
    status = ft.Text("", size=12, visible=False)
    url_field = ft.TextField(
        hint_text="https://...",
        text_style=ft.TextStyle(font_family=FONT_DATA, size=13),
        expand=True,
    )
    text_field = ft.TextField(
        hint_text="...",
        text_style=ft.TextStyle(font_family=FONT_DATA, size=13),
        expand=True,
    )
    x_field = ft.TextField(value="300", width=90, text_style=_DATA)
    y_field = ft.TextField(value="300", width=90, text_style=_DATA)
    busy = {"on": False}

    def show(msg: str, ok: bool) -> None:
        status.value = msg
        status.color = COLORS["success"] if ok else COLORS["error"]
        status.visible = True
        with contextlib.suppress(Exception):
            page.update()

    def run(action: str, params: dict) -> None:
        if busy["on"]:
            return
        targets = [n for n in names if n in picked and bl.is_running(n)]
        if not targets:
            show(get_string("sync_need_running"), False)
            return
        busy["on"] = True
        show("...", True)

        def work() -> None:
            try:
                results = fan_out(bl, targets, action, params)
                ok = sum(1 for r in results if r["ok"])
                show(get_string("sync_result", ok=ok, total=len(results)), ok == len(results))
                for r in results:
                    if not r["ok"]:
                        log(f"[{r['name']}] {r['error']}")
            finally:
                busy["on"] = False

        threading.Thread(target=work, daemon=True).start()

    target_checks = ft.Column(
        spacing=0,
        tight=True,
        scroll=ft.ScrollMode.AUTO,
        height=min(32 * len(names), 160),
        controls=[
            ft.Checkbox(
                label=n,
                value=True,
                on_change=lambda e, n=n: (
                    picked.discard(n) if not e.control.value else picked.add(n)
                ),
            )
            for n in names
        ],
    )

    dlg = ft.AlertDialog(
        modal=True,
        bgcolor=COLORS["card_bg"],
        shape=ft.RoundedRectangleBorder(radius=18),
        title=ft.Text(
            get_string("sync_title", count=len(names)),
            size=17,
            font_family=FONT_SEMIBOLD,
            color=COLORS["text_main"],
        ),
        content=ft.Container(
            width=480,
            content=ft.Column(
                tight=True,
                spacing=10,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.Text(get_string("sync_targets"), size=12.5, color=COLORS["text_sub"]),
                    target_checks,
                    ft.Row(
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            url_field,
                            ft.Button(
                                get_string("sync_open_url"),
                                style=ACCENT_STYLE,
                                on_click=lambda _: (
                                    run("navigate", {"url": (url_field.value or "").strip()})
                                    if (url_field.value or "").strip()
                                    else show("https://...", False)
                                ),
                            ),
                        ],
                    ),
                    ft.Row(
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            text_field,
                            ft.Button(
                                get_string("sync_type"),
                                style=ACCENT_STYLE,
                                on_click=lambda _: run(
                                    "keyboard_type", {"text": text_field.value or ""}
                                ),
                            ),
                        ],
                    ),
                    ft.Row(
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.OutlinedButton(
                                get_string("sync_enter"),
                                style=OUTLINE_STYLE,
                                on_click=lambda _: run("press", {"key": "Enter"}),
                            ),
                            x_field,
                            y_field,
                            ft.OutlinedButton(
                                get_string("sync_click"),
                                style=OUTLINE_STYLE,
                                on_click=lambda _: run(
                                    "click_at",
                                    {
                                        "x": _num(x_field.value),
                                        "y": _num(y_field.value),
                                    },
                                ),
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
    page.show_dialog(dlg)


_DATA = ft.TextStyle(font_family=FONT_DATA, size=13)


def _num(value: str | None) -> float:
    try:
        return float((value or "").strip())
    except ValueError:
        return 0
