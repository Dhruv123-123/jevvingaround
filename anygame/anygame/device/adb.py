"""An Android phone over adb. v1 uses `screencap` (100-250 ms a frame); scrcpy's video stream is the faster path later."""
from __future__ import annotations
import subprocess
import numpy as np
import cv2
from .base import Device


class AdbDevice(Device):
    def __init__(self, serial: str = ""):
        self.serial = serial
        if serial and ":" in serial:
            subprocess.run(["adb", "connect", serial], check=False, capture_output=True)
        out = self._adb(["shell", "wm", "size"]).decode().strip()   # "Physical size: 1080x2400"
        w, h = out.split()[-1].split("x")
        self._size = (int(w), int(h))

    def _adb(self, args: list[str]) -> bytes:
        cmd = ["adb"] + (["-s", self.serial] if self.serial else []) + args
        return subprocess.run(cmd, check=True, capture_output=True).stdout

    def size(self):
        return self._size

    def frame(self):
        png = self._adb(["exec-out", "screencap", "-p"])
        return cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)

    def tap(self, x, y):
        self._adb(["shell", "input", "tap", str(int(x)), str(int(y))])

    def swipe(self, x0, y0, x1, y1, ms=120):
        self._adb(["shell", "input", "swipe", str(int(x0)), str(int(y0)), str(int(x1)), str(int(y1)), str(int(ms))])

    def key(self, name):
        self._adb(["shell", "input", "keyevent", name])
