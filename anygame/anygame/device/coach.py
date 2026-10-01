"""Coach mode: the loop reads, decides and shows, but never acts. Every input becomes a suggestion the HUD displays
and the person performs, or not. The mode for games whose anti-cheat treats any injected input as cheating, and
for watching what the runtime would do before letting it."""
from __future__ import annotations
from typing import Any

from .base import Device


class CoachDevice(Device):
    coach = True

    def __init__(self, inner: Device):
        self.inner = inner
        self.suggestion: str | None = None
        self.suggestions: list[str] = []

    def size(self):
        return self.inner.size()

    def frame(self):
        return self.inner.frame()

    def state(self) -> Any:
        return self.inner.state() if hasattr(self.inner, "state") else None

    def _suggest(self, s: str) -> None:
        self.suggestion = s
        self.suggestions.append(s)
        del self.suggestions[:-50]

    def tap(self, x, y):
        self._suggest(f"tap ({x},{y})")

    def swipe(self, x0, y0, x1, y1, ms=120):
        self._suggest(f"swipe ({x0},{y0})→({x1},{y1})")

    def key(self, name, hold_ms=0):
        self._suggest(f"key {name}" + (f" held {hold_ms} ms" if hold_ms else ""))

    def mouse_move(self, dx, dy):
        self._suggest(f"move the mouse by {dx},{dy}")

    def reload(self):
        if hasattr(self.inner, "reload"):
            self.inner.reload()

    @property
    def exhausted(self) -> bool:
        return bool(getattr(self.inner, "exhausted", False))

    @property
    def paused(self) -> bool:
        return bool(getattr(self.inner, "paused", False))

    def close(self):
        self.inner.close()
