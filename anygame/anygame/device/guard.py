"""Guard rails for any device that acts where a person might also be acting: a shared desktop, a window on it, a
virtual controller the game reads beside the real one. Three rules, all local and all cheap:

- pause on human input: a key or mouse event the device did not inject itself suspends acting for `pause_s`
  seconds (the loop keeps reading and says why it waits); the device's own injections are recognised by timing,
  since a listener cannot tell them apart otherwise
- a kill switch: a hotkey (Ctrl+Alt+Q by default) stops the run; the loop sees the device as exhausted
- an action budget: at most `max_actions_per_minute` inputs; the rest are dropped and counted, so a loop that goes
  wrong cannot flood the game or the desktop

Listeners need a display; without one (headless tests, a stream) the mixin runs with the budget only."""
from __future__ import annotations
import collections
import threading
import time
from typing import Any


class Guarded:
    pause_s: float = 3.0
    max_actions_per_minute: int = 300
    kill_hotkey: str = "ctrl+alt+q"

    def _guard_start(self, listen: bool = True, display: str | None = None) -> None:
        self._own_until = 0.0
        self._human_until = 0.0
        self._stopped = False
        self._stamps: collections.deque = collections.deque()
        self.human_events = 0
        self.dropped = 0
        self._mods: set[str] = set()
        self._listeners: list[Any] = []
        self._lock = threading.Lock()
        self.listening = False
        if not listen:
            return
        try:
            import os
            from pynput import keyboard, mouse
            saved = os.environ.get("DISPLAY")
            if display:
                os.environ["DISPLAY"] = display
            try:
                kl = keyboard.Listener(on_press=self._on_key, on_release=self._on_key_release)
                ml = mouse.Listener(on_move=lambda *a: self._on_human(), on_click=lambda *a: self._on_human(), on_scroll=lambda *a: self._on_human())
                kl.daemon = ml.daemon = True
                kl.start(); ml.start()
            finally:
                if display:
                    if saved is None:
                        os.environ.pop("DISPLAY", None)
                    else:
                        os.environ["DISPLAY"] = saved
            self._listeners = [kl, ml]
            self.listening = True
        except Exception:  # noqa: BLE001 — no display or no pynput: budget only
            self.listening = False

    # ---- what the device calls around its own injections
    def _own(self, ms: float) -> None:
        """Our own injection is in flight for `ms`: events seen meanwhile are ours, not a person's."""
        with self._lock:
            self._own_until = max(self._own_until, time.monotonic() + ms / 1000 + 0.08)

    def _allow(self) -> bool:
        """The budget: True when this action may go out now."""
        now = time.monotonic()
        with self._lock:
            while self._stamps and now - self._stamps[0] > 60:
                self._stamps.popleft()
            if self._stopped or len(self._stamps) >= self.max_actions_per_minute:
                self.dropped += 1
                return False
            self._stamps.append(now)
            return True

    # ---- what the listeners call
    def _on_human(self) -> None:
        now = time.monotonic()
        with self._lock:
            if now <= self._own_until:
                return
            self.human_events += 1
            self._human_until = now + self.pause_s

    def _on_key(self, key) -> None:
        name = _key_name(key)
        if name in ("ctrl", "alt", "shift", "cmd"):
            self._mods.add(name)
        want = set(self.kill_hotkey.lower().split("+"))
        if name and (self._mods | {name}) >= want:
            self.stop()
            return
        self._on_human()

    def _on_key_release(self, key) -> None:
        name = _key_name(key)
        self._mods.discard(name)

    # ---- what the loop reads
    @property
    def paused(self) -> bool:
        return time.monotonic() < self._human_until

    @property
    def exhausted(self) -> bool:
        return self._stopped

    def stop(self) -> None:
        self._stopped = True

    def guard_status(self) -> dict[str, Any]:
        return {"paused": self.paused, "human_events": self.human_events, "dropped": self.dropped, "stopped": self._stopped, "listening": self.listening}

    def _guard_stop(self) -> None:
        for l in self._listeners:
            try:
                l.stop()
            except Exception:  # noqa: BLE001
                pass
        self._listeners = []


def _key_name(key) -> str:
    """A pynput key → a short lowercase name: 'ctrl', 'alt', 'q', …"""
    n = getattr(key, "name", None)
    if n:
        n = n.lower()
        for base in ("ctrl", "alt", "shift", "cmd"):
            if n.startswith(base):
                return base
        return n
    c = getattr(key, "char", None)
    if c:
        return c.lower()
    vk = getattr(key, "vk", None)
    if vk and 65 <= vk <= 90:        # a letter arrives as a virtual key while Ctrl is held
        return chr(vk).lower()
    return ""
