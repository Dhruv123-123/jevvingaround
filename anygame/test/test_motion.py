"""Motion: what each button does to the player, learned from branches of a tiny scripted game's memory."""
import numpy as np
from anygame.motion import describe, learn

X, Y, NOISE = 0xC100, 0xC101, 0xC200


class Platformer:
    """Side view. A held direction walks 1 a frame (B with it runs 2 a frame); A jumps: 3 up a frame for 8 frames, then
    back down; up and down do nothing. A timer byte counts frames, and a junk byte jumps around."""

    def __init__(self):
        self.mem = np.zeros(0x10000, np.int64)
        self.mem[X], self.mem[Y] = 40, 100
        self.down: set[str] = set()
        self.vy = 0
        self.air = 0
        self.frames = 0
        self.discoverer = None

    @property
    def memory(self):
        return self.mem

    def snapshot(self):
        return (self.mem.copy(), set(self.down), self.vy, self.air, self.frames)

    def restore(self, s):
        self.mem, self.down, self.vy, self.air, self.frames = s[0].copy(), set(s[1]), s[2], s[3], s[4]

    def _frame(self):
        self.frames += 1
        self.mem[0xC000] = self.frames % 256                   # a timer: moves while waiting too
        self.mem[NOISE] = (self.frames * 97 + 13) % 256        # junk
        step = 2 if "b" in self.down else 1
        if "right" in self.down:
            self.mem[X] = (self.mem[X] + step) % 256
        if "left" in self.down:
            self.mem[X] = (self.mem[X] - step) % 256
        if "a" in self.down and self.air == 0 and self.mem[Y] == 100:
            self.air = 16
        if self.air:
            self.mem[Y] += -3 if self.air > 8 else 3
            self.air -= 1

    def wait(self, n):
        for _ in range(n):
            self._frame()

    def hold_keys(self, keys, n):
        self.down |= set(keys)
        self.wait(n)

    def release_keys(self, keys):
        self.down -= set(keys)

    def press(self, k, hold=4, after=10):
        self.hold_keys([k], hold)
        self.release_keys([k])
        self.wait(after)


def test_a_platformer_walks_runs_and_jumps():
    g = Platformer()
    before = g.snapshot()
    m = learn(g)
    assert m["axes"]["x"][0] == hex(X) and m["axes"]["y"][0] == hex(Y) and m["side_view"]
    by = {(tuple(x["keys"]), x["hold"]): x for x in m["moves"]}
    assert by[(("right",), 32)]["reach_x"] == 32 and by[(("right",), 8)]["reach_x"] == 8
    assert by[(("right", "b"), 32)]["reach_x"] == 64                       # B with a direction runs
    assert by[(("a",), 32)]["kind"] == "jump" and by[(("a",), 32)]["reach_y"] == -24
    assert by[(("up",), 32)]["kind"] == "nothing"
    lines = dict(line.split(": ", 1) for line in describe(m))
    assert lines["right"].startswith("east 32, 1.00 a frame while held") and "jumps 24 up" in lines["a"]
    assert np.array_equal(g.mem, before[0]) and g.frames == before[4]       # put back exactly


class TileWalker(Platformer):
    """Top view on a grid: a tap moves a whole tile of 16 even when released early; holding keeps walking."""

    def _frame(self):
        self.frames += 1
        self.mem[0xC000] = self.frames % 256
        if not getattr(self, "walk", None):
            for d, (dx, dy) in {"right": (1, 0), "left": (-1, 0), "down": (0, 1), "up": (0, -1)}.items():
                if d in self.down:
                    self.walk = [dx, dy, 16]
                    break
        if getattr(self, "walk", None):
            dx, dy, n = self.walk
            self.mem[X] += dx
            self.mem[Y] += dy
            self.walk = [dx, dy, n - 1] if n > 1 else None

    def snapshot(self):
        return super().snapshot() + (getattr(self, "walk", None),)

    def restore(self, s):
        super().restore(s[:5])
        self.walk = s[5]


def test_a_tile_walker_steps_a_whole_tile_for_a_tap():
    g = TileWalker()
    m = learn(g)
    assert not m["side_view"]
    by = {(tuple(x["keys"]), x["hold"]): x for x in m["moves"]}
    assert by[(("right",), 8)]["reach_x"] == 16 and by[(("right",), 32)]["reach_x"] == 32
    assert by[(("down",), 8)]["reach_y"] == 16
    assert "16 for a 8-frame tap" in dict(line.split(": ", 1) for line in describe(m))["right"]
