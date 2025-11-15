import time
from dataclasses import dataclass

from gwincc.models import Window


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

    def get_or_none(self, key: Window) -> WindowState | None:
        return self.store.get(key, None)

    def purge(self, windows: list[Window]):
        """
        Purge state from store that doesn't exist anymore.
        """
        self.store = {
            window: state for window, state in self.store.items() if window in windows
        }

    def selected(self) -> dict[Window, WindowState]:
        return {w: ws for w, ws in self.store.items() if ws.selected}
