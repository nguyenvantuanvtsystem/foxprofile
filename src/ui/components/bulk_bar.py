from collections.abc import Callable

import flet as ft

from ...core.strings import get_string
from ...models.profile import Profile
from ..state import AppState
from ..theme.colors import COLORS, FONT_SEMIBOLD
from ..theme.styles import ACCENT_STYLE, OUTLINE_STYLE

BulkCallbacks = dict[str, Callable[[], None]]

_TILE_LAYOUTS = ("auto", "1x2", "2x2", "3x2", "3x3")
_layout_value = "auto"


def tile_layout() -> str:
    """Layout picked in the bulk bar, shared with the arrange handlers."""
    return _layout_value


def _set_layout(value: str) -> None:
    global _layout_value
    _layout_value = value if value in _TILE_LAYOUTS else "auto"


def rebuild_bulk_bar(
    bulk_bar: ft.Row,
    state: AppState,
    page_profiles: list[Profile],
    cbs: BulkCallbacks,
) -> None:
    count = len(state.selected_names())
    bulk_bar.visible = True
    bulk_bar.controls = [_build_container(count, cbs, state.follow_active)]


def _build_container(count: int, cbs: BulkCallbacks, follow_active: bool = False) -> ft.Container:
    def btn(label: str, icon: str, key: str, style: ft.ButtonStyle) -> ft.Control:
        cls = ft.Button if style is ACCENT_STYLE else ft.OutlinedButton
        return cls(label, icon=icon, height=32, style=style, on_click=lambda _: cbs[key]())

    layout = ft.Dropdown(
        value=_layout_value,
        options=[ft.dropdown.Option(v, v) for v in _TILE_LAYOUTS],
        height=32,
        text_size=13,
        tooltip=get_string("layout_label"),
        on_select=lambda e: _set_layout(e.control.value),
    )
    # Selection tools hide when nothing is ticked; tiling + sync stay
    # visible so they are discoverable without any selection.
    selection_ctls: list[ft.Control] = []
    if count:
        selection_ctls = [
            btn(get_string("launch"), ft.Icons.PLAY_ARROW_ROUNDED, "launch", ACCENT_STYLE),
            btn(get_string("stop"), ft.Icons.STOP_ROUNDED, "stop", OUTLINE_STYLE),
            btn(get_string("delete"), ft.Icons.DELETE_OUTLINE, "delete", OUTLINE_STYLE),
        ]
    return ft.Container(
        expand=True,
        bgcolor=COLORS["paper_sunk"],
        padding=ft.Padding.symmetric(horizontal=14, vertical=9),
        border=ft.Border.only(bottom=ft.BorderSide(1, COLORS["card_border"])),
        content=ft.Row(
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Text(
                    get_string("selected_count", count=count),
                    size=13.5,
                    font_family=FONT_SEMIBOLD,
                    color=COLORS["text_main"],
                ),
                ft.Container(width=6),
                *selection_ctls,
                layout,
                btn(
                    get_string("bulk_launch_tile"),
                    ft.Icons.GRID_VIEW_ROUNDED,
                    "launch_tile",
                    OUTLINE_STYLE,
                ),
                btn(
                    get_string("bulk_arrange"),
                    ft.Icons.DASHBOARD_CUSTOMIZE_OUTLINED,
                    "arrange",
                    OUTLINE_STYLE,
                ),
                btn(
                    get_string("bulk_sync"),
                    ft.Icons.SYNC_ROUNDED,
                    "sync",
                    OUTLINE_STYLE,
                ),
                btn(
                    get_string("bulk_follow"),
                    ft.Icons.VISIBILITY_ROUNDED,
                    "follow",
                    ACCENT_STYLE if follow_active else OUTLINE_STYLE,
                ),
                btn(
                    get_string("bulk_ext_install"),
                    ft.Icons.DOWNLOAD_ROUNDED,
                    "ext_install",
                    OUTLINE_STYLE,
                ),
                ft.Container(expand=True),
                *(
                    [
                        ft.TextButton(
                            get_string("clear"),
                            on_click=lambda _: cbs["clear"](),
                            style=ft.ButtonStyle(color=COLORS["text_sub"]),
                        )
                    ]
                    if count
                    else []
                ),
            ],
        ),
    )
