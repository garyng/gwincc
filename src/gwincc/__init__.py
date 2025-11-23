import ctypes
from functools import partial
import os
from pathlib import Path
import sys
from time import sleep
from typing import Callable, Generic, TypeVar

import rapidfuzz
from imgui_bundle import ImVec2, hello_imgui, imgui, imgui_ctx, immapp, glfw_utils

from gwincc.imgui_ex import get_window_viewport_platform_hwnd, set_item_tooltip_no_delay
from gwincc.models import Monitor, Rect, Window
from gwincc.services import GetWindowsBackgroundService
from gwincc.state import WindowStateStore
import glfw
import keyboard
import win32gui
import logging
from functools import wraps
from typing import Any, Callable, TypeVar
import win32con

# todo: purge state


logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d) - %(message)s",
)

logger = logging.getLogger(__name__)


def bring_self_to_front(get_windows_background_service: GetWindowsBackgroundService):
    self = next(
        (x for x in get_windows_background_service.windows if x.pid == os.getpid()),
        None,
    )
    if not self:
        return

    print("bringing to front")

    # not sure why but doing this sometimes will fail
    # so we retry until it is succeeded

    for x in range(0, 30):
        try:
            self.bring_to_front()
            self.center()
            break
        except:
            print(f"failed to bring to front, retrying [{x}]")
            sleep(0.05)
            pass


class Startup:
    def _load_fonts(self, font_size=12.0):
        default_font = hello_imgui.load_font(
            "fonts/CascadiaCode-Regular.otf", font_size, hello_imgui.FontLoadingParams()
        )
        icon_fontg = hello_imgui.load_font(
            "fonts/fontawesome6/Font Awesome 6 Free-Solid-900.otf",
            font_size,
            hello_imgui.FontLoadingParams(merge_to_last_font=True),
        )

    def _setup_imgui_config(self):
        # ref: https://github.com/pthom/hello_imgui/blob/812a05d43f409bede0df37af54dba644e5861141/src/hello_imgui/impl/imgui_default_settings.cpp#L50
        io = imgui.get_io()
        # io.config_flags |= imgui.ConfigFlags_.docking_enable
        io.config_viewports_no_auto_merge = True
        # io.config_flags |= imgui.ConfigFlags_.nav_enable_keyboard

    def run(self):
        root_dir = Path(__file__).parent
        assets_dir = root_dir / "assets"
        self._get_windows_background_service = GetWindowsBackgroundService()
        self._get_windows_background_service.run()

        main_view = MainView(
            get_windows_background_service=self._get_windows_background_service
        )

        keyboard.add_hotkey("ctrl+f1", main_view.show)

        hello_imgui.set_assets_folder(assets_dir.as_posix())

        runner_params = hello_imgui.RunnerParams()

        # runner_params.imgui_window_params.default_imgui_window_type = (
        #     hello_imgui.DefaultImGuiWindowType.provide_full_screen_dock_space
        # )
        runner_params.imgui_window_params.enable_viewports = True

        runner_params.app_window_params.window_title = "gwincc"
        runner_params.callbacks.load_additional_fonts = self._load_fonts

        runner_params.app_window_params.restore_previous_geometry = True

        runner_params.callbacks.show_gui = main_view.render
        runner_params.callbacks.setup_imgui_config = self._setup_imgui_config

        runner_params.app_window_params.hidden = True

        immapp.run(runner_params=runner_params)

    def cleanup(self):
        self._get_windows_background_service.close()
        keyboard.unhook_all()


T = TypeVar("T")


class OneShotValue(Generic[T]):
    """
    Wraps a value that returns and resets to default afterwards.
    """

    def __init__(self, default: T) -> None:
        self._default = default
        self._value = self._default

    def set(self, value: T) -> None:
        self._value = value

    def read(self) -> T:
        value = self._value
        self._value = self._default
        return value

    def peek(self) -> T:
        return self._value


class StateChangeTracker(Generic[T]):
    def __init__(self, initial: T) -> None:
        self._previous = initial
        self._current = initial

        # todo: remove this if unused
        self._initial_oneshot: OneShotValue[T | None] = OneShotValue(None)
        self._initial_oneshot.set(initial)

    @property
    def value(self) -> T:
        return self._current

    @value.setter
    def value(self, value: T) -> None:
        self._previous = self._current
        self._current = value

    @property
    def changed(self) -> bool:
        return self._current != self._previous

    @property
    def initial_oneshot(self) -> T | None:
        return self._initial_oneshot.read()

    def __repr__(self) -> str:
        return (
            f"previous={self._previous} current={self._current} changed={self.changed}"
        )


class StateToggleTracker:
    """
    Keep track of a boolean state changes.
    `changed` is true when the state changes and reset to false after it has been read.
    Also provides the initial value that is reset to None after first read.
    """

    def __init__(self, initial: bool) -> None:
        self._previous = initial
        self._current = initial
        self._changed = OneShotValue(default=False)

        self._initial: OneShotValue[bool | None] = OneShotValue(None)
        self._initial.set(initial)

    @property
    def value(self) -> bool:
        return self._current

    @value.setter
    def value(self, value: bool) -> None:
        self._previous = self._current
        self._current = value
        self._changed.set(True)

    @property
    def changed(self) -> bool:
        return self._changed.read()

    @property
    def initial(self) -> bool | None:
        return self._initial.read()

    def __repr__(self) -> str:
        return f"initial={self._initial.peek()} previous={self._previous} current={self._current} changed={self._changed.peek()}"


F = TypeVar("F", bound=Callable[..., Any])


def log_call(func: F) -> F:
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger.info("called: %(func_name)s", {"func_name": func.__name__})
        return func(*args, **kwargs)

    return wrapper


class WindowVisibilityHandler:
    def __init__(self, initial_visibility=False) -> None:
        self.platform_window_hwnd: OneShotValue[int | None] = OneShotValue(None)
        self._request_show: OneShotValue[bool | None] = OneShotValue(None)
        self._visible: StateChangeTracker[bool] = StateChangeTracker(initial_visibility)

        self._request_resize: OneShotValue[bool | None] = OneShotValue(None)
        self._request_resize.set(initial_visibility)

    @property
    def visible(self):
        return self._visible.value

    @visible.setter
    def visible(self, value):
        self._visible.value = value

        if self._visible.changed:
            if self._visible.value:
                self._request_show.set(True)
                self._request_resize.set(True)

    @log_call
    def request_show(self):
        """Explicitly request to show"""
        self.visible = True
        self._request_show.set(True)
        self._request_resize.set(True)

    def should_handle_show_request(self):
        if not self._request_show.peek():
            return

        if not self.platform_window_hwnd.peek():
            return

        # reset request
        self._request_show.read()
        return True

    def should_resize(self):
        return self._request_resize.read()


class SearchBoxFocusHandler:

    def __init__(self) -> None:
        self.window_has_focus: StateChangeTracker[bool] = StateChangeTracker(False)

    def should_focus(self):
        return self.window_has_focus.changed and self.window_has_focus.value

class DefaultSearchBoxView:
    """
    A search box that has the input focus by default.
    """

    def __init__(self) -> None:
        self.window_has_focus: StateChangeTracker[bool] = StateChangeTracker(False)
        self.search_str = ""

    def render(self):
        imgui.text("search")
        imgui.same_line()

        # ref: https://github.com/ocornut/imgui/issues/5882
        self.window_has_focus.value = (
            imgui.get_window_viewport().flags & imgui.ViewportFlags_.is_focused > 0
        )

        if self.window_has_focus.changed and self.window_has_focus.value:
            imgui.set_keyboard_focus_here(0)

        _, self.search_str = imgui.input_text(
            "##search",
            self.search_str,
            imgui.InputTextFlags_.escape_clears_all
        )
        if imgui.is_key_pressed(imgui.Key.down_arrow):
            logger.info("down")

class MainView:
    focus_search_box: OneShotValue[bool] = OneShotValue(False)

    def __init__(self, get_windows_background_service) -> None:
        self._window_state_store = WindowStateStore()
        self._get_windows_background_service = get_windows_background_service

        self._visibility = WindowVisibilityHandler(initial_visibility=True)
        self._search_box = DefaultSearchBoxView()

    def show(self):
        self._visibility.request_show()

    def render(self) -> None:

        if not self._visibility.visible:
            return

        if self._visibility.should_resize():
            monitor_rect = Monitor.from_mouse_pos().work
            rect = Rect.from_width_height(
                monitor_rect.width() / 2, monitor_rect.height() / 2
            )
            rect = rect.center_inside(monitor_rect)
            imgui.set_next_window_size(ImVec2(rect.width(), rect.height()))
            imgui.set_next_window_pos(ImVec2(rect.left, rect.top))

        with imgui_ctx.begin(
            "gwincc", p_open=True, flags=imgui.WindowFlags_.no_collapse
        ) as window:
            if not window.opened:
                self._visibility.visible = False

            self._visibility.platform_window_hwnd.set(
                get_window_viewport_platform_hwnd()
            )
            # self._visibility.has_focus.set(imgui.get_window_viewport().flags & imgui.ViewportFlags_.is_focused > 0)

            if self._visibility.should_handle_show_request():
                Window.from_hwnd(hwnd=self._visibility.platform_window_hwnd.peek()).bring_to_front()

            # if imgui.button("close"):
            #     self.hide()

            # self._window_created.value = vp.platform_window_created

            # w = None

            # if self._window_created.value:
            #     ptr = platform_handle_raw_GetPointer(vp.platform_handle_raw, platform_handle_raw_GetName(vp.platform_handle_raw))
            #     w = Window.from_hwnd(ptr)

            # if w and ((self._window_created.changed and self._window_created.value) or (self._show.changed and self._show.value)):

            #     for x in range(0, 30):
            #         try:
            #             w.bring_to_front()
            #             w.center()
            #             break
            #         except:
            #             print(f"failed to bring to front, retrying [{x}]")
            #             sleep(0.05)
            #             pass

            #     # print(ptr, ctypes.c_void_p(ptr).value)

            # self.window_has_focus.value = imgui.get_window_viewport().flags & imgui.ViewportFlags_.is_focused > 0
            # if self.window_has_focus.changed:
            #     self._show.value = self.window_has_focus.value

            # self._render_search()

            self._search_box.render()

            self._render_windows()

        # imgui.separator_text("controls")

        # self._render_controls_group()

    def _scorer(self, query: str, window: Window, *, processor=None, score_cutoff=None):
        title = rapidfuzz.fuzz.WRatio(
            query, window.title, processor=lambda x: x.lower()
        )
        process = rapidfuzz.fuzz.WRatio(
            query, window.proc.name(), processor=lambda x: x.lower()
        )

        return 0.75 * title + 0.15 * process

    def _filter(self, windows: list[Window]):
        # always filter out self
        windows = [window for window in windows if window.pid != os.getpid()]

        if not self._search_box.search_str:
            return windows

        results = [
            window
            for window, score, index in rapidfuzz.process.extract(
                self._search_box.search_str,
                windows,
                scorer=self._scorer,
                limit=None,
            )
        ]

        return results

    def _sort(self, windows: list[Window]) -> list[Window]:
        def _sort_by_pinned_at(window: Window):
            state = self._window_state_store.get_or_none(window)

            if not state:
                return (1, None)
            if not state.pinned_at:
                return (1, None)
            # sort pinned items first
            return (0, state.pinned_at)

        return sorted(windows, key=_sort_by_pinned_at)

    def _apply_selection_requests(
        self, msio: imgui.MultiSelectIO, on_selection: Callable[[int, bool], None]
    ):
        for r in msio.requests:
            if r.type == imgui.SelectionRequestType.set_range:
                for idx in range(
                    r.range_first_item, r.range_last_item + 1, r.range_direction
                ):
                    on_selection(idx, r.selected)
            if r.type == imgui.SelectionRequestType.set_all:
                for idx in range(0, msio.items_count):
                    on_selection(idx, r.selected)

    def _render_windows(self):
        with imgui_ctx.begin_table(
            "windows",
            3,
            imgui.TableFlags_.resizable
            + imgui.TableFlags_.scroll_x
            + imgui.TableFlags_.scroll_y,
            # ImVec2(0, -5 * imgui.get_frame_height_with_spacing()),
        ):
            imgui.table_setup_scroll_freeze(0, 1)
            imgui.table_setup_column("##actions")
            imgui.table_setup_column("Title")
            imgui.table_setup_column("Process")
            imgui.table_headers_row()

            # if imgui.is_window_focused():
            #     pass
            # prepend the character typed into this table
            # for char in imgui.get_io().input_queue_characters:
            #     self.search_str += chr(char)
            # then focus to the search box
            # self.focus_search_box.set(True)

            windows = self._sort(
                self._filter(self._get_windows_background_service.windows)
            )

            def on_selection(idx: int, selected: bool):
                self._window_state_store[windows[idx]].selected = selected

            msio = imgui.begin_multi_select(
                imgui.MultiSelectFlags_.clear_on_escape
                # + imgui.MultiSelectFlags_.box_select2d,
                + imgui.MultiSelectFlags_.single_select,
                items_count=len(windows),  # used in set_all request
            )
            self._apply_selection_requests(msio=msio, on_selection=on_selection)

            for idx, window in enumerate(windows):
                state = self._window_state_store[window]
                with imgui_ctx.push_id(str(window.hwnd)):
                    imgui.table_next_row()

                    imgui.table_next_column()
                    if state.pinned_at:
                        if imgui.button("\ue68f", ImVec2(24, 0)):
                            state.unpin()
                        set_item_tooltip_no_delay("unpin")
                    else:
                        if imgui.button("\uf08d", ImVec2(24, 0)):
                            state.pin()
                        set_item_tooltip_no_delay("pin")

                    imgui.table_next_column()

                    imgui.set_next_item_selection_user_data(idx)
                    
                    clicked, selected = imgui.selectable(
                        label=window.title,
                        p_selected=state.selected,
                        flags=imgui.SelectableFlags_.span_all_columns
                        + imgui.SelectableFlags_.allow_double_click,
                    )
                    state.selected = selected
                    if clicked:
                        if imgui.is_mouse_double_clicked(
                            imgui.MouseButton_.left
                        ):
                            window.bring_to_front()
                        else:
                            imgui.open_popup("actions")

                    with imgui_ctx.begin_popup("actions") as actions_popup:
                        if actions_popup:
                            style = imgui.get_style()

                            with (
                                imgui_ctx.begin_group(),
                                imgui_ctx.begin_horizontal("actions"),
                                imgui_ctx.push_style_var(
                                    imgui.StyleVar_.item_spacing,
                                    ImVec2(style.item_spacing.y * 0.9, style.item_spacing.y),
                                ),
                                imgui_ctx.push_style_var(
                                    imgui.StyleVar_.frame_padding,
                                    ImVec2(style.frame_padding.y * 10, style.frame_padding.y * 2),
                                ),
                            ):
                                if imgui.button("\uf140"):
                                    window.bring_to_front()
                                set_item_tooltip_no_delay("bring to front")

                                if imgui.button("\ue4bd"):
                                    window.resize_and_center()
                                set_item_tooltip_no_delay("center")

                                if imgui.button("\uf0fe"):
                                    window.resize(width_delta=10)
                                set_item_tooltip_no_delay("bigger")

                                if imgui.button("\uf146"):
                                    window.resize(width_delta=-10)
                                set_item_tooltip_no_delay("smaller")

                                imgui.button("\uf0d8")
                                set_item_tooltip_no_delay("always on top")

                    imgui.table_next_column()
                    imgui.text(window.proc.name())

            msio = imgui.end_multi_select()
            self._apply_selection_requests(msio=msio, on_selection=on_selection)

    window_has_focus = StateChangeTracker(False)

    def _render_search(self):
        imgui.text("search")
        imgui.same_line()

        # todo: cant select item anymore
        if imgui.is_window_focused(imgui.FocusedFlags_.root_window):
            self.focus_search_box.set(True)

        # todo: if window is focused, then focus on the textbox on the first time

        should_focus = self.focus_search_box.read()

        def unselect_all(data: imgui.InputTextCallbackData) -> int:
            """
            Weirdly imgui will select all text when programmatically focused.
            This clear the selection when a focus is requested.
            """
            if should_focus:
                data.clear_selection()
            return 0

        # if should_focus:
        #     imgui.set_keyboard_focus_here(0)

        # self.window_has_focus.value = imgui.is_window_appearing() or imgui.is_window_focused(imgui.FocusedFlags_.root_and_child_windows)
        # ref: https://github.com/ocornut/imgui/issues/5882
        self.window_has_focus.value = (
            imgui.get_window_viewport().flags & imgui.ViewportFlags_.is_focused > 0
        )
        if self.window_has_focus.changed and self.window_has_focus.value:
            imgui.set_keyboard_focus_here(0)

        # print(imgui.get_io().app_focus_lost)

        _, self._search_str = imgui.input_text(
            "##search",
            self._search_str,
            # callback=unselect_all
        )
        # imgui.set_item_default_focus()

    def _render_controls_group(self):
        selected = self._window_state_store.selected()
        style = imgui.get_style()

        with (
            imgui_ctx.begin_group(),
            imgui_ctx.begin_horizontal("actions"),
            imgui_ctx.push_style_var(
                imgui.StyleVar_.item_spacing,
                ImVec2(style.item_spacing.y * 0.9, style.item_spacing.y),
            ),
            imgui_ctx.push_style_var(
                imgui.StyleVar_.frame_padding,
                ImVec2(style.frame_padding.y * 10, style.frame_padding.y * 2),
            ),
        ):
            imgui.button("\uf0d8")
            set_item_tooltip_no_delay("always on top")

            if imgui.button("\ue4bd"):
                [window.resize_and_center() for window in selected.keys()]
            set_item_tooltip_no_delay("center")

            if imgui.button("\uf0fe"):
                [window.resize(width_delta=10) for window in selected.keys()]
            set_item_tooltip_no_delay("bigger")

            if imgui.button("\uf146"):
                [window.resize(width_delta=-10) for window in selected.keys()]
            set_item_tooltip_no_delay("smaller")

    view2_show = StateChangeTracker(True)

    def _render_view2(self):
        _, self.view2_show.value = imgui.checkbox("show", self.view2_show.value)

        if not self.view2_show.value:
            return

        monitor_rect = Monitor.from_mouse_pos().work
        rect = Rect.from_width_height(
            monitor_rect.width() / 4, monitor_rect.height() / 4
        )
        rect = rect.center_inside(monitor_rect)

        if self.view2_show.initial_oneshot or self.view2_show.changed:
            imgui.set_next_window_size(ImVec2(rect.width(), rect.height()))
            imgui.set_next_window_pos(ImVec2(rect.left, rect.top))

        with imgui_ctx.begin(
            "gwincc", p_open=True, flags=imgui.WindowFlags_.no_collapse
        ):
            pass


def main():
    startup = Startup()
    try:
        startup.run()
    finally:
        startup.cleanup()


if __name__ == "__main__":
    main()
