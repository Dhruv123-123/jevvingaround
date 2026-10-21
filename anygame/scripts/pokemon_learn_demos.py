"""Learn-move demos for a menu book (anygame/walk_book.py's FightBook, as a screen agent's menu_book): when the first
party member levels up into a fifth move, "Which move should be forgotten?" lists its four; the demos press DOWN to
the second move and A, so the first move (the attack the fight book plays) is kept. Pressing A at the list (the fight
book's habit) forgot the first move: Ivysaur lost TACKLE to POISONPOWDER at level 22 and lost every fight after.
A RAM rule drives each demo (grader side, a test helper like pokemon_menu_demos.py): set the level and experience
one win short of a new move, walk into a wild fight, A through it, and on the move list go down to the second move.
Only the move list screens are saved, each with the press made before it ("prev"): after A the cursor is on the
first move (press DOWN), after DOWN it is on the second (press A).

    python scripts/pokemon_learn_demos.py OUT.npz RUNS STATE [STATE ...]   (states on the map, not in a fight)
"""
from __future__ import annotations
import os
import random
import sys

import numpy as np
from pyboy import PyBoy

sys.path.insert(0, os.path.dirname(__file__))
from pokemon_fixture_walk import press  # noqa: E402

ROM = "/mnt/project-files/roms/pokemon-red.gb"
STEPS = ("up", "down", "left", "right", "a", "b", "start", "select")
BATTLE = 0xD057
MOVES, PP, LEVEL, EXP = 0xD173, 0xD188, 0xD18C, 0xD179
MENU_Y, MENU_X, CURSOR, MAX_ITEM = 0xCC24, 0xCC25, 0xCC26, 0xCC28
TACKLE, GROWL, LEECH_SEED, VINE_WHIP, POISONPOWDER, RAZOR_LEAF = 33, 45, 73, 22, 77, 75
# (level before the win, moves then, the one learned at the next level, experience just short of that level;
# Ivysaur is medium-slow: 6/5 n^3 - 15 n^2 + 100 n - 140)
CASES = [(21, [TACKLE, GROWL, LEECH_SEED, VINE_WHIP], POISONPOWDER, 7577),
         (29, [TACKLE, POISONPOWDER, LEECH_SEED, VINE_WHIP], RAZOR_LEAF, 21760)]
PPS = {TACKLE: 35, GROWL: 40, LEECH_SEED: 10, VINE_WHIP: 10, POISONPOWDER: 35, RAZOR_LEAF: 25}


def move_list(m) -> bool:
    """The forget-a-move list: a four-row menu at the top of the screen (the fight's own move menu sits lower)."""
    return m[MAX_ITEM] == 3 and m[MENU_X] == 5 and m[MENU_Y] == 8


def main() -> None:
    out, runs, states = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
    rng = random.Random(1)
    shots, steps, prevs, ok = [], [], [], 0
    pb = PyBoy(ROM, window="null", sound_emulated=False)
    m = pb.memory
    for r in range(runs):
        with open(states[r % len(states)], "rb") as f:
            pb.load_state(f)
        pb.tick(60 + rng.randrange(60))
        level, moves, new, need = CASES[r % len(CASES)]
        for k, v in enumerate(moves):
            m[MOVES + k], m[PP + k] = v, PPS[v]
        m[LEVEL] = level
        e = need - 1 - rng.randrange(5)
        m[EXP], m[EXP + 1], m[EXP + 2] = e >> 16, (e >> 8) & 255, e & 255
        n = 0
        while not m[BATTLE] and n < 3000:
            press(pb, rng.choice(("up", "down", "left", "right")), after=10)
            n += 1
        prev, seen = "a", set()
        for _ in range(600):
            if not m[BATTLE] and m[MOVES + 1] != moves[1]:
                break
            b = "a"
            if move_list(m) and m[MOVES + 1] == moves[1]:
                b = "down" if m[CURSOR] == 0 else "a" if m[CURSOR] == 1 else "up"
                if m[CURSOR] not in seen:      # (once per cursor row: the menu's RAM outlives the list)
                    seen.add(m[CURSOR])
                    shots.append(pb.screen.ndarray[:, :, :3].copy())
                    steps.append(STEPS.index(b))
                    prevs.append(STEPS.index(prev))
            press(pb, b, after=30 + rng.randrange(20))
            prev = b
        got = [m[MOVES + k] for k in range(4)]
        good = got == [moves[0], new, moves[2], moves[3]]
        ok += good
        print(r, "level", m[LEVEL], "moves", got, "ok" if good else "MISSED", flush=True)
    pb.stop(save=False)
    np.savez_compressed(out, shots=np.array(shots, dtype=np.uint8), steps=np.array(steps, dtype=np.int64),
                        prev=np.array(prevs, dtype=np.int64))
    print(f"{ok}/{runs} runs kept the first move; {len(steps)} list screens -> {out}")


if __name__ == "__main__":
    main()
