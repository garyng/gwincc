from dataclasses import dataclass
import logging
from time import sleep
from typing import Any

import psutil
import win32api
import win32con
import win32gui
import win32process


logger = logging.getLogger(__name__)


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

    @staticmethod
    def from_win32_rect(rect: Any) -> "Rect":
        """
        Accepts either a 4-tuple (left, top, right, bottom) or an object
        with attributes left, top, right, bottom (e.g., a win32 RECT).
        """
        if hasattr(rect, "left") and hasattr(rect, "top"):
            return Rect(rect.left, rect.top, rect.right, rect.bottom)
        l, t, r, b = rect
        return Rect(l, t, r, b)

    @staticmethod
    def from_width_height(width: int, height: int, top=0, left=0) -> "Rect":
        right = left + width
        bottom = top + height

        return Rect(left, top, right, bottom)

    def center_inside(self, outside_rect: "Rect") -> "Rect":
        """
        Calculate the new rect where the current rect is centered inside the provided rect.
        """

        width = self.width()
        height = self.height()

        left_gap = (outside_rect.width() - width) / 2
        top_gap = (outside_rect.height() - height) / 2

        left = int(outside_rect.left + left_gap)
        top = int(outside_rect.top + top_gap)

        right = left + width
        bottom = top + height

        return Rect(left=left, top=top, right=right, bottom=bottom)


@dataclass
class Monitor:
    work: Rect

    @staticmethod
    def from_monitor_handle(hmonitor: int) -> "Monitor":
        monitor = win32api.GetMonitorInfo(hmonitor)

        return Monitor(
            work=Rect.from_win32_rect(monitor["Work"]),
        )

    @staticmethod
    def from_hwnd(hwnd: int) -> "Monitor":
        monitor_handle = win32api.MonitorFromWindow(hwnd)
        return Monitor.from_monitor_handle(monitor_handle)

    @staticmethod
    def from_mouse_pos() -> "Monitor":
        x, y = win32api.GetCursorPos()
        monitor_handle = win32api.MonitorFromPoint(
            (x, y), win32con.MONITOR_DEFAULTTONEAREST
        )
        return Monitor.from_monitor_handle(monitor_handle)


@dataclass
class Window:
    pid: int
    proc: psutil.Process
    hwnd: int
    title: str
    process_created_at: float

    @staticmethod
    def from_hwnd(hwnd: int) -> "Window":
        title = win32gui.GetWindowText(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc = psutil.Process(pid=pid)

        return Window(
            pid=pid,
            proc=proc,
            hwnd=hwnd,
            title=title,
            process_created_at=proc.create_time(),
        )

    def __hash__(self) -> int:
        return hash((self.hwnd,))

    def __eq__(self, value: object) -> bool:
        if not isinstance(value, Window):
            raise NotImplementedError()

        return self.hwnd == value.hwnd

    def resize_and_center(self, ratio: float = 0.8):
        work = self.monitor().work

        width = int(work.width() * ratio)
        height = int(work.height() * ratio)

        self._resize_move_to_center_of_rect(
            width=width, height=height, monitor_rect=work
        )

    def center(self):
        work = self.monitor().work
        rect = self.rect()

        inner_centered = rect.center_inside(work)
        win32gui.SetWindowPos(
            self.hwnd,
            None,
            inner_centered.left,
            inner_centered.top,
            0,
            0,
            win32con.SWP_NOZORDER  # dont change zorder
            | win32con.SWP_NOSIZE  # dont resize
            | win32con.SWP_NOACTIVATE,  # dont reactivate
        )

    def rect(self) -> Rect:
        return Rect.from_win32_rect(win32gui.GetWindowRect(self.hwnd))

    def monitor(self) -> Monitor:
        return Monitor.from_hwnd(self.hwnd)

    def _resize_move_to_center_of_rect(
        self, width: int, height: int, monitor_rect: Rect
    ):
        """
        Resize window and move it to the center of the monitor,
        leaving even gaps from the top and left.
        """

        inner = Rect.from_width_height(width=width, height=height)
        inner_centered = inner.center_inside(monitor_rect)

        self.restore()

        win32gui.MoveWindow(
            self.hwnd,
            inner_centered.left,
            inner_centered.top,
            inner_centered.width(),
            inner_centered.height(),
            True,
        )

    def resize(self, width_delta=10):
        work = self.monitor().work
        rect = Rect.from_win32_rect(win32gui.GetWindowRect(self.hwnd))

        height_delta = int(width_delta / rect.wh_ratio())
        self._resize_move_to_center_of_rect(
            width=rect.width() + width_delta,
            height=rect.height() + height_delta,
            monitor_rect=work,
        )

    def bring_to_front(self, retry_when_failed=True):
        def _():
            self.restore()
            win32gui.BringWindowToTop(self.hwnd)
            self.activate()

        for x in range(0, 30):
            try:
                _()
                break
            except:
                logger.info(
                    "Failed to bring window to front, retrying, [%(x)s]", {"x": x}
                )
                sleep(0.01)

    def activate(self):
        win32gui.SetForegroundWindow(self.hwnd)

    def restore(self):
        if win32gui.IsIconic(self.hwnd):
            # restore if minimized
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
        else:
            win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
