import threading
from abc import abstractmethod

import psutil
import win32con
import win32gui
import win32process

from gwincc.models import Window


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


class GetWindowsBackgroundService(BackgroundService):
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
            
            # top level window only without parent
            if win32gui.GetParent(hwnd):
                return

            # skip if has an owner (eg: tool windows)
            if win32gui.GetWindow(hwnd, win32con.GW_OWNER):
                return

            _, pid = win32process.GetWindowThreadProcessId(hwnd)

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
