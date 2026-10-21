"""Learn-move demos for a menu book (anygame/walk_book.py's FightBook, as a screen agent's menu_book): when the first
party member levels up into a fifth move, "Which move should be forgotten?" lists its four; the demos go down to the
move that does no damage (GROWL, then POISONPOWDER) and press A, so the attacks are kept. Pressing A at the list (the
fight book's habit) forgot the first move: Ivysaur lost TACKLE to POISONPOWDER at level 22 and lost every fight after.
A run may have moved its attacks around (SELECT in the attack list), so the demos go through every order.
A RAM rule drives each demo (grader side, a test helper like pokemon_menu_demos.py): set the level and experience
one win short of a new move, walk into a wild fight, win it with the best attack, and on the move list go down to the move to drop.
Only the move list screens are saved: the list with the cursor on each of its four rows (the agent may have moved it),
going by the screen alone, as the press before it may be anyone's (the agent's own presses, the explorer's).

    python scripts/pokemon_learn_demos.py OUT.npz RUNS STATE [STATE ...]   (states on the map, not in a fight)
"""
from __future__ import annotations
import io
import itertools
import os
import random
import sys

import numpy as np
from pyboy import PyBoy

sys.path.insert(0, os.path.dirname(__file__))
from pokemon_fight_demos import rule  # noqa: E402
from pokemon_fixture_walk import press  # noqa: E402

ROM = "/mnt/project-files/roms/pokemon-red.gb"
STEPS = ("up", "down", "left", "right", "a", "b", "start", "select")
BATTLE = 0xD057
MOVES, PP, LEVEL, EXP = 0xD173, 0xD188, 0xD18C, 0xD179
MENU_Y, MENU_X, CURSOR, MAX_ITEM = 0xCC24, 0xCC25, 0xCC26, 0xCC28
TACKLE, GROWL, LEECH_SEED, VINE_WHIP, POISONPOWDER, RAZOR_LEAF = 33, 45, 73, 22, 77, 75
# (level before the win, moves then in every order, the one to drop, the one learned at the next level, experience
# just short of that level; Ivysaur is medium-slow: 6/5 n^3 - 15 n^2 + 100 n - 140)
CASES = [(21, list(o), GROWL, POISONPOWDER, 7577) for o in itertools.permutations([TACKLE, GROWL, LEECH_SEED, VINE_WHIP])]
CASES += [(29, list(o), POISONPOWDER, RAZOR_LEAF, 21760)
          for o in itertools.permutations([TACKLE, POISONPOWDER, LEECH_SEED, VINE_WHIP])]
PPS = {TACKLE: 35, GROWL: 40, LEECH_SEED: 10, VINE_WHIP: 10, POISONPOWDER: 35, RAZOR_LEAF: 25}


def move_list(m) -> bool:
    """The forget-a-move list: a four-row menu at the top of the screen (the fight's own move menu sits lower)."""
    return m[MAX_ITEM] == 3 and m[MENU_X] == 5 and m[MENU_Y] == 8


def main() -> None:
    out, runs, states = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
    rng = random.Random(1)
    shots, steps, ok = [], [], 0
    pb = PyBoy(ROM, window="null", sound_emulated=False)
    m = pb.memory
    for r in range(runs):
        with open(states[r % len(states)], "rb") as f:
            pb.load_state(f)
        pb.tick(60 + rng.randrange(60))
        level, moves, drop, new, need = CASES[r % len(CASES)]
        row = moves.index(drop)
        for k, v in enumerate(moves):
            m[MOVES + k], m[PP + k] = v, PPS[v]
        m[LEVEL] = level
        e = need - 1 - rng.randrange(5)
        m[EXP], m[EXP + 1], m[EXP + 2] = e >> 16, (e >> 8) & 255, e & 255
        n = 0
        while not m[BATTLE] and n < 3000:
            press(pb, rng.choice(("up", "down", "left", "right")), after=10)
            n += 1
        listed = False
        for _ in range(600):
            if not m[BATTLE] and m[MOVES + row] != drop:
                break
            b = rule(m)                        # the fight: its best attack, A through messages
            if move_list(m) and m[MOVES + row] == drop:
                if not listed:                 # the list with the cursor on each row, and the press to make there
                    listed = True
                    here = io.BytesIO()
                    pb.save_state(here)
                    for k in range(4):
                        here.seek(0)
                        pb.load_state(here)
                        for _ in range(k):
                            press(pb, "down", after=12)
                        shots.append(pb.screen.ndarray[:, :, :3].copy())
                        steps.append(STEPS.index("down" if k < row else "a" if k == row else "up"))
                    here.seek(0)
                    pb.load_state(here)
                b = "down" if m[CURSOR] < row else "a" if m[CURSOR] == row else "up"
            press(pb, b, after=30 + rng.randrange(20))
        got = [m[MOVES + k] for k in range(4)]
        good = got == [new if k == row else v for k, v in enumerate(moves)]
        ok += good
        print(r, "level", m[LEVEL], "moves", got, "ok" if good else "MISSED", flush=True)
    pb.stop(save=False)
    np.savez_compressed(out, shots=np.array(shots, dtype=np.uint8), steps=np.array(steps, dtype=np.int64))
    print(f"{ok}/{runs} runs dropped the move that does no damage; {len(steps)} list screens -> {out}")


if __name__ == "__main__":
    main()
