from collections.abc import Callable

import flet as ft

from ...core.strings import get_string
from ...interfaces.protocols import IProfileManager
from ...services.profile.extensions import validate_ext_dir
from ..theme.colors import COLORS, FONT_DATA, FONT_SEMIBOLD
from ..theme.styles import ACCENT_STYLE


def open_bulk_extension_dialog(
    page: ft.Page,
    names: list[str],
    pm: IProfileManager,
    log: Callable[[str], None],
    refresh: Callable[[], None],
) -> None:
    """Point at one unpacked extension dir; it is attached to every name."""
    import contextlib
    import threading

    status = ft.Text("", size=12, visible=False)
    path_field = ft.TextField(
        hint_text=get_string("ext_path_hint"),
        text_style=ft.TextStyle(font_family=FONT_DATA, size=13),
        expand=True,
    )
    busy = {"on": False}

    def show(msg: str, ok: bool) -> None:
        status.value = msg
        status.color = COLORS["success"] if ok else COLORS["error"]
        status.visible = True
        with contextlib.suppress(Exception):
            page.update()

    def do_install(_: ft.ControlEvent) -> None:
        if busy["on"]:
            return
        path = (path_field.value or "").strip()
        ok, err = validate_ext_dir(path)
        if not ok:
            show(err, False)
            return
        busy["on"] = True

        def work() -> None:
            try:
                done, failed = 0, []
                for name in names:
                    good, msg = pm.attach_extension(name, path)
                    if good:
                        done += 1
                    else:
                        failed.append(f"{name} ({msg})")
                log(get_string("ext_bulk_done", ok=done, total=len(names)))
                for f in failed:
                    log(f)
                show(get_string("ext_bulk_done", ok=done, total=len(names)), done == len(names))
                refresh()
            finally:
                busy["on"] = False

        threading.Thread(target=work, daemon=True).start()

    dlg = ft.AlertDialog(
        modal=True,
        bgcolor=COLORS["card_bg"],
        shape=ft.RoundedRectangleBorder(radius=18),
        title=ft.Text(
            get_string("ext_bulk_title", count=len(names)),
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
                    ft.Text(get_string("ext_bulk_hint"), size=12, color=COLORS["text_dim"]),
                    ft.Row(
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            path_field,
                            ft.Button(
                                get_string("ext_bulk_install"),
                                icon=ft.Icons.DOWNLOAD_ROUNDED,
                                style=ACCENT_STYLE,
                                on_click=do_install,
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
