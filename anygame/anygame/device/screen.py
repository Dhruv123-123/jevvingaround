"""The computer's own screen as a device: any window, any game, through what the OS shows and the keys and mouse it
takes. Frames come from `mss` (a region of a monitor), input goes through `pynput` (real key and mouse events).
`screen://x,y,w,h` is a region in screen pixels; `screen://` is the whole primary monitor; `?scale=0.5` captures at
half size (the pack's coordinates are frame pixels, so input is mapped back). Needs `pip install anygame[desktop]`."""
from __future__ import annotations
import time
from typing import Any

import numpy as np

from .base import Device

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


class ScreenDevice(Device):
    def __init__(self, spec: str, size: tuple[int, int] | None = None):
        import cv2
        import mss
        from pynput.keyboard import Controller as KB
        from pynput.mouse import Button, Controller as MS
        self._cv2, self._Button = cv2, Button
        o = parse_url(spec)
        self._sct = mss.mss()
        mon = self._sct.monitors[o["monitor"]] if len(self._sct.monitors) > o["monitor"] else self._sct.monitors[0]
        self.region = o["region"] or {"left": mon["left"], "top": mon["top"], "width": mon["width"], "height": mon["height"]}
        self.scale = o["scale"]
        self._size = (int(self.region["width"] * self.scale), int(self.region["height"] * self.scale))
        self.kb, self.ms = KB(), MS()

    def size(self):
        return self._size

    def frame(self):
        shot = self._sct.grab(self.region)
        img = np.asarray(shot)[:, :, :3]        # BGRA → BGR
        if self.scale != 1:
            img = self._cv2.resize(img, self._size, interpolation=self._cv2.INTER_AREA)
        return np.ascontiguousarray(img)

    def _to_screen(self, x: float, y: float) -> tuple[int, int]:
        return int(self.region["left"] + x / self.scale), int(self.region["top"] + y / self.scale)

    def tap(self, x, y):
        self.ms.position = self._to_screen(x, y)
        time.sleep(0.02)
        self.ms.click(self._Button.left, 1)

    def swipe(self, x0, y0, x1, y1, ms=120):
        self.ms.position = self._to_screen(x0, y0)
        time.sleep(0.02)
        self.ms.press(self._Button.left)
        steps = max(4, ms // 15)
        for i in range(1, steps + 1):
            t = i / steps
            self.ms.position = self._to_screen(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
            time.sleep(ms / 1000 / steps)
        self.ms.release(self._Button.left)

    def key(self, name):
        k = key_of(name)
        self.kb.press(k)
        time.sleep(0.03)
        self.kb.release(k)

    def close(self):
        try:
            self._sct.close()
        except Exception:  # noqa: BLE001
            pass
