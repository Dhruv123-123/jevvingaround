"""The computer's own screen as a device: any window, any game, through what the OS shows and the keys and mouse it
takes. Frames come from `mss` (a region of a monitor), input goes through `pynput` (real key and mouse events).
`screen://x,y,w,h` is a region in screen pixels; `screen://` is the whole primary monitor; `?scale=0.5` captures at
half size (the pack's coordinates are frame pixels, so input is mapped back). Needs `pip install anygame[desktop]`.
This is the one device that shares the person's keyboard and mouse, so the guard rails are on: it pauses for
`?pause=3` seconds after any input it did not send itself, Ctrl+Alt+Q stops it, and it sends at most `?budget=300`
inputs a minute. `window://`, `pad://` and `nested://` act without touching the person's own input at all."""
from __future__ import annotations
import time
from typing import Any

import numpy as np

from .base import Device
from .guard import Guarded

KEYS = {"ArrowUp": "up", "ArrowDown": "down", "ArrowLeft": "left", "ArrowRight": "right", "Space": "space", " ": "space", "Enter": "enter",
        "Escape": "esc", "Shift": "shift", "Tab": "tab", "Backspace": "backspace", "Delete": "delete", "Control": "ctrl", "Alt": "alt"}


def parse_url(spec: str) -> dict[str, Any]:
    """`x,y,w,h[?scale=s&monitor=n]` → {region, scale, monitor}; an empty spec is the whole primary monitor."""
    q: dict[str, str] = {}
    if "?" in spec:
        spec, qs = spec.split("?", 1)
        q = dict(kv.split("=", 1) for kv in qs.split("&") if "=" in kv)
    region = None
    if spec.strip():
        parts = [int(float(v)) for v in spec.split(",")]
        if len(parts) != 4:
            raise ValueError(f"screen:// needs x,y,w,h, got {spec!r}")
        region = {"left": parts[0], "top": parts[1], "width": parts[2], "height": parts[3]}
    return {"region": region, "scale": float(q.get("scale", 1)), "monitor": int(q.get("monitor", 1))}


def key_of(name: str):
    """A pack key name → a pynput key (special) or a character."""
    from pynput.keyboard import Key
    if name in KEYS:
        return getattr(Key, KEYS[name])
    if len(name) == 1:
        return name
    low = name.lower()
    if hasattr(Key, low):
        return getattr(Key, low)
    return name


class ScreenFrames:
    """A region of a display as frames, through mss. Shared by every desktop-facing device; `display` picks an X
    display other than the current one (the nested sandbox)."""

    def __init__(self, spec: str, display: str | None = None):
        import cv2
        import mss
        self._cv2 = cv2
        o = parse_url(spec)
        self._sct = mss.mss(display=display) if display else mss.mss()
        mon = self._sct.monitors[o["monitor"]] if len(self._sct.monitors) > o["monitor"] else self._sct.monitors[0]
        self.region = o["region"] or {"left": mon["left"], "top": mon["top"], "width": mon["width"], "height": mon["height"]}
        self.scale = o["scale"]
        self.query = o
        self._size = (int(self.region["width"] * self.scale), int(self.region["height"] * self.scale))

    def size(self):
        return self._size

    def frame(self):
        shot = self._sct.grab(self.region)
        img = np.asarray(shot)[:, :, :3]        # BGRA → BGR
        if self.scale != 1:
            img = self._cv2.resize(img, self._size, interpolation=self._cv2.INTER_AREA)
        return np.ascontiguousarray(img)

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        return int(self.region["left"] + x / self.scale), int(self.region["top"] + y / self.scale)

    def close(self):
        try:
            self._sct.close()
        except Exception:  # noqa: BLE001
            pass


class ScreenDevice(Guarded, Device):
    """The real keyboard and mouse: the one path that shares them with the person, so every guard rail is on."""

    def __init__(self, spec: str, size: tuple[int, int] | None = None, display: str | None = None):
        import os
        from pynput.keyboard import Controller as KB
        from pynput.mouse import Button, Controller as MS
        self._Button = Button
        self._frames = ScreenFrames(spec, display)
        self.region, self.scale = self._frames.region, self._frames.scale
        saved = os.environ.get("DISPLAY")
        if display:
            os.environ["DISPLAY"] = display       # pynput opens the display when a controller is made
        try:
            self.kb, self.ms = KB(), MS()
        finally:
            if display:
                if saved is None:
                    os.environ.pop("DISPLAY", None)
                else:
                    os.environ["DISPLAY"] = saved
        q = self._frames.query
        self.pause_s = float(q.get("pause", self.pause_s))
        self.max_actions_per_minute = int(q.get("budget", self.max_actions_per_minute))
        self._guard_start(listen=q.get("guard", "1") != "0", display=display)

    def size(self):
        return self._frames.size()

    def frame(self):
        return self._frames.frame()

    def _to_screen(self, x: float, y: float) -> tuple[int, int]:
        return self._frames.to_screen(x, y)

    def tap(self, x, y):
        if not self._allow():
            return
        self._own(80)
        self.ms.position = self._to_screen(x, y)
        time.sleep(0.02)
        self.ms.click(self._Button.left, 1)

    def swipe(self, x0, y0, x1, y1, ms=120):
        if not self._allow():
            return
        self._own(ms + 100)
        self.ms.position = self._to_screen(x0, y0)
        time.sleep(0.02)
        self.ms.press(self._Button.left)
        steps = max(4, ms // 15)
        for i in range(1, steps + 1):
            t = i / steps
            self.ms.position = self._to_screen(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
            time.sleep(ms / 1000 / steps)
        self.ms.release(self._Button.left)

    def key(self, name, hold_ms=0):
        if not self._allow():
            return
        self._own(max(30, hold_ms or 0) + 40)
        k = key_of(name)
        self.kb.press(k)
        time.sleep(max(0.03, (hold_ms or 0) / 1000))
        self.kb.release(k)

    def mouse_move(self, dx, dy):
        """Relative motion in captured pixels (scaled to the screen): a camera or a cursor."""
        if not self._allow():
            return
        self._own(60)
        self.ms.move(int(dx / self.scale), int(dy / self.scale))

    def close(self):
        self._guard_stop()
        self._frames.close()
