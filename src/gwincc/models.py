from dataclasses import dataclass
from typing import Any

import psutil
import win32api
import win32con
import win32gui


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

        self.restore()

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

    def bring_to_front(self):
        self.restore()
        win32gui.BringWindowToTop(self.hwnd)

    def restore(self):
        # not minimized
        if not win32gui.IsIconic(self.hwnd):
            return

        win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
