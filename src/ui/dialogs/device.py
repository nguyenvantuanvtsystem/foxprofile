import contextlib
import threading
from collections.abc import Callable

import flet as ft

from ...core.strings import get_string
from ...interfaces.protocols import IBrowserLauncher, IProfileManager
from ..theme.colors import COLORS, FONT_DATA, FONT_SEMIBOLD
from ..theme.styles import ACCENT_STYLE, OUTLINE_STYLE


def manage_device(
    page: ft.Page,
    name: str,
    pm: IProfileManager,
    bl: IBrowserLauncher,
    log: Callable[[str], None],
    refresh: Callable[[], None],
) -> None:
    """View and change the stable device a Chrome profile presents."""
    import os

    from chrome_engine import persona as chrome_persona

    from ...core.config import DATA_DIR

    profile = pm.profiles.get(name)
    if not profile or profile.engine != "chrome":
        return
    stopped = not bl.is_running(name)
    status = ft.Text("", size=12, visible=False)

    def profile_dir() -> str:
        return os.path.join(os.getcwd(), DATA_DIR, name)

    def current() -> dict:
        p = chrome_persona.load(profile_dir())
        return p.to_json() if p else {}

    dev = current()
    brand_drop = ft.Dropdown(
        value=dev.get("brand", "Chrome"),
        options=[ft.dropdown.Option("Chrome", "Chrome"), ft.dropdown.Option("Edge", "Edge")],
        width=200,
        disabled=not stopped,
    )
    version_field = ft.TextField(
        value=dev.get("platform_version", ""),
        text_style=ft.TextStyle(font_family=FONT_DATA, size=13),
        width=140,
        disabled=not stopped,
    )
    cores_field = ft.Dropdown(
        value=str(dev.get("hardware_concurrency", 8)),
        options=[
            ft.dropdown.Option(str(c), str(c)) for c in (2, 4, 6, 8, 10, 12, 14, 16, 20, 24, 32)
        ],
        width=140,
        disabled=not stopped,
    )
    ua_field = ft.TextField(
        value=dev.get("user_agent") or "",
        hint_text=get_string("device_ua_hint"),
        text_style=ft.TextStyle(font_family=FONT_DATA, size=12),
        expand=True,
        disabled=not stopped,
    )
    from ...services.ua_store import list_uas

    _presets = [("", get_string("device_ua_custom"))] + [(ua, label) for label, ua in list_uas()]
    ua_preset = ft.Dropdown(
        value="",
        options=[ft.dropdown.Option(key=v, text=t) for v, t in _presets],
        width=280,
        disabled=not stopped,
    )

    def on_ua_preset(_: ft.ControlEvent) -> None:
        if ua_preset.value:
            ua_field.value = ua_preset.value
            page.update()

    ua_preset.on_select = on_ua_preset
    webrtc_drop = ft.Dropdown(
        value=dev.get("webrtc", "proxy"),
        options=[
            ft.dropdown.Option("proxy", get_string("device_webrtc_proxy")),
            ft.dropdown.Option("public", get_string("device_webrtc_public")),
        ],
        width=260,
        disabled=not stopped,
    )
    geo_drop = ft.Dropdown(
        value=dev.get("geo", "ask"),
        options=[
            ft.dropdown.Option("ask", get_string("device_geo_ask")),
            ft.dropdown.Option("allow", get_string("device_geo_allow")),
            ft.dropdown.Option("block", get_string("device_geo_block")),
        ],
        width=260,
        disabled=not stopped,
    )
    seed_text = ft.Text(
        get_string("device_seed", seed=dev.get("seed", "-")),
        size=12.5,
        font_family=FONT_DATA,
        color=COLORS["text_main"],
    )

    def show(msg: str, ok: bool) -> None:
        status.value = msg
        status.color = COLORS["success"] if ok else COLORS["error"]
        status.visible = True
        with contextlib.suppress(Exception):
            page.update()

    def do_save(_: ft.ControlEvent) -> None:
        try:
            cores = int(cores_field.value or 8)
        except ValueError:
            show(get_string("device_bad_cores"), False)
            return
        try:
            fresh = chrome_persona.update_fields(
                profile_dir(),
                brand=brand_drop.value,
                platform_version=(version_field.value or "").strip(),
                hardware_concurrency=cores,
                user_agent=(ua_field.value or "").strip(),
                webrtc=webrtc_drop.value,
                geo=geo_drop.value,
            )
        except chrome_persona.PersonaError as e:
            show(str(e), False)
            return
        seed_text.value = get_string("device_seed", seed=fresh.seed)
        log(get_string("device_saved", name=name))
        show(get_string("device_saved", name=name), True)
        refresh()

    def do_regen(_: ft.ControlEvent) -> None:
        def work() -> None:
            try:
                fresh = chrome_persona.regenerate_seed(profile_dir())
            except chrome_persona.PersonaError as e:
                show(str(e), False)
                return
            seed_text.value = get_string("device_seed", seed=fresh.seed)
            log(get_string("device_regenerated", name=name))
            show(get_string("device_regenerated", name=name), True)
            refresh()

        threading.Thread(target=work, daemon=True).start()

    dlg = ft.AlertDialog(
        modal=True,
        bgcolor=COLORS["card_bg"],
        shape=ft.RoundedRectangleBorder(radius=18),
        title=ft.Text(
            get_string("device_title", name=name),
            size=17,
            font_family=FONT_SEMIBOLD,
            color=COLORS["text_main"],
        ),
        content=ft.Container(
            width=560,
            content=ft.Column(
                tight=True,
                spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.Text(get_string("device_hint"), size=12, color=COLORS["text_dim"]),
                    seed_text,
                    ft.Row(
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            _lab(get_string("device_brand")),
                            brand_drop,
                            _lab(get_string("device_version")),
                            version_field,
                        ],
                    ),
                    ft.Row(
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            _lab(get_string("device_cores")),
                            cores_field,
                        ],
                    ),
                    _lab(get_string("device_ua")),
                    ft.Row(spacing=8, controls=[ua_preset, ua_field]),
                    ft.Row(spacing=10, controls=[_lab(get_string("device_webrtc")), webrtc_drop]),
                    ft.Row(spacing=10, controls=[_lab(get_string("device_geo")), geo_drop]),
                    ft.Row(
                        spacing=8,
                        controls=[
                            ft.Button(
                                get_string("save_changes"),
                                icon=ft.Icons.SAVE,
                                style=ACCENT_STYLE,
                                disabled=not stopped,
                                on_click=do_save,
                            ),
                            ft.OutlinedButton(
                                get_string("device_regen"),
                                icon=ft.Icons.REFRESH_ROUNDED,
                                style=OUTLINE_STYLE,
                                disabled=not stopped,
                                tooltip=get_string("device_regen_hint"),
                                on_click=do_regen,
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


def _lab(text: str) -> ft.Text:
    return ft.Text(text, size=12.5, color=COLORS["text_sub"])
