"""Make Pokemon Red test saves by walking with RAM (a test fixture, not the agent: the agent never reads RAM).

From a save, walk to the next map in a route by greedy moves on the RAM position, learning blocked steps as it goes, and
run from wild battles. Saves the state on arrival.

    python scripts/pokemon_fixture_walk.py IN.state OUT.state 0:10,0 12:-,0 1
    (each leg is MAP:X,Y, the spot to head for on that map, '-' for any, taken in order; the last argument is the map
    to stop on, or MAP@X,Y to stop on a spot)
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


def route(mp, x, y, goal, blocked, rng):
    """First step of a shortest path to the goal over the steps not yet seen blocked (unseen steps count as open)."""
    gx, gy = goal
    if gx is None and gy is None:
        return rng.choice(list(DIRS))
    from collections import deque
    order = list(DIRS)
    rng.shuffle(order)
    seen = {(x, y): None}
    todo = deque([(x, y)])
    while todo:
        cx, cy = todo.popleft()
        if (gx is None or cx == gx) and (gy is None or cy == gy):
            while seen[(cx, cy)] is not None and seen[(cx, cy)][0] != (x, y):
                cx, cy = seen[(cx, cy)][0]
            return seen[(cx, cy)][1] if seen[(cx, cy)] else rng.choice(order)
        for d in order:
            dx, dy = DIRS[d]
            nx, ny = cx + dx, cy + dy
            if (mp, cx, cy, d) in blocked or (nx, ny) in seen or not (-1 <= nx <= 60 and -1 <= ny <= 60):
                continue
            seen[(nx, ny)] = ((cx, cy), d)
            todo.append((nx, ny))
    return None


def main() -> None:
    from pyboy import PyBoy
    src, out, *legs = sys.argv[1:]
    stop = legs.pop()
    spot = None
    if "@" in stop:
        stop, xy = stop.split("@")
        spot = tuple(int(v) for v in xy.split(","))
    stop = int(stop)
    goals = []
    for leg in legs:
        m, xy = leg.split(":")
        gx, gy = xy.split(",")
        goals.append((int(m), None if gx == "-" else int(gx), None if gy == "-" else int(gy)))
    leg = 0
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
        if mp == stop and (spot is None or (x, y) == spot):
            break
        if leg + 1 < len(goals) and goals[leg][0] != mp and goals[leg + 1][0] == mp:
            leg += 1        # legs are taken in order, so a map met twice can have two different spots
        d = route(mp, x, y, goals[leg][1:] if goals[leg][0] == mp else (None, None), blocked, rng)
        if d is None:
            blocked = {b for b in blocked if b[0] != mp}
            continue
        press(pb, d, hold=8, after=12)
        if (m[MAP], m[X], m[Y]) == (mp, x, y) and not m[BATTLE]:
            press(pb, "b")
            if (m[MAP], m[X], m[Y]) == (mp, x, y):
                blocked.add((mp, x, y, d))
    print("map", m[MAP], "x", m[X], "y", m[Y], "presses", i)
    if m[MAP] == stop and (spot is None or (m[X], m[Y]) == spot):
        for _ in range(60):
            pb.tick()
        with open(out, "wb") as f:
            pb.save_state(f)
        print("saved", out)
    pb.stop(save=False)


if __name__ == "__main__":
    main()
