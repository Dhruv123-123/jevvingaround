"""Fight demos for a learned battle book (anygame/walk_book.py's FightBook): pace back and forth from a save until wild
fights start, and play each fight with a RAM rule (grader side, a test helper like pokemon_fixture_walk.py): FIGHT,
then the attack that hurts this foe most, A through every message, and yes to any other menu (a new attack takes the first
slot). Each press is saved with the screen it was made on.

    python scripts/pokemon_fight_demos.py STATE OUT.npz FIGHTS [UP,DOWN pacing presses, default 4,3]

FIXTURE_HEAL=1 keeps the first party member above a third of its health between fights, so a demo is not cut short.
"""
from __future__ import annotations
import os
import sys

import numpy as np
from pyboy import PyBoy

sys.path.insert(0, os.path.dirname(__file__))
from pokemon_fixture_walk import press  # noqa: E402

ROM = "/mnt/project-files/roms/pokemon-red.gb"
STEPS = ("up", "down", "left", "right", "a", "b")
ARROW = 0xED                         # the menu cursor tile in the tile map at 0xC3A0 (20 x 18)
# attacks the rule knows: id -> (power, type); types as the game numbers them
MOVES = {33: (35, 0), 15: (50, 0), 22: (35, 22), 75: (55, 22), 10: (40, 0), 1: (40, 0), 52: (40, 20), 55: (40, 21), 84: (40, 23)}
STAB = {22}                          # the starter here is a grass type
WEAK = {22: {2, 3, 7, 20, 22, 26}, 0: {5}}            # attack type -> foe types that halve it
STRONG = {22: {4, 5, 21}}                              # attack type -> foe types that double it
GHOST = 8


def arrows(m) -> list[tuple[int, int]]:
    return [(i % 20, i // 20) for i in range(360) if m[0xC3A0 + i] == ARROW]


def best_move(m) -> int:
    foe = {m[0xCFEA], m[0xCFEB]}
    score = []
    for j in range(4):
        mid, pp = m[0xD01C + j], m[0xD02D + j] & 0x3F
        power, typ = MOVES.get(mid, (0, 0))
        if not mid or not pp or not power or (typ == 0 and GHOST in foe):
            score.append(-1.0)
            continue
        s = power * (1.5 if typ in STAB else 1.0)
        for f in foe:
            s *= 0.5 if f in WEAK.get(typ, ()) else 2.0 if f in STRONG.get(typ, ()) else 1.0
        score.append(s)
    return int(np.argmax(score))


def rule(m) -> str:
    cur = arrows(m)
    if not cur:
        return "a"                                     # a message: read on
    x, y = cur[0]
    if (x, y) in ((9, 14), (15, 14), (9, 16), (15, 16)):   # FIGHT PKMN / ITEM RUN
        return "a" if (x, y) == (9, 14) else "left" if x == 15 else "up"
    if x == 5 and 13 <= y <= 16:                       # the attack list, first attack on row 13
        want = best_move(m)
        return "a" if y - 13 == want else "down" if y - 13 < want else "up"
    return "a"                                         # any other menu (learn a new attack?): yes, in its first slot


def fight_screen(shot: np.ndarray) -> bool:
    """The fight's bottom box is drawn: its top border is the dark line across row 98."""
    return shot[98, 8:152, :3].mean() < 40


def main() -> None:
    state, out, fights = sys.argv[1], sys.argv[2], int(sys.argv[3])
    up, down = (int(v) for v in (sys.argv[4] if len(sys.argv) > 4 else "4,3").split(","))
    heal = os.environ.get("FIXTURE_HEAL") == "1"
    pb = PyBoy(ROM, window="null", sound_emulated=False)
    with open(state, "rb") as f:
        pb.load_state(f)
    pb.tick(60)
    m = pb.memory
    shots, steps, done, k = [], [], 0, 0
    while done < fights and k < 20000:
        if m[0xD057]:
            b = rule(m)
            shot = pb.screen.ndarray[:, :, :3].copy()
            if fight_screen(shot):         # not the map frames before the fight is drawn
                shots.append(shot)
                steps.append(STEPS.index(b))
            press(pb, b, after=40)
            if not m[0xD057]:
                done += 1
                print("fight", done, "presses", len(steps), "level", m[0xD18C], "hp", m[0xD16C] * 256 + m[0xD16D],
                      flush=True)
            continue
        if heal:
            hp, top = m[0xD16C] * 256 + m[0xD16D], m[0xD18D] * 256 + m[0xD18E]
            if hp * 3 < top:
                m[0xD16C], m[0xD16D] = m[0xD18D], m[0xD18E]
        if m[0xD16C] * 256 + m[0xD16D] == 0:
            break
        press(pb, "up" if k % (up + down) < up else "down", after=12)
        k += 1
    np.savez_compressed(out, shots=np.array(shots), steps=np.array(steps, dtype=np.uint8))
    print("recorded", len(steps), "fight presses in", done, "fights to", out)


if __name__ == "__main__":
    main()
