"""A browser page as a device: screenshots for frames, mouse for taps and drags. Runs anywhere Chromium runs.
`web://<url>#state=<js expression>` also gives state(): the expression evaluated on the page (e.g. a game's own
`window.__state()`), for packs that read the stream instead of the pixels."""
from __future__ import annotations
import base64
import os
import time
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
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if proxy and not url.startswith(("file:", "/", ".")) and "://" in url:      # Chromium ignores the proxy env vars
            kwargs["proxy"] = {"server": proxy}
        self._browser = self._pw.chromium.launch(**kwargs)
        self._page = self._browser.new_page(viewport={"width": size[0], "height": size[1]}, device_scale_factor=1)
        self._size = size
        self._state_js = None
        if "#state=" in url:
            url, self._state_js = url.split("#state=", 1)
        self._url = url if "://" in url else "file://" + os.path.abspath(url)
        self._page.goto(self._url)
        self._page.wait_for_load_state("load")

    def size(self):
        return self._size

    def stream(self, on=True):
        """Frames from Chrome's screencast instead of a screenshot per frame. A screenshot costs 35-50 ms whatever its
        size, which caps a loop near 15 frames a second; the screencast pushes every painted frame (60 a second), and
        frame() takes the first one painted after it was called. Chromium only."""
        if not on:
            if getattr(self, "_cdp", None):
                self._cdp.send("Page.stopScreencast")
            self._cdp = None
            return
        if getattr(self, "_cdp", None):
            return
        self._cdp = self._page.context.new_cdp_session(self._page)
        self._shot = None

        def got(e):
            self._shot = (e["metadata"].get("timestamp") or time.time(), e["data"])
            try:
                self._cdp.send("Page.screencastFrameAck", {"sessionId": e["sessionId"]})
            except Exception:  # noqa: BLE001
                pass

        self._cdp.on("Page.screencastFrame", got)
        self._cdp.send("Page.startScreencast", {"format": "png", "everyNthFrame": 1})

    def _streamed(self, wait_s=0.05):
        """The first screencast frame painted after now, or None when the page paints nothing new within wait_s (a
        still screen sends no frames: the caller takes a screenshot instead)."""
        t0, end = time.time(), time.perf_counter() + wait_s
        while time.perf_counter() < end:
            s = self._shot
            if s and s[0] >= t0 - 0.002:
                return cv2.imdecode(np.frombuffer(base64.b64decode(s[1]), dtype=np.uint8), cv2.IMREAD_COLOR)
            self._page.wait_for_timeout(2)       # lets the frame events in
        return None

    def frame(self):
        self._release_due()
        if getattr(self, "_cdp", None):
            img = self._streamed()
            if img is not None and img.shape[1] == self._size[0] and img.shape[0] == self._size[1]:
                return img
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

    def key(self, name, hold_ms=0, block=True, extend=False):
        p = getattr(self, "_pending_up", None)
        if extend and p and p[0] == name and hold_ms and not block:
            # the same key again while it is still held, for a hold that should last (a duck): keep holding (letting
            # go between would stand a ducking dino up for a frame), and let go hold_ms from now. Not for a press
            # that must come down anew to count (a jump)
            self._pending_up = (name, time.perf_counter() + hold_ms / 1000)
            return
        self._release_due(force=True)
        if hold_ms and hold_ms > 0 and not block:
            # a held key that does not stop the loop: down now, up on the first device call after hold_ms (the next
            # frame, usually), so a jump held 120 ms in a fast game does not cost a frame
            self._page.keyboard.down(name)
            self._pending_up = (name, time.perf_counter() + hold_ms / 1000)
        elif hold_ms and hold_ms > 0:
            # a held key: down, hold, up (what a run, a charge or a camera turn needs)
            self._page.keyboard.down(name)
            time.sleep(hold_ms / 1000)
            self._page.keyboard.up(name)
        else:
            self._page.keyboard.press(name)

    def _release_due(self, force=False):
        p = getattr(self, "_pending_up", None)
        if p and (force or time.perf_counter() >= p[1]):
            self._pending_up = None
            self._page.keyboard.up(p[0])

    def mouse_move(self, dx, dy):
        """Relative motion from the last pointer position (the page sees mousemove events with the movement)."""
        self._mx, self._my = getattr(self, "_mx", self.size()[0] // 2) + int(dx), getattr(self, "_my", self.size()[1] // 2) + int(dy)
        w, h = self.size()
        self._mx, self._my = max(0, min(w - 1, self._mx)), max(0, min(h - 1, self._my))
        self._page.mouse.move(self._mx, self._my, steps=max(2, int(np.hypot(dx, dy) // 8)))

    def back_if_navigated(self) -> bool:
        """A tap that followed a link left the game: go back to it. True when it had to."""
        if self._page.url.split("#")[0] == self._url.split("#")[0]:
            return False
        try:
            self._page.goto(self._url)
            self._page.wait_for_load_state("load")
        except Exception:  # noqa: BLE001
            pass
        return True

    def reload(self):
        """Reload the page: the cheapest restart for a browser game between episodes."""
        self._page.reload()
        self._page.wait_for_load_state("load")

    def state(self):
        """The page's own state when the URL named an expression, else None."""
        if not self._state_js:
            return None
        try:
            return self._page.evaluate(self._state_js)
        except Exception:  # noqa: BLE001
            return None

    def evaluate(self, js: str):
        """For tests: read the page's own truth to check perception against it."""
        return self._page.evaluate(js)

    def close(self):
        try:
            if getattr(self, "_cdp", None):
                self._cdp.send("Page.stopScreencast")
        except Exception:  # noqa: BLE001
            pass
        try:
            self._browser.close()
        finally:
            self._pw.stop()
