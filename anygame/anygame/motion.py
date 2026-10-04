"""What each button does to the player, learned by trying it from a save state: a step, a run, a jump, a dash, or
nothing. Nothing here knows a game.

A world tracker that moves one tile per d-pad press cannot play a platformer, a racer, or Pokemon on a bike: there a
press of A is a jump, B held with a direction is a run, a held direction keeps going, and a ledge carries the player
two tiles. So before planning, try each input from the current moment and watch where the player goes:

  1. from a snapshot, hold each input (a direction, A, B, a direction with A or B) for a few lengths of time, and
     record memory every few frames (work RAM, HRAM, and the sprite table);
  2. find the player's axes: x is the memory that goes one way for right and the other way for left, compared with
     just waiting (y the same with up and down). The Game Boy's sprite table says which of its bytes is an x and which
     a y, and a sprite (where the player is drawn) is preferred. In a side view, where up and down move nothing, y
     is the sprite y paired with the x, or the memory A or B moves up and brings back;
  3. describe each input by how x and y moved compared with waiting: how far, how fast, whether it kept going while
     held (a walk or a run) or stopped (a step), and whether y went out and came back (a jump), and how high and for
     how long;
  4. put the game back exactly as it was.

    from anygame.motion import learn, describe
    m = learn(device)                    # {axes, moves: [{keys, hold, dx, dy, kind, ...}]}
    describe(m)  →  ["right: east 32, 0.94 a frame while held (16 for a 8-frame tap)", "b: jumps 45 up, 24 frames in
                     the air", ...]
"""
from __future__ import annotations
from typing import Any

import numpy as np

# memory looked at: work RAM, the sprite table (sprite y, x at bytes 0 and 1 of each 4) and high RAM
SPANS = ((0xC000, 0xE000), (0xFE00, 0xFEA0), (0xFF80, 0xFFFF))
INPUTS = (("right",), ("left",), ("up",), ("down",), ("a",), ("b",), ("right", "a"), ("right", "b"), ("left", "a"),
          ("left", "b"))
HOLDS = (8, 32)


_N = sum(hi - lo for lo, hi in SPANS)
OAM_MASK = np.zeros(_N, bool)
OAM_OFFSET = np.full(_N, -1)
_o = SPANS[0][1] - SPANS[0][0]
OAM_MASK[_o:_o + 0xA0] = True
OAM_OFFSET[_o:_o + 0xA0] = np.arange(0xA0) % 4
OAM_ROLE = {"y": 0, "x": 1}


def snapshot_memory(mem) -> np.ndarray:
    parts = []
    for lo, hi in SPANS:
        try:
            parts.append(np.asarray(mem[lo:hi], dtype=np.int16))
        except TypeError:
            parts.append(np.array([mem[a] for a in range(lo, hi)], dtype=np.int16))
    return np.concatenate(parts)


def address(i: int) -> int:
    for lo, hi in SPANS:
        if i < hi - lo:
            return lo + i
        i -= hi - lo
    raise IndexError(i)


def _signed(d: np.ndarray) -> np.ndarray:
    """Byte differences as small signed numbers: 255 → -1 (a position that wraps)."""
    return ((d + 128) % 256) - 128


def trace(device, keys: tuple[str, ...], hold: int, frames: int, every: int = 2) -> np.ndarray:
    """Memory every `every` frames while `keys` are held for `hold` frames, then released, up to `frames`. Rows are
    samples. Uses device.hold_keys(keys, n) when the device has it (several buttons at once), else presses them in turn."""
    out = [snapshot_memory(device.memory)]
    t = 0
    held = False
    while t < frames:
        n = min(every, frames - t)
        if keys and t < hold:
            n = min(n, hold - t)
            _hold(device, keys, n)
            held = True
        else:
            if held:
                _release(device, keys)
                held = False
            device.wait(n)
        t += n
        out.append(snapshot_memory(device.memory))
    if held:
        _release(device, keys)
    return np.stack(out)


def _hold(device, keys, n):
    """Hold `keys` together for n more frames (they stay down until _release)."""
    if callable(getattr(device, "hold_keys", None)):
        device.hold_keys(list(keys), n)
        return
    pb = getattr(device, "_pb", None)
    if pb is not None and hasattr(device, "_button"):
        # the PyBoy device has no several-buttons-at-once call yet: press its emulator's buttons directly
        for k in keys:
            pb.button_press(device._button(k))
        device._tick(n)
        return
    device.press(keys[0], hold=n, after=0)          # any other device: the first button only


def _release(device, keys):
    if callable(getattr(device, "release_keys", None)):
        device.release_keys(list(keys))
        return
    pb = getattr(device, "_pb", None)
    if pb is not None and hasattr(device, "_button"):
        for k in keys:
            pb.button_release(device._button(k))


def _rel(tr: np.ndarray, wait: np.ndarray) -> np.ndarray:
    """Each byte's path compared with waiting, unwrapped (a byte that wraps 255 → 0 keeps counting): samples x bytes."""
    n = min(len(tr), len(wait))
    step = _signed(np.diff(tr[:n], axis=0)) - _signed(np.diff(wait[:n], axis=0))
    return np.vstack([np.zeros((1, tr.shape[1]), dtype=np.int64), np.cumsum(step, axis=0)])


def _steady(rel: np.ndarray, way: int, max_step: int = 8) -> np.ndarray:
    """Per byte: it answered the press by moving `way` (+1 or -1) in small steps: its first move went that way and it
    got at least 2 that way. What a position does under a held direction, even when a wall or a bump then pushes it
    back. A counter, a timer or the stack moves in jumps, or first the other way."""
    d = np.diff(rel, axis=0)
    small = (np.abs(d) <= max_step).all(axis=0)
    moved = d != 0
    first = np.where(moved.any(axis=0), d[np.argmax(moved, axis=0), np.arange(d.shape[1])], 0)
    return small & (first * way > 0) & ((rel * way).max(axis=0) >= 2)


def _reach(rel: np.ndarray, way: int) -> np.ndarray:
    return np.abs((rel * way).max(axis=0))


def axes(traces: dict[tuple, np.ndarray], wait: np.ndarray, top: int = 3) -> dict[str, list[int]]:
    """The memory that is the player's x (right vs left) and y (down vs up): the indices that moved steadily one way
    for one direction and steadily the other way for the other, compared with waiting, by the most. A negative index
    -(i+1) is a byte that falls going right (or down)."""
    out: dict[str, list[int]] = {}
    for name, plus, minus in (("x", ("right",), ("left",)), ("y", ("down",), ("up",))):
        if plus not in traces or minus not in traces:
            continue
        p, m = _rel(traces[plus], wait), _rel(traces[minus], wait)
        # one way may be blocked (a wall, the road's edge): moving one way only counts for a byte that holds still
        # while the player waits (in a side view y never holds still, and up or down alone is a crouch, not a move)
        rest = (wait == wait[:1]).all(axis=0)
        still_p = (np.abs(p) < 2).all(axis=0) & rest
        still_m = (np.abs(m) < 2).all(axis=0) & rest
        grows = (_steady(p, 1) & (_steady(m, -1) | still_m)) | (still_p & _steady(m, -1))
        falls = (_steady(p, -1) & (_steady(m, 1) | still_m)) | (still_p & _steady(m, 1))
        both = ~(still_p | still_m)
        # a byte that moved both ways ranks above any that moved one way only
        rp = np.maximum(_reach(p, 1), _reach(p, -1))
        rm = np.maximum(_reach(m, 1), _reach(m, -1))
        size = np.where(both, 1000 + np.minimum(rp, rm), np.maximum(rp, rm))
        score = np.where(grows | falls, size, 0)
        for j in out.get("x", []):
            score[j if j >= 0 else -j - 1] = 0          # one byte is not both axes
        # the Game Boy's sprite table says which byte is which (y, x, tile, flags per sprite): a sprite's x byte can
        # only be x and its y byte only y, and a sprite byte (where the player is drawn) is preferred
        role = OAM_ROLE[name]
        score = np.where(OAM_MASK & (OAM_OFFSET != role), 0, score + np.where(OAM_MASK & (score > 0), 20.0, 0.0))
        score = np.where(OAM_MASK & falls, 0, score)     # a sprite's x grows to the right and its y downward
        # a copy of a sprite byte elsewhere (a shadow table the game copies in) takes that byte's role
        oam = np.flatnonzero(OAM_MASK)
        for i in np.flatnonzero(score > 0):
            if OAM_MASK[i]:
                continue
            same = oam[(p[:, oam] == p[:, [i]]).all(axis=0) & (m[:, oam] == m[:, [i]]).all(axis=0)]
            if len(same) and (not (OAM_OFFSET[same] == role).any() or falls[i]):
                score[i] = 0
        best = [int(i) for i in np.argsort(-score, kind="stable")[:top] if score[i] > 0]
        out[name] = [i if grows[i] else -(i + 1) for i in best]
    return out


def _series(tr: np.ndarray, wait: np.ndarray, idx: int) -> np.ndarray:
    i = idx if idx >= 0 else -idx - 1
    r = _rel(tr[:, i:i + 1], wait[:, i:i + 1])[:, 0].astype(float)
    return r if idx >= 0 else -r


def _kind(dx: np.ndarray, dy: np.ndarray, hold_rows: int) -> dict[str, Any]:
    """How the player moved, from x and y relative to waiting, sample by sample."""
    def reach(v):
        return float(v[np.argmax(np.abs(v))]) if len(v) else 0.0
    rx, ry = reach(dx), reach(dy)
    air = int((np.abs(dy) > max(2.0, 0.25 * abs(ry))).sum())
    d = {"dx": round(float(dx[-1]), 1), "dy": round(float(dy[-1]), 1), "reach_x": round(rx, 1), "reach_y": round(ry, 1),
         "air_samples": air, "dx_held": round(float(dx[min(hold_rows, len(dx) - 1)]), 1)}
    if ry <= -4 and abs(d["dy"]) <= 0.4 * abs(ry):
        d["kind"] = "jump"
    elif abs(rx) < 1 and abs(ry) < 1:
        d["kind"] = "nothing"
    else:
        d["kind"] = "move"
    return d


def _oam(i: int) -> bool:
    return 0xFE00 <= address(i) < 0xFEA0


def _side_y(traces, wait, ax) -> list[int]:
    """In a side view up and down do not move the player. Its y is then the sprite y paired with its sprite x (the
    byte before it in the Game Boy's sprite table), or else the memory that A or B moves up steadily and brings back."""
    for j in ax.get("x", []):
        i = j if j >= 0 else -j - 1
        if _oam(i) and (address(i) - 0xFE00) % 4 == 1:
            return [i - 1]
    best, best_score = None, 0.0
    longest = max(h for (_, h) in traces)
    for button in ("a", "b"):
        trs = [tr for (keys, h), tr in traces.items() if keys == (button,) and h == longest]
        for tr in trs:
            r = _rel(tr, wait)
            small = (np.abs(np.diff(r, axis=0)) <= 8).all(axis=0)
            peak = np.abs(r).max(axis=0)
            back = np.abs(r[-1])
            score = np.where(small & (back <= 0.4 * peak), peak, 0)
            i = int(np.argmax(score))
            if score[i] > best_score:
                best, best_score = i, float(score[i])
    if best is None or best_score < 4:
        return []
    return [best]


def learn(device, inputs=INPUTS, holds=HOLDS, frames: int = 64, every: int = 2) -> dict[str, Any]:
    """Try every input for every hold length from now; return the axes found and how each input moved the player.
    The game is put back as it was."""
    snap = device.snapshot()
    disc, device.discoverer = getattr(device, "discoverer", None), None
    traces: dict[tuple, np.ndarray] = {}
    try:
        wait = trace(device, (), 0, frames, every)
        device.restore(snap)
        for keys in inputs:
            for h in holds:
                traces[(keys, h)] = trace(device, keys, h, frames, every)
                device.restore(snap)
    finally:
        device.restore(snap)
        device.discoverer = disc
    longest = max(holds)
    ax = axes({k: v for (k, h), v in traces.items() if h == longest}, wait)
    side = not ax.get("y")
    if side:
        y = _side_y(traces, wait, ax)
        if y:
            ax["y"] = y           # screen y: smaller is higher
    moves = []
    for (keys, h), tr in traces.items():
        dx = _series(tr, wait, ax["x"][0]) if ax.get("x") else np.zeros(len(tr))
        dy = _series(tr, wait, ax["y"][0]) if ax.get("y") else np.zeros(len(tr))
        moves.append({"keys": list(keys), "hold": h, **_kind(dx, dy, h // every)})
    return {"axes": {k: [hex(address(i if i >= 0 else -i - 1)) + ("" if i >= 0 else " (falls going right/down)")
                         for i in v] for k, v in ax.items()},
            "side_view": side, "moves": moves, "frames": frames, "every": every}


def describe(m: dict[str, Any]) -> list[str]:
    """One line per input (its longest hold), for the decider and for a person."""
    longest = max(x["hold"] for x in m["moves"]) if m["moves"] else 0
    short = {tuple(x["keys"]): x for x in m["moves"] if x["hold"] != longest}
    lines = []
    for x in m["moves"]:
        if x["hold"] != longest:
            continue
        k = "+".join(x["keys"])
        s = short.get(tuple(x["keys"]))
        bits = []
        if abs(x["reach_x"]) >= 1:
            way = "east" if x["reach_x"] > 0 else "west"
            speed = abs(x["dx_held"]) / max(1, x["hold"])
            keeps = s is not None and abs(x["reach_x"]) > 1.5 * max(1.0, abs(s["reach_x"]))
            tap = f" ({abs(s['reach_x']):.0f} for a {s['hold']}-frame tap)" if s is not None and abs(s["reach_x"]) >= 1 else ""
            b = f"{way} {abs(x['reach_x']):.0f}" + (f", {speed:.2f} a frame while held" if keeps else ", then stops") + tap
            if abs(x["dx"]) < 0.5 * abs(x["reach_x"]):
                b += f", pushed back to {x['dx']:+.0f}"
            bits.append(b)
        if x["kind"] == "jump":
            bits.append(f"jumps {abs(x['reach_y']):.0f} up, {x['air_samples'] * m['every']} frames in the air")
        elif abs(x["reach_y"]) >= 1:
            bits.append(f"{'south' if x['reach_y'] > 0 else 'north'} {abs(x['reach_y']):.0f}")
        lines.append(f"{k}: " + ("; ".join(bits) if bits else "moves nothing"))
    return lines
