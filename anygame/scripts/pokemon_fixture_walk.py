"""Make Pokemon Red test saves by walking with RAM (a test fixture, not the agent: the agent never reads RAM).

From a save, walk to the next map in a route by greedy moves on the RAM position, learning blocked steps as it goes, and
run from wild battles. Saves the state on arrival.

    python scripts/pokemon_fixture_walk.py IN.state OUT.state 0:10,0 12:-,0 1
    (each leg is MAP:X,Y, the spot to head for on that map, '-' for any, taken in order; the last argument is the map
    to stop on, or MAP@X,Y to stop on a spot; a leg ending in '!' faces up and talks on arrival, as with Oak)
"""
from __future__ import annotations
import os
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


def flee(pb, heal: bool = False):
    """Get through a battle: try RUN (bottom right of the battle menu) from wild ones; trainers refuse, so then fight
    with the first move by mashing A."""
    for k in range(600):
        if not pb.memory[BATTLE]:
            return
        if heal:                        # demos only: never lose a fight
            pb.memory[0xD16C], pb.memory[0xD16D] = pb.memory[0xD18D], pb.memory[0xD18E]
        if pb.memory[BATTLE] == 1 and k % 4 == 0:
            press(pb, "down"); press(pb, "right"); press(pb, "a", after=60)
        press(pb, "a", after=40)


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
            if (mp, cx, cy, d) in blocked or (nx, ny) in seen or not (-1 <= nx <= 120 and -1 <= ny <= 120):
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
        talk = xy.endswith("!")
        gx, gy = xy.rstrip("!").split(",")
        goals.append((int(m), None if gx == "-" else int(gx), None if gy == "-" else int(gy), talk))
    leg = 0
    rom = tempfile.mkdtemp(prefix="pkfx-") + "/p.gb"
    shutil.copyfile(ROM, rom)
    pb = PyBoy(rom, window="null", sound_emulated=False)
    with open(src, "rb") as f:
        pb.load_state(f)
    pb.tick(2)
    rng = random.Random(int(os.environ.get("FIXTURE_SEED", "0")))
    record = os.environ.get("FIXTURE_RECORD")         # walk demos for a learned walker: (screen, step that moved)
    rec_maps = {int(v) for v in os.environ.get("FIXTURE_RECORD_MAPS", "").split(",") if v}
    shots, steps, where = [], [], []
    heal = os.environ.get("FIXTURE_HEAL") == "1"     # demos only: never lose a fight
    for _ in range(int(os.environ.get("FIXTURE_WANDER", "0"))):    # start somewhere off the best path
        press(pb, rng.choice(list(DIRS)), hold=8, after=12)
        if pb.memory[BATTLE]:
            flee(pb, heal)
    blocked: set = set()
    doors: set = set()
    m = pb.memory
    for i in range(20000):
        if m[BATTLE]:
            flee(pb, heal)
            continue
        mp, x, y = m[MAP], m[X], m[Y]
        if i % 400 == 399:
            blocked.clear()             # a step seen blocked behind a person or a text box may be open now
        if mp == stop and (spot is None or (x, y) == spot):
            break
        if leg + 1 < len(goals) and goals[leg][0] != mp and goals[leg + 1][0] == mp:
            leg += 1        # legs are taken in order, so a map met twice can have two different spots
        g = goals[leg]
        if not g[3] and (mp, x, y) == g[:3] and leg + 1 < len(goals) and goals[leg + 1][0] == mp:
            leg += 1                    # a waypoint on this map: on to the next one
            g = goals[leg]
        if g[3] and (mp, x, y) == g[:3]:
            press(pb, "up")             # face up and talk (Oak across his desk), then read through the scene
            for _ in range(80):
                press(pb, "a", after=30)
            leg = min(leg + 1, len(goals) - 1)
            continue
        if g[0] != mp:      # wandered onto another map of the route: head for its spot again
            g = next((h for h in reversed(goals) if h[0] == mp and not h[3]), (mp, None, None, False))
        d = route(mp, x, y, g[1:3], blocked | doors, rng)
        if d is None:
            blocked = {b for b in blocked if b[0] != mp}
            continue
        shot = pb.screen.ndarray[:, :, :3].copy() if record and mp in rec_maps else None
        press(pb, d, hold=8, after=12)
        if m[MAP] != mp:
            pb.tick(40)                 # after a warp the map id changes a few frames before x, y do
        if shot is not None and not m[BATTLE] and (m[MAP] != mp or (m[X], m[Y]) != (x, y)):   # moved, or went through a door
            shots.append(shot)
            steps.append("udlr".index(d[0]))
            where.append((mp, x, y))
        if m[MAP] != mp and m[MAP] != goals[leg][0] and not (leg + 1 < len(goals) and m[MAP] == goals[leg + 1][0]):
            doors.add((mp, x, y, d))    # a door off the route: never take it again
        if (m[MAP], m[X], m[Y]) == (mp, x, y) and not m[BATTLE]:
            press(pb, "b")
            if (m[MAP], m[X], m[Y]) == (mp, x, y):
                blocked.add((mp, x, y, d))
    end = os.environ.get("FIXTURE_RECORD_END")      # a last demo screen at the stop spot with this step (face the nurse)
    if record and end and m[MAP] in rec_maps and m[MAP] == stop and (spot is None or (m[X], m[Y]) == spot):
        shots.append(pb.screen.ndarray[:, :, :3].copy())
        steps.append("udlr".index(end[0]))
        where.append((m[MAP], m[X], m[Y]))
    print("map", m[MAP], "x", m[X], "y", m[Y], "presses", i, "leg", leg, "bag", [m[0xD31E + 2 * k] for k in range(min(m[0xD31D], 20))])
    pb.screen.image.save(out + ".png")
    if record and shots:
        import numpy as np
        np.savez_compressed(record, shots=np.array(shots), steps=np.array(steps, dtype=np.uint8),
                            where=np.array(where, dtype=np.int16), end=np.array((m[MAP], m[X], m[Y]), dtype=np.int16))
        print("recorded", len(shots), "steps to", record)
    if m[MAP] == stop and (spot is None or (m[X], m[Y]) == spot):
        for _ in range(60):
            pb.tick()
        with open(out, "wb") as f:
            pb.save_state(f)
        print("saved", out)
    pb.stop(save=False)


if __name__ == "__main__":
    main()
