"""A Game Boy ROM as a device, through PyBoy. Frames are the emulator screen scaled up; keys are the pad.

    pyboy://roms/2048gb/2048.gb            # 3x nearest-neighbour: 480x432 frames
    pyboy://path/to/game.gb?scale=4&hold=6&after=16   # hold = frames a button stays pressed, after = frames run after it
    pyboy://path/to/game.gb?lock=1&idle=4              # step-locked: game time is set by the loop, not the wall clock

The emulator only advances when the loop asks for a frame: it runs as many frames as wall-clock time has
passed since the last one (capped at a second), so the game keeps real time while the model thinks and no
time passes between a frame and the action decided on it. With `lock=1` the wall clock plays no part: each frame
advances exactly `idle` frames and each press `hold + after`, so the same inputs give the same game whatever the
decider's latency (the held-out score relies on this to be reproducible by seed). `frames` counts game frames run. Swipes map to the d-pad, taps to A, so a pack
written with swipes for a touch screen plays here unchanged.
"""
from __future__ import annotations
import os
import time
from urllib.parse import parse_qs, urlsplit
import numpy as np
import cv2
from .base import Device

BUTTONS = {"a", "b", "start", "select", "up", "down", "left", "right"}
KEY_ALIASES = {"arrowup": "up", "arrowdown": "down", "arrowleft": "left", "arrowright": "right", "enter": "start", "space": "a",
               "x": "a", "z": "b", "shift": "select"}


class PyBoyDevice(Device):
    def __init__(self, url: str, size: tuple[int, int] | None = None):
        from pyboy import PyBoy
        u = urlsplit(url if "://" in url else "pyboy://" + url)
        path = (u.netloc + u.path) if u.netloc else u.path
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if not os.path.exists(path):
            raise SystemExit(f"ROM not found: {path}")
        self.scale = int(q.get("scale", 3))
        self.hold = int(q.get("hold", 6))
        self.after = int(q.get("after", 16))     # frames to run after a press so slide animations finish before the next read
        self.fps = float(q.get("fps", 60))
        self.lock = q.get("lock", "0") not in ("0", "", "false")
        self.idle = int(q.get("idle", 4))
        self.frames = 0
        self._pb = PyBoy(path, window="null", sound_emulated=False)
        self._pb.set_emulation_speed(0)
        self._last = time.perf_counter()
        boot = int(q.get("boot", 120))
        self._tick(boot)
        self._size = (160 * self.scale, 144 * self.scale)

    def size(self):
        return self._size

    def _tick(self, n: int, render: bool = False):
        if n > 0:
            self._pb.tick(n, render=render)
            self.frames += n

    def _advance(self, frames: int):
        self._tick(frames, render=True)

    def frame(self):
        if self.lock:
            frames = self.idle
        else:
            now = time.perf_counter()
            frames = int(min(1.0, now - self._last) * self.fps)
            self._last = now
        self._advance(frames)
        if self.lock and frames <= 0:
            self._tick(1, render=True)       # idle=0 still needs the screen rendered: one frame, counted like any other
        rgb = self._pb.screen.ndarray[:, :, :3]
        bgr = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2BGR)
        return cv2.resize(bgr, self._size, interpolation=cv2.INTER_NEAREST)

    def press(self, button: str):
        b = KEY_ALIASES.get(button.lower(), button.lower())
        if b not in BUTTONS:
            raise ValueError(f"no Game Boy button '{button}'")
        self._pb.button_press(b)
        self._tick(self.hold)
        self._pb.button_release(b)
        self._tick(self.after)

    def key(self, name, hold_ms=0):
        if hold_ms:
            b = KEY_ALIASES.get(name.lower(), name.lower())
            self._pb.button_press(b)
            self._tick(max(1, int(hold_ms / 1000 * 60)))     # the Game Boy runs 60 frames a second
            self._pb.button_release(b)
            self._tick(self.after)
            return
        self.press(name)

    def tap(self, x, y):
        self.press("a")

    def swipe(self, x0, y0, x1, y1, ms=120):
        dx, dy = x1 - x0, y1 - y0
        self.press(("right" if dx > 0 else "left") if abs(dx) > abs(dy) else ("down" if dy > 0 else "up"))

    def close(self):
        try:
            self._pb.stop(save=False)
        except Exception:  # noqa: BLE001
            pass
