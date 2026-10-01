"""A virtual gamepad: the game sees a second controller, the person keeps their keyboard and mouse. Frames come from
a screen region like `screen://`; inputs go to a virtual device the OS presents to the game. `pad://x,y,w,h` with
`?backend=uinput` (Linux, python-evdev, needs /dev/uinput) or `?backend=vigem` (Windows, the vgamepad package over
the ViGEm bus driver). Pack keys map to buttons and the d-pad (ArrowUp → d-pad up, Space or a → A, b → B, x, y,
l, r, Enter → Start, Escape → Select); an evdev button name (BTN_SOUTH, DPAD_LEFT, LS_UP) is taken as is.
`mouse_move` deflects the right stick for a moment, which is what a camera reads. Guard rails as on screen://."""
from __future__ import annotations
import time
from typing import Any

from .base import Device
from .guard import Guarded
from .screen import ScreenFrames

BUTTONS = {"a": "BTN_SOUTH", "space": "BTN_SOUTH", "b": "BTN_EAST", "escape": "BTN_SELECT", "x": "BTN_WEST", "y": "BTN_NORTH",
           "l": "BTN_TL", "r": "BTN_TR", "enter": "BTN_START", "start": "BTN_START", "select": "BTN_SELECT",
           "arrowup": "DPAD_UP", "arrowdown": "DPAD_DOWN", "arrowleft": "DPAD_LEFT", "arrowright": "DPAD_RIGHT",
           "w": "LS_UP", "s": "LS_DOWN", "d": "LS_RIGHT"}      # a (left) is the A button; use LS_LEFT by name for the stick
HAT = {"DPAD_UP": ("ABS_HAT0Y", -1), "DPAD_DOWN": ("ABS_HAT0Y", 1), "DPAD_LEFT": ("ABS_HAT0X", -1), "DPAD_RIGHT": ("ABS_HAT0X", 1)}
STICK = {"LS_UP": ("ABS_Y", -1), "LS_DOWN": ("ABS_Y", 1), "LS_LEFT": ("ABS_X", -1), "LS_RIGHT": ("ABS_X", 1),
         "RS_UP": ("ABS_RY", -1), "RS_DOWN": ("ABS_RY", 1), "RS_LEFT": ("ABS_RX", -1), "RS_RIGHT": ("ABS_RX", 1)}
RANGE = 32767


def button_of(name: str) -> str:
    """A pack key name → BTN_*, DPAD_* or LS_*/RS_*."""
    if name.upper() == name and ("BTN_" in name or "DPAD_" in name or name[:3] in ("LS_", "RS_")):
        return name
    return BUTTONS.get(name.lower(), "BTN_SOUTH")


class UInputBackend:
    """Linux: a uinput gamepad through python-evdev."""

    def __init__(self):
        from evdev import AbsInfo, UInput, ecodes as e
        self.e = e
        absinfo = AbsInfo(value=0, min=-RANGE, max=RANGE, fuzz=16, flat=128, resolution=0)
        hat = AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)
        caps = {e.EV_KEY: [e.BTN_SOUTH, e.BTN_EAST, e.BTN_NORTH, e.BTN_WEST, e.BTN_TL, e.BTN_TR, e.BTN_SELECT, e.BTN_START, e.BTN_MODE, e.BTN_THUMBL, e.BTN_THUMBR],
                e.EV_ABS: [(e.ABS_X, absinfo), (e.ABS_Y, absinfo), (e.ABS_RX, absinfo), (e.ABS_RY, absinfo), (e.ABS_HAT0X, hat), (e.ABS_HAT0Y, hat)]}
        self.ui = UInput(caps, name="anygame virtual gamepad", vendor=0x045e, product=0x028e, version=1)

    def button(self, name: str, down: bool) -> None:
        self.ui.write(self.e.EV_KEY, getattr(self.e, name), 1 if down else 0); self.ui.syn()

    def axis(self, name: str, value: int) -> None:
        self.ui.write(self.e.EV_ABS, getattr(self.e, name), value); self.ui.syn()

    def close(self) -> None:
        self.ui.close()


class ViGEmBackend:
    """Windows: an Xbox 360 pad through vgamepad (ViGEmBus)."""

    def __init__(self):
        import vgamepad as vg
        self.vg, self.pad = vg, vg.VX360Gamepad()
        self.map = {"BTN_SOUTH": vg.XUSB_BUTTON.XUSB_GAMEPAD_A, "BTN_EAST": vg.XUSB_BUTTON.XUSB_GAMEPAD_B, "BTN_WEST": vg.XUSB_BUTTON.XUSB_GAMEPAD_X, "BTN_NORTH": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
                    "BTN_TL": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER, "BTN_TR": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER, "BTN_START": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
                    "BTN_SELECT": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK, "DPAD_UP": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP, "DPAD_DOWN": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
                    "DPAD_LEFT": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT, "DPAD_RIGHT": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT}
        self.axes = {"ABS_X": 0.0, "ABS_Y": 0.0, "ABS_RX": 0.0, "ABS_RY": 0.0}

    def button(self, name: str, down: bool) -> None:
        b = self.map.get(name)
        if b is not None:
            (self.pad.press_button if down else self.pad.release_button)(button=b); self.pad.update()

    def axis(self, name: str, value: int) -> None:
        if name in ("ABS_HAT0X", "ABS_HAT0Y"):
            for n, (ax, sgn) in HAT.items():
                if ax == name:
                    self.button(n, value == sgn)
            return
        self.axes[name] = value / RANGE
        self.pad.left_joystick_float(x_value_float=self.axes["ABS_X"], y_value_float=-self.axes["ABS_Y"])
        self.pad.right_joystick_float(x_value_float=self.axes["ABS_RX"], y_value_float=-self.axes["ABS_RY"])
        self.pad.update()

    def close(self) -> None:
        self.pad.reset(); self.pad.update()


class PadDevice(Guarded, Device):
    def __init__(self, spec: str, size: tuple[int, int] | None = None, backend: Any = None):
        self._frames = ScreenFrames(spec)
        q = self._frames.query
        if backend is None:
            kind = q.get("backend", "uinput")
            backend = ViGEmBackend() if kind == "vigem" else UInputBackend()
        self.pad = backend
        self.press_ms = int(q.get("press", 60))
        self.max_actions_per_minute = int(q.get("budget", self.max_actions_per_minute))
        self._guard_start(listen=q.get("guard", "1") != "0")

    def size(self):
        return self._frames.size()

    def frame(self):
        return self._frames.frame()

    def _press(self, name: str, hold_ms: int) -> None:
        self._own(hold_ms + 40)
        if name in HAT:
            ax, v = HAT[name]
            self.pad.axis(ax, v); time.sleep(hold_ms / 1000); self.pad.axis(ax, 0)
        elif name in STICK:
            ax, v = STICK[name]
            self.pad.axis(ax, v * RANGE); time.sleep(hold_ms / 1000); self.pad.axis(ax, 0)
        else:
            self.pad.button(name, True); time.sleep(hold_ms / 1000); self.pad.button(name, False)

    def key(self, name, hold_ms=0):
        if not self._allow():
            return
        self._press(button_of(name), max(self.press_ms, int(hold_ms or 0)))

    def tap(self, x, y):
        """A pad has no pointer: a tap is the primary button."""
        self.key("a")

    def swipe(self, x0, y0, x1, y1, ms=120):
        """A swipe is the d-pad in that direction for the swipe's duration."""
        if not self._allow():
            return
        dx, dy = x1 - x0, y1 - y0
        name = ("DPAD_RIGHT" if dx > 0 else "DPAD_LEFT") if abs(dx) >= abs(dy) else ("DPAD_DOWN" if dy > 0 else "DPAD_UP")
        self._press(name, max(self.press_ms, int(ms)))

    def mouse_move(self, dx, dy):
        """The right stick, deflected in proportion for a moment: what a camera reads."""
        if not self._allow():
            return
        self._own(140)
        sx, sy = max(-1.0, min(1.0, dx / 200)), max(-1.0, min(1.0, dy / 200))
        self.pad.axis("ABS_RX", int(sx * RANGE)); self.pad.axis("ABS_RY", int(sy * RANGE))
        time.sleep(0.1)
        self.pad.axis("ABS_RX", 0); self.pad.axis("ABS_RY", 0)

    def close(self):
        self._guard_stop()
        try:
            self.pad.close()
        finally:
            self._frames.close()
