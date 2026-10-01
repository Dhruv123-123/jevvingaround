"""One window, not the desktop: inputs are delivered to a single window and the person's focus, keyboard and mouse
stay theirs. Frames are that window's rectangle. `window://<title substring>` or `window://id=0x3a00005`; `?scale=`.

X11: python-xlib finds the window by name and sends synthetic KeyPress/ButtonPress events to it with XSendEvent.
Windows: PostMessage with WM_KEYDOWN/WM_LBUTTONDOWN to the window handle. Both are honest about their limit: a
game that reads raw input (DirectInput, XInput, evdev) ignores synthetic window messages. Browsers, toolkits and
casual games take them; shooters mostly do not, and for those `pad://` or `nested://` is the path."""
from __future__ import annotations
import sys
import time
from typing import Any

from .base import Device
from .guard import Guarded
from .screen import ScreenFrames

X_KEYS = {"ArrowUp": "Up", "ArrowDown": "Down", "ArrowLeft": "Left", "ArrowRight": "Right", "Space": "space", " ": "space", "Enter": "Return",
          "Escape": "Escape", "Shift": "Shift_L", "ShiftLeft": "Shift_L", "Tab": "Tab", "Backspace": "BackSpace", "Delete": "Delete", "Control": "Control_L", "Alt": "Alt_L"}


def _parse(spec: str) -> tuple[str, dict[str, str]]:
    q: dict[str, str] = {}
    if "?" in spec:
        spec, qs = spec.split("?", 1)
        q = dict(kv.split("=", 1) for kv in qs.split("&") if "=" in kv)
    return spec, q


class X11Window:
    """Find a window on an X display and send it events."""

    def __init__(self, spec: str, display: str | None = None):
        from Xlib import X, display as xdisplay, XK
        self.X, self.XK = X, XK
        self.d = xdisplay.Display(display)
        self.root = self.d.screen().root
        self.win = self._find(spec)
        if self.win is None:
            raise ValueError(f"window://{spec}: no window with that title or id")
        self.NET_WM_NAME = self.d.intern_atom("_NET_WM_NAME")

    def _name(self, w) -> str:
        try:
            n = w.get_full_property(self.d.intern_atom("_NET_WM_NAME"), 0)
            if n and n.value:
                return n.value.decode("utf-8", "ignore") if isinstance(n.value, bytes) else str(n.value)
            n = w.get_wm_name()
            return n.decode("utf-8", "ignore") if isinstance(n, bytes) else (n or "")
        except Exception:  # noqa: BLE001
            return ""

    def _find(self, spec: str):
        if spec.startswith("id="):
            return self.d.create_resource_object("window", int(spec[3:], 0))
        want = spec.lower()
        todo = [self.root]
        best = None
        while todo:
            w = todo.pop()
            try:
                kids = w.query_tree().children
            except Exception:  # noqa: BLE001
                continue
            for k in kids:
                name = self._name(k)
                if want and want in name.lower():
                    try:
                        g = k.get_geometry()
                        if g.width > 1 and g.height > 1 and (best is None or g.width * g.height > best[0]):
                            best = (g.width * g.height, k)
                    except Exception:  # noqa: BLE001
                        pass
                todo.append(k)
        return best[1] if best else None

    def rect(self) -> dict[str, int]:
        g = self.win.get_geometry()
        p = self.win.translate_coords(self.root, 0, 0)        # the window's origin in root coordinates (negated)
        return {"left": -p.x, "top": -p.y, "width": g.width, "height": g.height}

    def keycode(self, name: str) -> int:
        sym = self.XK.string_to_keysym(X_KEYS.get(name, name)) or self.XK.string_to_keysym(name.lower())
        return self.d.keysym_to_keycode(sym)

    def key(self, name: str, hold_ms: int) -> None:
        from Xlib.protocol import event
        kc = self.keycode(name)
        r = self.rect()
        for cls, delay in ((event.KeyPress, max(0.02, hold_ms / 1000)), (event.KeyRelease, 0)):
            ev = cls(time=self.X.CurrentTime, root=self.root, window=self.win, same_screen=1, child=self.X.NONE, root_x=r["left"], root_y=r["top"], event_x=1, event_y=1, state=0, detail=kc)
            self.win.send_event(ev, propagate=True)
            self.d.sync()
            time.sleep(delay)

    def button(self, x: int, y: int, down: bool, button: int = 1) -> None:
        from Xlib.protocol import event
        r = self.rect()
        cls = event.ButtonPress if down else event.ButtonRelease
        ev = cls(time=self.X.CurrentTime, root=self.root, window=self.win, same_screen=1, child=self.X.NONE, root_x=r["left"] + x, root_y=r["top"] + y, event_x=x, event_y=y, state=0 if down else self.X.Button1Mask, detail=button)
        self.win.send_event(ev, propagate=True)
        self.d.sync()

    def motion(self, x: int, y: int) -> None:
        from Xlib.protocol import event
        r = self.rect()
        ev = event.MotionNotify(time=self.X.CurrentTime, root=self.root, window=self.win, same_screen=1, child=self.X.NONE, root_x=r["left"] + x, root_y=r["top"] + y, event_x=x, event_y=y, state=0, detail=0)
        self.win.send_event(ev, propagate=True)
        self.d.sync()

    def close(self) -> None:
        self.d.close()


class Win32Window:
    """Windows: PostMessage to a window handle found by title."""
    VK = {"ArrowUp": 0x26, "ArrowDown": 0x28, "ArrowLeft": 0x25, "ArrowRight": 0x27, "Space": 0x20, " ": 0x20, "Enter": 0x0D, "Escape": 0x1B, "Shift": 0x10, "Tab": 0x09, "Backspace": 0x08, "Delete": 0x2E, "Control": 0x11, "Alt": 0x12}

    def __init__(self, spec: str):
        import ctypes
        self.u = ctypes.windll.user32
        if spec.startswith("id="):
            self.h = int(spec[3:], 0)
        else:
            want = spec.lower()
            found = []
            proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))
            def cb(h, _):
                n = ctypes.create_unicode_buffer(256)
                self.u.GetWindowTextW(h, n, 256)
                if want in n.value.lower() and self.u.IsWindowVisible(h):
                    found.append(h)
                return True
            self.u.EnumWindows(proc(cb), 0)
            if not found:
                raise ValueError(f"window://{spec}: no window with that title")
            self.h = found[0]

    def rect(self) -> dict[str, int]:
        import ctypes
        r = (ctypes.c_long * 4)()
        self.u.GetClientRect(self.h, r)
        pt = (ctypes.c_long * 2)()
        self.u.ClientToScreen(self.h, pt)
        return {"left": pt[0], "top": pt[1], "width": r[2], "height": r[3]}

    def key(self, name: str, hold_ms: int) -> None:
        vk = self.VK.get(name) or (ord(name.upper()) if len(name) == 1 else 0)
        self.u.PostMessageW(self.h, 0x0100, vk, 0)      # WM_KEYDOWN
        time.sleep(max(0.02, hold_ms / 1000))
        self.u.PostMessageW(self.h, 0x0101, vk, 0)      # WM_KEYUP

    def button(self, x: int, y: int, down: bool, button: int = 1) -> None:
        self.u.PostMessageW(self.h, 0x0201 if down else 0x0202, 1 if down else 0, (y << 16) | (x & 0xFFFF))

    def motion(self, x: int, y: int) -> None:
        self.u.PostMessageW(self.h, 0x0200, 0, (y << 16) | (x & 0xFFFF))

    def close(self) -> None:
        pass


class WindowDevice(Guarded, Device):
    def __init__(self, spec: str, size: tuple[int, int] | None = None, display: str | None = None):
        spec, q = _parse(spec)
        self.w = Win32Window(spec) if sys.platform == "win32" else X11Window(spec, display)
        r = self.w.rect()
        self._frames = ScreenFrames(f"{r['left']},{r['top']},{r['width']},{r['height']}?scale={q.get('scale', 1)}", display)
        self.scale = self._frames.scale
        self.max_actions_per_minute = int(q.get("budget", self.max_actions_per_minute))
        self._mx, self._my = r["width"] // 2, r["height"] // 2
        # the person keeps their own input: nothing we send reaches the focused window, so no pause is needed; the
        # kill switch and the budget stay
        self.pause_s = float(q.get("pause", 0))
        self._guard_start(listen=q.get("guard", "1") != "0", display=display)

    def size(self):
        return self._frames.size()

    def frame(self):
        r = self.w.rect()                      # the window may move: re-aim the capture every frame
        self._frames.region.update(r)
        return self._frames.frame()

    def _px(self, x: float, y: float) -> tuple[int, int]:
        return int(x / self.scale), int(y / self.scale)

    def key(self, name, hold_ms=0):
        if not self._allow():
            return
        self._own(max(30, hold_ms or 0) + 40)
        self.w.key(name, int(hold_ms or 0))

    def tap(self, x, y):
        if not self._allow():
            return
        px, py = self._px(x, y)
        self._own(80)
        self.w.motion(px, py); self.w.button(px, py, True); time.sleep(0.03); self.w.button(px, py, False)

    def swipe(self, x0, y0, x1, y1, ms=120):
        if not self._allow():
            return
        self._own(ms + 100)
        ax, ay = self._px(x0, y0); bx, by = self._px(x1, y1)
        self.w.motion(ax, ay); self.w.button(ax, ay, True)
        steps = max(4, ms // 15)
        for i in range(1, steps + 1):
            t = i / steps
            self.w.motion(int(ax + (bx - ax) * t), int(ay + (by - ay) * t)); time.sleep(ms / 1000 / steps)
        self.w.button(bx, by, False)

    def mouse_move(self, dx, dy):
        if not self._allow():
            return
        r = self.w.rect()
        self._mx = max(0, min(r["width"] - 1, self._mx + int(dx / self.scale))); self._my = max(0, min(r["height"] - 1, self._my + int(dy / self.scale)))
        self._own(60)
        self.w.motion(self._mx, self._my)

    def close(self):
        self._guard_stop()
        self._frames.close()
        self.w.close()
