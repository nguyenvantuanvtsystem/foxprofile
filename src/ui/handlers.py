"""Event handlers extracted from App for Single Responsibility compliance."""

from collections.abc import Callable

import flet as ft

from ..core.strings import get_string
from ..interfaces.protocols import IBrowserLauncher, IProfileManager, IProxyService
from ..services.window_tile import APP_NAMES, arrange_windows, compute_rects
from .actions.browser import launch_or_stop
from .actions.bulk import bulk_delete_profiles, bulk_launch_profiles, bulk_stop_profiles
from .actions.cookies import manage_cookies
from .actions.profile import add_profile, delete_profile, edit_profile
from .actions.transfer import export_profile, import_profile
from .dialogs import open_log_dialog
from .dialogs.device import manage_device
from .dialogs.ext_bulk import open_bulk_extension_dialog
from .dialogs.extensions import manage_extensions
from .dialogs.sync import open_sync_dialog
from .refs import UIRefs
from .state import AppState


class AppHandlers:
    """Decoupled event-handler object wired to the App's dependencies."""

    def __init__(
        self,
        pm: IProfileManager,
        bl: IBrowserLauncher,
        ps: IProxyService,
        state: AppState,
        get_page: Callable[[], ft.Page | None],
        get_refs: Callable[[], UIRefs | None],
        log_fn: Callable[[str], None],
        refresh_fn: Callable[[], None],
        get_page_profiles: Callable[[], tuple],
    ) -> None:
        self._pm = pm
        self._bl = bl
        self._ps = ps
        self._state = state
        self._get_page = get_page
        self._get_refs = get_refs
        self._log = log_fn
        self._refresh = refresh_fn
        self._get_page_profiles = get_page_profiles

    def on_launch(self, name: str) -> None:
        launch_or_stop(name, self._pm, self._bl, self._state, self._log)

    def on_delete(self, name: str) -> None:
        page = self._get_page()
        assert page is not None
        delete_profile(page, name, self._pm, self._log, self._refresh)

    def on_edit(self, name: str) -> None:
        page = self._get_page()
        assert page is not None
        edit_profile(
            page,
            name,
            self._pm,
            self._bl,
            self._ps,
            self._log,
            self._refresh,
        )

    def on_cookies(self, name: str) -> None:
        page = self._get_page()
        refs = self._get_refs()
        assert page is not None and refs is not None
        manage_cookies(page, name, refs.file_picker, self._pm, self._bl, self._log)

    def on_extensions(self, name: str) -> None:
        page = self._get_page()
        refs = self._get_refs()
        assert page is not None and refs is not None
        manage_extensions(
            page, name, refs.file_picker, self._pm, self._bl, self._log, self._refresh
        )

    def on_device(self, name: str) -> None:
        page = self._get_page()
        assert page is not None
        manage_device(page, name, self._pm, self._bl, self._log, self._refresh)

    def open_add_dialog(self) -> None:
        page = self._get_page()
        assert page is not None
        add_profile(page, self._pm, self._ps, self._log, self._refresh)

    async def on_import(self, _: ft.ControlEvent | None = None) -> None:
        refs = self._get_refs()
        assert refs is not None
        await import_profile(refs.file_picker, self._pm, self._log, self._refresh)

    def on_export_open(self) -> None:
        page = self._get_page()
        refs = self._get_refs()
        assert page is not None and refs is not None
        export_profile(page, refs.file_picker, self._pm, self._log)

    # --- Selection handlers ---

    def on_toggle_select(self, name: str) -> None:
        self._state.toggle_selection(name)
        self._state.schedule_refresh()

    def on_select_all_page(self) -> None:
        _, page_profiles, _ = self._get_page_profiles()
        self._state.select_all([p.name for p in page_profiles])
        self._state.schedule_refresh()

    def on_deselect_page(self) -> None:
        _, page_profiles, _ = self._get_page_profiles()
        for p in page_profiles:
            if self._state.is_selected(p.name):
                self._state.toggle_selection(p.name)
        self._state.schedule_refresh()

    def on_clear_selection(self) -> None:
        self._state.clear_selection()
        self._state.schedule_refresh()

    # --- Bulk action handlers ---

    def on_bulk_delete(self) -> None:
        page = self._get_page()
        assert page is not None
        selected = self._state.selected_names()
        # Like the web panel and the API: a running profile is never deleted.
        if running := [n for n in selected if self._bl.is_running(n)]:
            self._log(get_string("bulk_skip_running", count=len(running)))
        if names := [n for n in selected if not self._bl.is_running(n)]:
            bulk_delete_profiles(
                page,
                names,
                self._pm,
                self._log,
                self._refresh,
                on_done=self._state.clear_selection,
            )

    def on_bulk_launch(self) -> None:
        if names := list(self._state.selected_names()):
            bulk_launch_profiles(names, self._pm, self._bl, self._state, self._log)

    def on_bulk_stop(self) -> None:
        if names := list(self._state.selected_names()):
            bulk_stop_profiles(names, self._pm, self._bl, self._state, self._log)

    def on_bulk_launch_tile(self) -> None:

        from .components.bulk_bar import tile_layout

        if not (names := sorted(self._state.selected_names())):
            return
        self._launch_tiled(names, tile_layout())

    def _launch_tiled(self, names: list[str], layout: str) -> None:
        import threading

        from ..services.window_tile import compute_rects

        try:
            rect_list = compute_rects(len(names), layout)
            rects = {name: rect_list[i] for i, name in enumerate(names)}
        except OSError:
            rects = {}
        bulk_launch_profiles(names, self._pm, self._bl, self._state, self._log, rects)

        def wait_and_tile() -> None:
            import time

            deadline = time.time() + 120
            while time.time() < deadline:
                if all(self._bl.is_running(n) for n in names):
                    break
                time.sleep(2)
            running = [n for n in names if self._bl.is_running(n)]
            if not running:
                self._log(get_string("tile_no_running"))
                return
            arranged = 0
            try:
                arranged = self._arrange_names(running, layout)
            except OSError:
                # Already tiled by launch positions; fine-tuning needs access.
                arranged = len(running)
            ok = len([n for n in names if self._bl.is_running(n)])
            self._log(get_string("tile_launched", ok=ok, total=len(names), arranged=arranged))
            self._refresh()

        threading.Thread(target=wait_and_tile, daemon=True).start()

    def _arrange_names(self, names: list[str], layout: str) -> int:
        by_app: dict[str, list[str]] = {}
        for n in names:
            profile = self._pm.profiles.get(n)
            if profile is None:
                continue
            by_app.setdefault(APP_NAMES.get(profile.engine, "Chromium"), []).append(n)
        count = 0
        for app, group in by_app.items():
            arrange_windows(app, compute_rects(len(group), layout))
            count += len(group)
        return count

    def on_bulk_arrange(self) -> None:
        import threading

        from ..services.window_tile import is_permission_error
        from .components.bulk_bar import tile_layout

        running = [n for n in self._state.selected_names() if self._bl.is_running(n)]
        if not running:
            running = sorted(self._bl.running_profile_names())
        if not running:
            self._log(get_string("tile_no_running"))
            return
        layout = tile_layout()
        try:
            count = self._arrange_names(running, layout)
        except OSError as e:
            if not is_permission_error(e):
                self._log(str(e))
                return
            # No permission to move live windows: stop and re-open them
            # directly into the grid (tabs restore themselves).
            self._log(get_string("tile_relaunching", count=len(running)))
            names = sorted(running)

            def relaunch() -> None:
                for n in names:
                    if self._bl.is_running(n):
                        self._launch_stop_quiet(n)
                self._launch_tiled(names, layout)

            threading.Thread(target=relaunch, daemon=True).start()
            return
        self._log(get_string("tile_arranged", count=count))

    def _launch_stop_quiet(self, name: str) -> None:
        import contextlib

        with contextlib.suppress(Exception):
            self._bl.stop_profile(name)

    def on_bulk_sync(self) -> None:
        page = self._get_page()
        assert page is not None
        selected = list(self._state.selected_names())
        names = [n for n in selected if self._bl.is_running(n)]
        if not names:
            names = sorted(self._bl.running_profile_names())
        if not names:
            self._log(get_string("sync_need_running"))
            return
        open_sync_dialog(page, names, self._bl, self._log)

    def on_bulk_follow(self) -> None:
        """One-tap follow: first tap starts, second tap stops.

        Master is the first-ticked running profile (or the first running
        one when nothing is ticked); the rest mirror it.
        """
        import threading

        from ..services.follow_toggle import pick_follow_group
        from .dialogs.follow import mirror_start, mirror_status, mirror_stop

        def work() -> None:
            try:
                if mirror_status().get("active"):
                    mirror_stop()
                    self._state.follow_active = False
                    self._state.follow_master = ""
                    self._log(get_string("follow_stopped"))
                    self._refresh()
                    return
            except Exception as e:  # noqa: BLE001 - report, don't crash the toggle
                self._log(str(e)[:200])
                return
            running = sorted(self._bl.running_profile_names())
            if not running:
                self._log(get_string("sync_need_running"))
                return
            group = pick_follow_group(self._state.selection_order(), running)
            if group is None:
                self._log(get_string("follow_need_two"))
                return
            master, followers = group
            try:
                mirror_start(master, followers)
            except Exception as e:  # noqa: BLE001 - report, don't crash the toggle
                self._log(str(e)[:200])
                return
            self._state.follow_active = True
            self._state.follow_master = master
            self._log(get_string("follow_active", master=master, count=len(followers)))
            self._refresh()

        threading.Thread(target=work, daemon=True).start()

    def on_bulk_ext_install(self) -> None:
        page = self._get_page()
        assert page is not None
        selected = sorted(self._state.selected_names())
        names = selected or sorted(self._pm.profiles.keys())
        if not names:
            self._log(get_string("ext_bulk_none"))
            return
        open_bulk_extension_dialog(page, names, self._pm, self._log, self._refresh)

    # --- Log handlers ---

    def toggle_log(self) -> None:
        page = self._get_page()
        refs = self._get_refs()
        assert refs is not None and page is not None
        self._state.log_collapsed = not self._state.log_collapsed
        has_content = bool(refs.log_text.value)
        refs.log_column.visible = has_content and not self._state.log_collapsed
        refs.log_toggle_btn.icon = (
            ft.Icons.KEYBOARD_ARROW_RIGHT
            if self._state.log_collapsed
            else ft.Icons.KEYBOARD_ARROW_DOWN
        )
        page.update()

    def open_log_fullscreen(self) -> None:
        page = self._get_page()
        assert page is not None
        open_log_dialog(page, self._state.get_all_log_lines())
