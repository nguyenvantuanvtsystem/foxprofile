from collections.abc import Callable

import flet as ft

from ...core.strings import get_string
from ...interfaces.protocols import IBrowserLauncher, IProfileManager
from ...services.profile.extensions import (
    attached_ids,
    pin_extensions,
    save_upload,
    validate_ext_dir,
)
from ..theme.colors import COLORS, FONT_DATA, FONT_SEMIBOLD
from ..theme.styles import ACCENT_STYLE, DANGER_ICON_STYLE, OUTLINE_STYLE


def manage_extensions(
    page: ft.Page,
    name: str,
    file_picker: ft.FilePicker,
    pm: IProfileManager,
    bl: IBrowserLauncher,
    log: Callable[[str], None],
    refresh: Callable[[], None],
) -> None:
    profile = pm.profiles.get(name)
    if not profile:
        return
    if profile.engine != "chrome":
        log(get_string("ext_chrome_only"))
    running = bl.is_running(name)

    status = ft.Text("", size=12, visible=False)
    path_field = ft.TextField(
        hint_text=get_string("ext_path_hint"),
        text_style=ft.TextStyle(font_family=FONT_DATA, size=13),
        expand=True,
    )
    ext_list = ft.Column(spacing=4, tight=True)

    def show(msg: str, ok: bool) -> None:
        status.value = msg
        status.color = COLORS["success"] if ok else COLORS["error"]
        status.visible = True
        page.update()

    def rebuild() -> None:
        prof = pm.profiles.get(name)
        exts = list(prof.extensions) if prof else []
        if not exts:
            ext_list.controls = [
                ft.Text(get_string("ext_empty"), size=12.5, color=COLORS["text_dim"])
            ]
        else:
            rows = []
            for ext in exts:
                rows.append(
                    ft.Row(
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Text(
                                ext,
                                size=12,
                                font_family=FONT_DATA,
                                expand=True,
                                color=COLORS["text_main"],
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_size=17,
                                tooltip=get_string("delete"),
                                style=DANGER_ICON_STYLE,
                                on_click=lambda _, e=ext: do_detach(e),
                            ),
                        ],
                    )
                )
            ext_list.controls = rows
        page.update()

    def do_detach(ext: str) -> None:
        if pm.detach_extension(name, ext):
            log(get_string("ext_detached"))
            rebuild()
            refresh()
        page.update()

    def do_add(_: ft.ControlEvent) -> None:
        path = (path_field.value or "").strip()
        ok, err = validate_ext_dir(path)
        if not ok:
            show(err, False)
            return
        good, msg = pm.attach_extension(name, path)
        if not good:
            show(msg, False)
            return
        path_field.value = ""
        log(get_string("ext_attached", path=msg))
        rebuild()
        refresh()

    async def do_upload() -> None:
        files = await file_picker.pick_files(
            dialog_title=get_string("ext_upload"),
            allowed_extensions=["zip"],
            allow_multiple=False,
        )
        if not files:
            return
        picked = files[0]
        try:
            with open(picked.path, "rb") as f:
                data = f.read()
        except OSError as e:
            show(str(e), False)
            return
        good, result = save_upload(name, picked.name, data)
        if not good:
            show(result, False)
            return
        attached, msg = pm.attach_extension(name, result)
        if not attached:
            show(msg, False)
            return
        log(get_string("ext_attached", path=msg))
        rebuild()
        refresh()

    def do_upload_click(_: ft.ControlEvent) -> None:
        page.run_task(do_upload)

    def do_pin(_: ft.ControlEvent) -> None:
        import os

        from ...core.config import DATA_DIR

        prof = pm.profiles.get(name)
        if not prof or not prof.extensions:
            show(get_string("ext_empty"), False)
            return
        profile_dir = os.path.join(os.getcwd(), DATA_DIR, name)
        ids = attached_ids(profile_dir, prof.extensions)
        missing = [p for p, i in ids.items() if not i]
        if missing:
            show(missing[0], False)
            return
        good, msg = pin_extensions(profile_dir, list(ids.values()))
        show(
            get_string("ext_pinned", count=len(ids)) if good else msg,
            good,
        )
        if good:
            log(get_string("ext_pinned", count=len(ids)))

    dlg = ft.AlertDialog(
        modal=True,
        bgcolor=COLORS["card_bg"],
        shape=ft.RoundedRectangleBorder(radius=18),
        title=ft.Text(
            get_string("ext_title", name=name),
            size=17,
            font_family=FONT_SEMIBOLD,
            color=COLORS["text_main"],
        ),
        content=ft.Container(
            width=480,
            content=ft.Column(
                tight=True,
                spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.Text(get_string("ext_hint"), size=12, color=COLORS["text_dim"]),
                    ext_list,
                    ft.Row(
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            path_field,
                            ft.Button(
                                get_string("ext_add"),
                                icon=ft.Icons.ADD,
                                style=ACCENT_STYLE,
                                on_click=do_add,
                            ),
                        ],
                    ),
                    ft.Row(
                        controls=[
                            ft.OutlinedButton(
                                get_string("ext_upload"),
                                icon=ft.Icons.UPLOAD_FILE,
                                style=OUTLINE_STYLE,
                                on_click=do_upload_click,
                            ),
                            ft.OutlinedButton(
                                get_string("ext_pin"),
                                icon=ft.Icons.PUSH_PIN_OUTLINED,
                                style=OUTLINE_STYLE,
                                disabled=running,
                                tooltip=get_string("ext_stop_first", name=name) if running else "",
                                on_click=do_pin,
                            ),
                        ]
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
    rebuild()
    page.show_dialog(dlg)
