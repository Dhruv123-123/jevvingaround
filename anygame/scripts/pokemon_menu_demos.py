"""Menu demos for a learned menu book (anygame/walk_book.py's FightBook, as a screen agent's menu_book): teach a move
from a machine in the bag (HM01, Cut) to the first party member, with a RAM rule (grader side, a test helper like
pokemon_fight_demos.py): B through any text, START, ITEM, the machine, USE, A through every message, and the first
attack is forgotten. Each press is saved with the screen it was made on. Every run starts from another square of the
map and with the start menu and bag cursors left somewhere else, so the book sees the screens the agent may meet.

    python scripts/pokemon_menu_demos.py STATE OUT.npz RUNS [ITEM MOVE, default 196 15]
"""
from __future__ import annotations
import io
import os
import random
import sys

import numpy as np
from pyboy import PyBoy

sys.path.insert(0, os.path.dirname(__file__))
from pokemon_fixture_walk import press  # noqa: E402

ROM = "/mnt/project-files/roms/pokemon-red.gb"
STEPS = ("up", "down", "left", "right", "a", "b", "start", "select")
MAP, X, Y = 0xD35E, 0xD362, 0xD361
CURSOR, SCROLL = 0xCC26, 0xCC36       # the open menu's cursor row, and how far a list is scrolled
ITEM_ROW = 2                          # POKEDEX, POKEMON, ITEM, ...


def moves(m) -> list[int]:
    return [m[0xD173 + k] for k in range(4)]


def bag(m) -> list[int]:
    return [m[0xD31E + 2 * k] for k in range(m[0xD31D])]


def main() -> None:
    state, out, runs = sys.argv[1], sys.argv[2], int(sys.argv[3])
    item, move = (int(v) for v in sys.argv[4:6]) if len(sys.argv) > 5 else (196, 15)
    pb = PyBoy(ROM, window="null", sound_emulated=False)
    with open(state, "rb") as f:
        pb.load_state(f)
    pb.tick(60)
    m = pb.memory
    rng = random.Random(1)

    def snap():
        b = io.BytesIO()
        pb.save_state(b)
        return b.getvalue()

    def load(s):
        pb.load_state(io.BytesIO(s))

    def screen():
        return pb.screen.ndarray[:, :, :3].copy()

    shots, steps = [], []

    def rec(b, after=40):
        shots.append(screen())
        steps.append(STEPS.index(b))
        press(pb, b, after=after)

    # B through the text the save starts in (recorded: the screen changes), then the squares the player can stand on
    for _ in range(12):
        before = screen()
        press(pb, "b", after=40)
        if not (screen() != before).any():
            break
        shots.append(before)
        steps.append(STEPS.index("b"))
    start, here = snap(), (m[MAP], m[X], m[Y])
    spots, todo = {here[1:]: start}, [start]
    while todo and len(spots) < 40:
        s = todo.pop()
        for d in ("up", "down", "left", "right"):
            load(s)
            press(pb, d, after=20)
            if m[MAP] == here[0] and (m[X], m[Y]) not in spots:
                spots[(m[X], m[Y])] = snap()
                todo.append(spots[(m[X], m[Y])])
    spots = list(spots.values())
    print("squares", len(spots), flush=True)
    done = 0
    for r in range(runs):
        load(spots[r % len(spots)])
        # leave the cursors somewhere else (not recorded)
        press(pb, "start", after=40)
        for _ in range(rng.randrange(6)):
            press(pb, "down", after=12)
        press(pb, "b", after=40)
        if rng.random() < 0.5:
            press(pb, "start", after=40)
            while m[CURSOR] != ITEM_ROW:
                press(pb, "down", after=12)
            press(pb, "a", after=40)
            for _ in range(rng.randrange(len(bag(m)))):
                press(pb, "down", after=12)
            press(pb, "b", after=40)
            press(pb, "b", after=40)
        pb.tick(30)
        rec("start")
        k = 0
        while m[CURSOR] != ITEM_ROW and k < 10:
            rec("down" if m[CURSOR] < ITEM_ROW else "up", after=12)
            k += 1
        rec("a")
        want = bag(m).index(item)
        while m[SCROLL] + m[CURSOR] != want and k < 40:
            rec("down" if m[SCROLL] + m[CURSOR] < want else "up", after=12)
            k += 1
        rec("a")                                       # the machine
        while move not in moves(m) and k < 120:        # USE, the party member, yes, the first attack, every message
            rec("a")
            k += 1
        for _ in range(6):                             # and the last messages, back to the map
            before = screen()
            press(pb, "b", after=40)
            if not (screen() != before).any():
                break
            shots.append(before)
            steps.append(STEPS.index("b"))
        done += move in moves(m)
        print("run", r, "learned", move in moves(m), "presses", len(steps), flush=True)
    np.savez_compressed(out, shots=np.array(shots), steps=np.array(steps, dtype=np.uint8))
    print("recorded", len(steps), "menu presses in", done, "of", runs, "runs to", out)


if __name__ == "__main__":
    main()
