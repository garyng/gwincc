from pathlib import Path
from typing import Callable

import rapidfuzz
from imgui_bundle import ImVec2, hello_imgui, imgui, imgui_ctx, immapp

from gwincc.imgui_ex import set_item_tooltip_no_delay
from gwincc.models import Window
from gwincc.services import GetWindowsBackgroundService
from gwincc.state import WindowStateStore

# todo: purge state


def startup():
    def load_fonts(font_size=13.0):
        default_font = hello_imgui.load_font(
            "fonts/CascadiaCode-Regular.otf", font_size, hello_imgui.FontLoadingParams()
        )
        icon_fontg = hello_imgui.load_font(
            "fonts/fontawesome6/Font Awesome 6 Free-Solid-900.otf",
            font_size,
            hello_imgui.FontLoadingParams(merge_to_last_font=True),
        )

    root_dir = Path(__file__).parent
    assets_dir = root_dir / "assets"
    get_windows_background_service = GetWindowsBackgroundService()
    get_windows_background_service.run()

    hello_imgui.set_assets_folder(assets_dir.as_posix())

    runner_params = hello_imgui.RunnerParams()

    # runner_params.imgui_window_params.default_imgui_window_type = (
    #     hello_imgui.DefaultImGuiWindowType.provide_full_screen_dock_space
    # )
    runner_params.imgui_window_params.enable_viewports = True

    runner_params.app_window_params.window_title = "gwincc"
    runner_params.callbacks.load_additional_fonts = load_fonts

    runner_params.app_window_params.restore_previous_geometry = True

    main_view = MainView(get_windows_background_service=get_windows_background_service)
    runner_params.callbacks.show_gui = main_view.render
    immapp.run(runner_params=runner_params)
    get_windows_background_service.close()


class MainView:
    def __init__(self, get_windows_background_service) -> None:
        self.store = WindowStateStore()
        self.search_str = ""
        self.get_windows_background_service = get_windows_background_service

    def _scorer(self, query: str, window: Window, *, processor=None, score_cutoff=None):
        title = rapidfuzz.fuzz.WRatio(
            query, window.title, processor=lambda x: x.lower()
        )
        process = rapidfuzz.fuzz.WRatio(
            query, window.proc.name(), processor=lambda x: x.lower()
        )

        return 0.75 * title + 0.15 * process

    def _filter(self, windows: list[Window]):
        if not self.search_str:
            return windows

        results = [
            window
            for window, score, index in rapidfuzz.process.extract(
                self.search_str,
                windows,
                scorer=self._scorer,
                limit=None,
            )
        ]

        return results

    def _sort(self, windows: list[Window]) -> list[Window]:
        def _sort_by_pinned_at(window: Window):
            state = self.store.get_or_none(window)

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

    def render(self) -> None:
        self._render_search()

        self._render_windows()

        imgui.separator_text("controls")

        self._render_controls_group()

        # imgui.set_next_window_size(ImVec2(200, 400), imgui.Cond_.first_use_ever)
        # imgui.set_next_window_pos(ImVec2(-1000, 100), imgui.Cond_.first_use_ever)
        # with imgui_ctx.begin("controls"):
        #     imgui.text("asdasd")

    def _render_windows(self):
        with imgui_ctx.begin_table(
            "windows",
            3,
            imgui.TableFlags_.resizable
            + imgui.TableFlags_.scroll_x
            + imgui.TableFlags_.scroll_y,
            ImVec2(0, -5 * imgui.get_frame_height_with_spacing()),
        ):
            imgui.table_setup_scroll_freeze(0, 1)
            imgui.table_setup_column("##actions")
            imgui.table_setup_column("Title")
            imgui.table_setup_column("Process")
            imgui.table_headers_row()

            # if imgui.is_window_focused():
            #     io = imgui.get_io()
            #     for char in io.input_queue_characters:
            #         print(chr(char))
            #     # for k in range(imgui.Key.named_key_begin, imgui.Key.named_key_end):
            #     #     if imgui.is_key_pressed(k):
            #     #         print(k)

            windows = self._sort(
                self._filter(self.get_windows_background_service.windows)
            )

            def on_selection(idx: int, selected: bool):
                self.store[windows[idx]].selected = selected

            msio = imgui.begin_multi_select(
                imgui.MultiSelectFlags_.clear_on_escape
                + imgui.MultiSelectFlags_.box_select2d,
                items_count=len(windows),  # used in set_all request
            )
            self._apply_selection_requests(msio=msio, on_selection=on_selection)

            for idx, window in enumerate(windows):
                state = self.store[window]
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
                    if clicked and imgui.is_mouse_double_clicked(
                        imgui.MouseButton_.left
                    ):
                        window.bring_to_front()

                    imgui.table_next_column()
                    imgui.text(window.proc.name())

            msio = imgui.end_multi_select()
            self._apply_selection_requests(msio=msio, on_selection=on_selection)

    def _render_search(self):
        imgui.text("search")
        imgui.same_line()

        # for k in range(imgui.Key.named_key_begin, imgui.Key.named_key_end):
        #     if imgui.is_key_pressed(k) and not imgui.get_io().want_capture_keyboard:
        #         imgui.set_keyboard_focus_here(0)
        # todo: how to make this receive input by default?
        _, self.search_str = imgui.input_text("##search", self.search_str)

    def _render_controls_group(self):
        selected = self.store.selected()
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
                [window.center() for window in selected.keys()]
            set_item_tooltip_no_delay("center")

            if imgui.button("\uf0fe"):
                [window.resize(width_delta=10) for window in selected.keys()]
            set_item_tooltip_no_delay("bigger")

            if imgui.button("\uf146"):
                [window.resize(width_delta=-10) for window in selected.keys()]
            set_item_tooltip_no_delay("smaller")


if __name__ == "__main__":
    startup()
