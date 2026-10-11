"""Make Pokemon Red test saves by walking with RAM (a test fixture, not the agent: the agent never reads RAM).

From a save, walk to the next map in a route by greedy moves on the RAM position, learning blocked steps as it goes, and
run from wild battles. Saves the state on arrival.

    python scripts/pokemon_fixture_walk.py IN.state OUT.state 0:10,0 12:-,0 1
    (each leg is MAP:X,Y, the spot to head for on that map, '-' for any; the last number is the map to stop on)
"""
from __future__ import annotations
import random
import shutil
import sys
import tempfile

ROM = "/mnt/project-files/roms/pokemon-red.gb"
MAP, X, Y, BATTLE, TEXT = 0xD35E, 0xD362, 0xD361, 0xD057, 0xC4F2
DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


def press(pb, b, hold=6, after=20):
    pb.button_press(b)
    pb.tick(hold)
    pb.button_release(b)
    pb.tick(after)


def flee(pb):
    """Mash through a wild battle: B to clear text, then RUN (bottom right of the battle menu)."""
    for _ in range(400):
        if not pb.memory[BATTLE]:
            return
        press(pb, "down"); press(pb, "right"); press(pb, "a", after=60); press(pb, "b", after=30)


def main() -> None:
    from pyboy import PyBoy
    src, out, *legs = sys.argv[1:]
    stop = int(legs.pop())
    goals = {}
    for leg in legs:
        m, xy = leg.split(":")
        gx, gy = xy.split(",")
        goals[int(m)] = (None if gx == "-" else int(gx), None if gy == "-" else int(gy))
    rom = tempfile.mkdtemp(prefix="pkfx-") + "/p.gb"
    shutil.copyfile(ROM, rom)
    pb = PyBoy(rom, window="null", sound_emulated=False)
    with open(src, "rb") as f:
        pb.load_state(f)
    pb.tick(2)
    rng = random.Random(0)
    blocked: set = set()
    m = pb.memory
    for i in range(20000):
        if m[BATTLE]:
            flee(pb)
            continue
        mp, x, y = m[MAP], m[X], m[Y]
        if mp == stop:
            break
        gx, gy = goals.get(mp, (None, None))
        opts = []
        for d, (dx, dy) in DIRS.items():
            if (mp, x, y, d) in blocked:
                continue
            dist = (abs(x + dx - gx) if gx is not None else 0) + (abs(y + dy - gy) if gy is not None else 0)
            opts.append((dist + rng.random() * 3, d))
        if not opts:
            blocked = {b for b in blocked if b[0] != mp}
            continue
        d = min(opts)[1] if rng.random() < 0.8 else rng.choice(opts)[1]
        press(pb, d, hold=8, after=12)
        if (m[MAP], m[X], m[Y]) == (mp, x, y) and not m[BATTLE]:
            press(pb, "b")
            if (m[MAP], m[X], m[Y]) == (mp, x, y):
                blocked.add((mp, x, y, d))
    print("map", m[MAP], "x", m[X], "y", m[Y], "presses", i)
    if m[MAP] == stop:
        for _ in range(60):
            pb.tick()
        with open(out, "wb") as f:
            pb.save_state(f)
        print("saved", out)
    pb.stop(save=False)


if __name__ == "__main__":
    main()
