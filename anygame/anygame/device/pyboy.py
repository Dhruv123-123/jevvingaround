"""A Game Boy ROM as a device, through PyBoy. Frames are the emulator screen scaled up; keys are the pad; the
game's RAM is its state.

    pyboy://roms/2048gb/2048.gb            # 3x nearest-neighbour: 480x432 frames
    pyboy://path/to/game.gb?scale=4&hold=6&after=16   # hold = frames a button stays pressed, after = frames run after it
    pyboy://game.gb?clock=game&step=8&state=saves/start.state   # the game waits for the decider; start from a save state

Two clocks. `clock=wall` (the default, for action games): the emulator only advances when the loop asks for a frame,
by as many frames as wall-clock time has passed since the last one (capped at a second), so the game keeps real time
while the model thinks. `clock=game` (RPGs, puzzles, anything turn-based): the game is frozen while the decider
thinks; each frame() runs `step` frames and each press runs its hold and `after` frames, so it plays as fast as the
CPU allows (thousands of frames a second headless) and a run is replayable from a save state.

RAM state. `use_pack()` hands the device the pack's `ram:` section, and state() returns it decoded every tick, for
the pack's `json` reads, exactly as a web game that publishes its state:

    ram:
      map:    { addr: 0xD35E }                         # u8 (the default)
      hp:     { addr: 0xD16C, type: u16 }              # big-endian; u16le for little-endian
      money:  { addr: 0xD347, type: bcd, len: 3 }      # 3 bytes of binary-coded decimal
      badges: { addr: 0xD356, type: bits }             # {count, on: [bit numbers set]}
      party:  { addr: 0xD164, type: bytes, len: 6 }    # a list of u8
      name:   { addr: 0xD158, type: text, len: 11, charmap: pokemon }   # stops at the terminator
      flag:   { addr: 0xD747, type: bit, bit: 3 }      # one bit as a bool
      lead:   { addr: 0xD16B, type: struct, stride: 44, count: 6, fields: { hp: { off: 1, type: u16 }, level: { off: 33 } } }

Swipes map to the d-pad, taps to A, so a pack written with swipes for a touch screen plays here unchanged.
"""
from __future__ import annotations
import os
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit
import numpy as np
import cv2
from .base import Device

BUTTONS = {"a", "b", "start", "select", "up", "down", "left", "right"}
KEY_ALIASES = {"arrowup": "up", "arrowdown": "down", "arrowleft": "left", "arrowright": "right", "enter": "start", "space": "a",
               "x": "a", "z": "b", "shift": "select"}

# Pokemon Red/Blue's text encoding (pret/pokered charmap.asm), the common subset; 0x50 ends a string
_PK = {0x7F: " ", 0xE0: "'", 0xE3: "-", 0xE6: "?", 0xE7: "!", 0xE8: ".", 0xF4: ",", 0xEF: "♂", 0xF5: "♀", 0xF3: "/", 0x9C: ":",
       0xBA: "é", 0x4E: "\n", 0x4F: "\n", 0x51: "\n", 0x55: "\n", 0x54: "POKé", 0x9A: "(", 0x9B: ")", 0x9D: ";", 0x9E: "[", 0x9F: "]"}
_PK.update({0x80 + i: chr(ord("A") + i) for i in range(26)})
_PK.update({0xA0 + i: chr(ord("a") + i) for i in range(26)})
_PK.update({0xF6 + i: str(i) for i in range(10)})
CHARMAPS: dict[str, dict[int, str]] = {"pokemon": _PK, "ascii": {i: chr(i) for i in range(32, 127)}}
TERMINATORS = {"pokemon": 0x50, "ascii": 0x00}


def decode(mem, spec: dict[str, Any]) -> Any:
    """One `ram:` entry from a memory view `mem` (anything indexable by address returning a byte)."""
    t = spec.get("type", "u8")
    a = int(spec["addr"]) if not isinstance(spec.get("addr"), str) else int(spec["addr"], 0)
    n = int(spec.get("len", 1))
    if t == "u8":
        return mem[a]
    if t == "i8":
        v = mem[a]
        return v - 256 if v > 127 else v
    if t in ("u16", "u16be"):
        return (mem[a] << 8) | mem[a + 1]
    if t == "u16le":
        return mem[a] | (mem[a + 1] << 8)
    if t == "u24":
        return (mem[a] << 16) | (mem[a + 1] << 8) | mem[a + 2]
    if t == "bcd":
        v = 0
        for i in range(n):
            b = mem[a + i]
            v = v * 100 + (b >> 4) * 10 + (b & 15)
        return v
    if t == "bit":
        return bool(mem[a] >> int(spec.get("bit", 0)) & 1)
    if t == "bits":
        on = [i * 8 + b for i in range(n) for b in range(8) if mem[a + i] >> b & 1]
        return {"count": len(on), "on": on}
    if t == "bytes":
        return [mem[a + i] for i in range(n)]
    if t == "text":
        cm = spec.get("charmap", "ascii")
        table = CHARMAPS.get(cm, {}) if isinstance(cm, str) else {int(k, 0) if isinstance(k, str) else int(k): v for k, v in cm.items()}
        stop = spec.get("stop", TERMINATORS.get(cm if isinstance(cm, str) else "", None))
        out = []
        for i in range(n):
            b = mem[a + i]
            if stop is not None and b == stop:
                break
            out.append(table.get(b, "") if spec.get("unknown", "drop") == "drop" else table.get(b, "?"))
        return "".join(out).strip()
    if t == "struct":
        stride, count = int(spec.get("stride", 1)), int(spec.get("count", 1))
        rows = []
        for k in range(count):
            row = {}
            for name, f in (spec.get("fields") or {}).items():
                f = dict(f) if isinstance(f, dict) else {"off": f}
                f["addr"] = a + k * stride + int(f.pop("off", 0))
                row[name] = decode(mem, f)
            rows.append(row)
        return rows
    raise ValueError(f"unknown ram type '{t}'")


def decode_all(mem, ram: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, spec in (ram or {}).items():
        try:
            out[k] = decode(mem, spec)
        except Exception as e:  # noqa: BLE001
            out[k] = None
            out.setdefault("_errors", {})[k] = str(e)[:80]
    return out


class PyBoyDevice(Device):
    rereadable = True

    def __init__(self, url: str, size: tuple[int, int] | None = None):
        from pyboy import PyBoy
        u = urlsplit(url if "://" in url else "pyboy://" + url)
        path = (u.netloc + u.path) if u.netloc else u.path
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if not os.path.exists(path):
            raise SystemExit(f"ROM not found: {path}")
        self.rom = path
        self.scale = int(q.get("scale", 3))
        self.hold = int(q.get("hold", 6))
        self.after = int(q.get("after", 16))     # frames to run after a press so slide animations finish before the next read
        self.fps = float(q.get("fps", 60))
        self.clock = q.get("clock", "wall")
        self.step_frames = int(q.get("step", 4))   # clock=game: frames each frame() runs
        self.ram: dict[str, Any] = {}
        self.discoverer = None                     # pack `discover: true`: position and map found from RAM while playing
        self.discover_file: str | None = None
        self.frames = 0                            # emulated frames since boot: the game's own clock
        self._pb = PyBoy(path, window="null", sound_emulated=False)
        self._pb.set_emulation_speed(0)
        self._last = time.perf_counter()
        if q.get("state"):
            self.load_state(q["state"])
        else:
            self._tick(int(q.get("boot", 120)), render=False)
        self._size = (160 * self.scale, 144 * self.scale)

    # ---- the clock ---------------------------------------------------------------------------------
    def _tick(self, n: int, render: bool = False) -> None:
        # only the last frame is drawn: the screen is always current, and the frames before it cost no rendering
        if n > 1:
            self._pb.tick(n - 1, False)
        if n > 0:
            self._pb.tick(1, True)
            self.frames += n
            if self.discoverer is not None:
                from ..discover import ram
                self.discoverer.frame(ram(self._pb.memory), bool(self._pb.screen.ndarray[:, :, :3].std() < 3))

    def wait(self, frames: int) -> None:
        self._tick(int(frames), render=False)

    def size(self):
        return self._size

    def frame(self):
        if self.clock == "game":
            self._tick(self.step_frames, render=True)
        else:
            now = time.perf_counter()
            n = int(min(1.0, now - self._last) * self.fps)
            self._last = now
            self._tick(n, render=True)
        return self.screen()

    def screen(self) -> np.ndarray:
        """The current screen without advancing the game."""
        rgb = self._pb.screen.ndarray[:, :, :3]
        bgr = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2BGR)
        return cv2.resize(bgr, self._size, interpolation=cv2.INTER_NEAREST)

    # ---- state -------------------------------------------------------------------------------------
    def use_pack(self, raw: dict[str, Any], pack_dir: str | None = None) -> None:
        """The pack's `ram:` map (and an optional `emulator:` block: clock, step, hold, after) configures the device.
        `discover: true` finds the position and map bytes while playing (anygame/discover.py); what it finds is kept
        in `discovered-<rom>.yaml` beside the pack (one per ROM, so one pack can serve many games) (or `discover_file`) and a later run starts from it."""
        self.ram = dict(raw.get("ram") or {})
        if raw.get("discover"):
            import yaml
            from ..discover import Discoverer
            self.discoverer = Discoverer()
            if os.environ.get("ANYGAME_DISCOVER_TRACE"):
                self.discoverer.trace = []
            self.discover_file = raw.get("discover_file") or (os.path.join(pack_dir, f"discovered-{os.path.splitext(os.path.basename(self.rom))[0]}.yaml") if pack_dir else None)
            if self.discover_file and os.path.exists(self.discover_file) and not os.environ.get("ANYGAME_REDISCOVER"):
                self.discoverer.load(yaml.safe_load(open(self.discover_file)) or {})
        emu = raw.get("emulator") or {}
        for k in ("clock", "step_frames", "hold", "after"):
            src = "step" if k == "step_frames" else k
            if src in emu:
                setattr(self, k, emu[src] if k == "clock" else int(emu[src]))

    @property
    def memory(self):
        return self._pb.memory

    def peek(self, addr: int, n: int = 1) -> list[int]:
        return [self._pb.memory[addr + i] for i in range(n)]

    def state(self) -> dict[str, Any] | None:
        if not self.ram and self.discoverer is None:
            return None
        s = decode_all(self._pb.memory, self.ram)
        if self.discoverer is not None:
            from ..discover import ram
            s["found"] = self.discoverer.state(ram(self._pb.memory))
        s["frames"] = self.frames
        return s

    def save_trace(self) -> None:
        path = os.environ.get("ANYGAME_DISCOVER_TRACE")
        if self.discoverer is None or self.discoverer.trace is None or not path:
            return
        import pickle
        import zlib
        with open(path, "wb") as f:
            f.write(zlib.compress(pickle.dumps(self.discoverer.trace), 1))

    def save_discovered(self) -> str | None:
        if self.discoverer is None or not self.discover_file or not self.discoverer.found:
            return None
        import yaml
        with open(self.discover_file, "w") as f:
            f.write("# found by anygame/discover.py while playing: the agent's own map of this game's RAM\n")
            yaml.safe_dump(self.discoverer.dump(), f, sort_keys=False)
        return self.discover_file

    # ---- branching: the emulator as the forward model of every game on it ------------------------------
    def snapshot(self) -> tuple[bytes, int]:
        import io
        b = io.BytesIO()
        self._pb.save_state(b)
        return b.getvalue(), self.frames

    def restore(self, snap: tuple[bytes, int]) -> None:
        import io
        self._pb.load_state(io.BytesIO(snap[0]))
        self.frames = snap[1]

    def branch(self, seqs: dict[str, list], frames: int = 16, hold: int = 4) -> dict[str, dict[str, Any]]:
        """Play each input sequence from the current moment for `frames` frames, then put the game back exactly as it
        was. Returns label → {screen, state}. Presses inside a branch teach the discoverer nothing."""
        snap = self.snapshot()
        disc, self.discoverer = self.discoverer, None
        out: dict[str, dict[str, Any]] = {}
        try:
            for label, keys in seqs.items():
                self.restore(snap)
                used = 0
                for k in keys:
                    k, _, h = str(k).partition(":")
                    h = int(h) if h else hold
                    self.press(k, hold=h, after=0)
                    used += h
                self._tick(max(1, frames - used), render=True)
                self.discoverer = disc
                from ..discover import ram
                out[label] = {"screen": self.screen(), "state": self.state(), "ram": ram(self._pb.memory)}
                self.discoverer = None
        finally:
            self.restore(snap)
            self.discoverer = disc
        return out

    def save_state(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "wb") as f:
            self._pb.save_state(f)
        with open(path + ".frames", "w") as f:
            f.write(str(self.frames))

    def load_state(self, path: str) -> None:
        with open(path, "rb") as f:
            self._pb.load_state(f)
        try:
            self.frames = int(open(path + ".frames").read())
        except (OSError, ValueError):
            pass
        self._tick(1, render=True)

    # ---- input -------------------------------------------------------------------------------------
    def _button(self, name: str) -> str:
        b = KEY_ALIASES.get(name.lower(), name.lower())
        if b not in BUTTONS:
            raise ValueError(f"no Game Boy button '{name}'")
        return b

    def press(self, button: str, hold: int | None = None, after: int | None = None):
        b = self._button(button)
        if self.discoverer is not None:
            from ..discover import ram
            before = ram(self._pb.memory)
        self._pb.button_press(b)
        self._tick(self.hold if hold is None else int(hold))
        self._pb.button_release(b)
        self._tick(self.after if after is None else int(after))
        if self.discoverer is not None:
            after_ = ram(self._pb.memory)
            self.discoverer.press(b, before, after_, full=hold is None or hold >= 8, continues=True)

    def key(self, name, hold_ms=0, **_):
        if hold_ms:
            self.press(name, hold=max(1, int(hold_ms / 1000 * 60)))     # the Game Boy runs ~60 frames a second
            return
        self.press(name)

    def tap(self, x, y):
        self.press("a")

    def swipe(self, x0, y0, x1, y1, ms=120):
        dx, dy = x1 - x0, y1 - y0
        self.press(("right" if dx > 0 else "left") if abs(dx) > abs(dy) else ("down" if dy > 0 else "up"))

    def close(self):
        try:
            self.save_discovered()
            self.save_trace()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._pb.stop(save=False)
        except Exception:  # noqa: BLE001
            pass
