"""A browser page as a device: screenshots for frames, mouse for taps and drags. Runs anywhere Chromium runs."""
from __future__ import annotations
import os
import numpy as np
import cv2
from .base import Device

CHROME_CANDIDATES = [os.environ.get("CHROMIUM_PATH", ""), "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"]


class WebDevice(Device):
    def __init__(self, url: str, size: tuple[int, int]):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        exe = next((c for c in CHROME_CANDIDATES if c and os.path.exists(c)), None)
        kwargs = {"headless": True, "args": ["--no-sandbox"]}
        if exe:
            kwargs["executable_path"] = exe
        self._browser = self._pw.chromium.launch(**kwargs)
        self._page = self._browser.new_page(viewport={"width": size[0], "height": size[1]}, device_scale_factor=1)
        self._size = size
        self._page.goto(url if "://" in url else "file://" + os.path.abspath(url))
        self._page.wait_for_load_state("load")

    def size(self):
        return self._size

    def frame(self):
        png = self._page.screenshot(type="png")
        arr = np.frombuffer(png, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    def tap(self, x, y):
        self._page.mouse.click(x, y)

    def swipe(self, x0, y0, x1, y1, ms=120):
        m = self._page.mouse
        m.move(x0, y0)
        m.down()
        steps = max(4, ms // 15)
        m.move(x1, y1, steps=steps)
        m.up()

    def key(self, name):
        self._page.keyboard.press(name)

    def evaluate(self, js: str):
        """For tests: read the page's own truth to check perception against it."""
        return self._page.evaluate(js)

    def close(self):
        try:
            self._browser.close()
        finally:
            self._pw.stop()
