from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
import threading
import time
from typing import Any, Protocol
from imgui_bundle import ImVec2, glfw_utils, hello_imgui, imgui, immapp, imgui_ctx
import glfw  # must import after imgui_bundle

from gwincc.common import test1
from pywinauto import Desktop


import win32gui
import win32con
import psutil
import win32process
import os


class BackgroundService:
    def run(self):
        self.cancellation = threading.Event()
        self.thread = threading.Thread(target=self._loop, args=(self.cancellation,))
        self.thread.start()

    def close(self):
        self.cancellation.set()
        self.thread.join(timeout=30)

    def _loop(self, cancellation: threading.Event):
        while not cancellation.is_set():
            if self._run(cancellation=cancellation):
                break

    @abstractmethod
    def _run(self, cancellation: threading.Event) -> bool: ...


class WindowProtocol(Protocol):
    class ElementInfoProtocol(Protocol):
        name: str
        process_id: int

    handle: int
    element_info: ElementInfoProtocol


class GetWindowsBackgroundService(BackgroundService):
    windows: list[WindowProtocol] = []

    def __init__(self) -> None:
        super().__init__()

        self.desktop = Desktop(backend="uia")

    def _run(self, cancellation: threading.Event):
        self.windows = self.desktop.windows()
        if cancellation.wait(1):
            return True
        return False


import win32api


@dataclass
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    def width(self) -> int:
        return self.right - self.left

    def height(self) -> int:
        return self.bottom - self.top
    
    def wh_ratio(self) -> float:
        return self.width() / self.height()

    @classmethod
    def from_win32_rect(cls, rect: Any) -> "Rect":
        """
        Accepts either a 4-tuple (left, top, right, bottom) or an object
        with attributes left, top, right, bottom (e.g., a win32 RECT).
        """
        if hasattr(rect, "left") and hasattr(rect, "top"):
            return cls(rect.left, rect.top, rect.right, rect.bottom)
        l, t, r, b = rect
        return cls(l, t, r, b)


@dataclass
class Monitor:
    work: Rect

    @classmethod
    def from_hwnd(cls, hwnd: int) -> "Monitor":
        monitor_handle = win32api.MonitorFromWindow(hwnd)
        monitor = win32api.GetMonitorInfo(monitor_handle)

        return cls(
            work=Rect.from_win32_rect(monitor["Work"]),
        )


@dataclass
class Window:
    pid: int
    proc: psutil.Process
    hwnd: int
    title: str
    process_created_at: float

    def __hash__(self) -> int:
        return hash((self.hwnd,))

    def __eq__(self, value: object) -> bool:
        if not isinstance(value, Window):
            raise NotImplementedError()

        return self.hwnd == value.hwnd

    def center(self, ratio: float = 0.8):
        monitor = Monitor.from_hwnd(self.hwnd)

        width = int(monitor.work.width() * ratio)
        height = int(monitor.work.height() * ratio)

        self._resize_move_to_center_of_rect(
            width=width, height=height, monitor_rect=monitor.work
        )

    def _resize_move_to_center_of_rect(
        self, width: int, height: int, monitor_rect: Rect
    ):
        """
        Resize window and move it to the center of the monitor,
        leaving even gaps from the top and left.
        """

        if win32gui.IsIconic(self.hwnd):
            # restore if minimized
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)

        left_gap = (monitor_rect.width() - width) / 2
        top_gap = (monitor_rect.height() - height) / 2

        left = int(monitor_rect.left + left_gap)
        top = int(monitor_rect.top + top_gap)

        win32gui.MoveWindow(self.hwnd, left, top, width, height, True)

    def resize(self, width_delta=10):
        monitor = Monitor.from_hwnd(self.hwnd)
        rect = Rect.from_win32_rect(win32gui.GetWindowRect(self.hwnd))

        height_delta = int(width_delta / rect.wh_ratio())
        self._resize_move_to_center_of_rect(
            width=rect.width() + width_delta,
            height=rect.height() + height_delta,
            monitor_rect=monitor.work,
        )

        print(rect.wh_ratio(), width_delta, height_delta)


@dataclass
class WindowState:
    selected: bool = False
    pinned_at: float | None = None

    def pin(self):
        self.pinned_at = time.time()

    def unpin(self):
        self.pinned_at = None


class WindowStateStore:
    store: dict[Window, WindowState] = {}

    def __init__(self) -> None:
        pass

    def __getitem__(self, key: Window) -> WindowState:
        return self.store.setdefault(key, WindowState())

    def purge(self, windows: list[Window]):
        """
        Purge state from store that doesn't exist anymore.
        """
        self.store = {
            window: state for window, state in self.store.items() if window in windows
        }


class GetWindowsBackgroundService2(BackgroundService):
    windows: list[Window] = []

    def __init__(self) -> None:
        super().__init__()

    def _run(self, cancellation: threading.Event):
        windows: list[Window] = []

        def enum_windows_callback(hwnd, extras):
            # visible
            if not win32gui.IsWindowVisible(hwnd):
                return

            title = win32gui.GetWindowText(hwnd)
            # not empty
            if not title:
                return

            # skip if has an owner (eg: tool windows)
            if win32gui.GetWindow(hwnd, win32con.GW_OWNER):
                return

            _, pid = win32process.GetWindowThreadProcessId(hwnd)

            # not self
            if pid == os.getpid():
                return

            # process creation time
            proc = psutil.Process(pid=pid)

            windows.append(
                Window(
                    pid=pid,
                    proc=proc,
                    hwnd=hwnd,
                    title=title,
                    process_created_at=proc.create_time(),
                )
            )

        win32gui.EnumWindows(enum_windows_callback, None)
        self.windows = windows

        if cancellation.wait(1):
            return True
        return False


get_windows_background_service = GetWindowsBackgroundService2()


def load_fonts(font_size=13.0):
    default_font = hello_imgui.load_font(
        "fonts/CascadiaCode-Regular.otf", font_size, hello_imgui.FontLoadingParams()
    )
    icon_fontg = hello_imgui.load_font(
        "fonts/fontawesome6/Font Awesome 6 Free-Solid-900.otf",
        font_size,
        hello_imgui.FontLoadingParams(merge_to_last_font=True),
    )


def set_item_tooltip_no_delay(fmt: str):
    if imgui.is_item_hovered(imgui.HoveredFlags_.delay_none):
        imgui.set_tooltip(fmt)


store = WindowStateStore()


def main() -> None:
    # remove the default window icon
    # ref: https://github.com/pthom/imgui_bundle/issues/401
    # glfw.set_window_icon(glfw_utils.glfw_window_hello_imgui(), 0, [])

    # for window in current_windows:
    #     with imgui_ctx.push_id(window):
    #         imgui.button("\uf08d")
    #         imgui.same_line()
    #         with imgui_ctx.tree_node_ex(window, flags=imgui.TreeNodeFlags_.draw_lines_full + imgui.TreeNodeFlags_.draw_lines_to_nodes + imgui.TreeNodeFlags_.default_open):
    #             imgui.button("\uf08d")
    #             imgui.same_line()
    #             with imgui_ctx.tree_node_ex(window, flags=imgui.TreeNodeFlags_.draw_lines_full + imgui.TreeNodeFlags_.draw_lines_to_nodes + imgui.TreeNodeFlags_.default_open):
    #                 pass
    style = imgui.get_style()
    action_button_size = ImVec2(
        imgui.get_frame_height() * 1.5,
        imgui.get_frame_height() * 1.5,
    )

    imgui.text("search")
    imgui.same_line()
    imgui.input_text("##search", "")

    # todo: rapidfuzz

    # todo: maybe change to use table
    with imgui_ctx.begin_child("windows", size=ImVec2(0, -imgui.get_frame_height())):
        for window in get_windows_background_service.windows:
            state = store[window]
            with imgui_ctx.push_id(str(window.hwnd)):
                with (
                    imgui_ctx.begin_horizontal("actions"),
                    imgui_ctx.push_style_var(
                        imgui.StyleVar_.item_spacing,
                        ImVec2(style.item_spacing.y * 0.9, style.item_spacing.y),
                    ),
                    imgui_ctx.push_style_var(
                        imgui.StyleVar_.frame_padding,
                        ImVec2(style.frame_padding.y * 2, style.frame_padding.y * 2),
                    ),
                ):
                    if state.pinned_at:
                        if imgui.button("\ue68f"):
                            state.unpin()
                        set_item_tooltip_no_delay("unpin")
                    else:
                        if imgui.button("\uf08d"):
                            state.pin()
                        set_item_tooltip_no_delay("pin")

                    if imgui.button("\ue4bd"):
                        window.center()
                    set_item_tooltip_no_delay("center")

                    if imgui.button("\uf0fe"):
                        window.resize(width_delta=10)
                    set_item_tooltip_no_delay("bigger")

                    if imgui.button("\uf146"):
                        window.resize(width_delta=-10)
                    set_item_tooltip_no_delay("smaller")

                    imgui.selectable(
                        f"{window.title}, hwnd={window.hwnd}, exe={window.proc.exe()}",
                        False,
                    )
    # changed, value = imgui.slider_float("zome", imgui.get_style().font_scale_dpi, 0.9, 2)
    # if changed:
    #     imgui.get_style().scale_all_sizes()


root_dir = Path(__file__).parent
assets_dir = root_dir / "assets"

if __name__ == "__main__":
    # glfw.init()
    get_windows_background_service.run()

    hello_imgui.set_assets_folder(assets_dir.as_posix())
    # hello_imgui.get_runner_params().callbacks.default_icon_font = hello_imgui.DefaultIconFont.font_awesome6

    runner_params = hello_imgui.RunnerParams()
    runner_params.callbacks.show_gui = main
    runner_params.app_window_params.window_title = "gwincc"
    runner_params.callbacks.load_additional_fonts = load_fonts

    immapp.run(runner_params=runner_params)
    get_windows_background_service.close()
