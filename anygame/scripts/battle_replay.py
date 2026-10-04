"""Fights played to the end from a save state, choosing each move by anygame/battle.py or by a simple policy, to see
whether choosing by the other side's bar wins more. The game's RAM is read here only to drive the menus the same way
for every policy and to grade the result (map grades only); the chooser sees the screens alone.

    python scripts/battle_replay.py STATE.state [--policy fight|cursor|random] [--seeds 20]

Pokemon Red only, for the addresses below. Each seed waits a different number of frames first, so the game's random
numbers (hits, misses, the other side's moves) differ between fights."""
from __future__ import annotations
import argparse, json, random, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from anygame.device.pyboy import PyBoyDevice
from anygame.playout import play_out, asks
from anygame.battle import Fight
from anygame.perceive import tiletext

# the text is read from the screen's cells with a finished glyph book and no labeller (no model calls): the own
# numbers ("16/ 19") that tell the player's bar from the other side's
TEXT = {"kind": "tiletext", "book": "/tmp/claude-0/sp/pk-glyphs.json", "labeller": "none"}

ROM = "/mnt/project-files/roms/pokemon-red.gb"
IN_BATTLE, MENU_ITEM, MY_HP, ENEMY_HP, MOVES = 0xD057, 0xCC26, 0xD015, 0xCFE6, 0xD01C   # grading and driving only


def word(d, a):
    hi, lo = d.peek(a, 2)
    return hi * 256 + lo


def fight_once(state: str, policy: str, seed: int, max_turns: int = 40, ocr: bool = True, book: str | None = None) -> dict:
    d = PyBoyDevice(f"pyboy://{ROM}?state={state}")
    rng = random.Random(seed)
    d.wait(seed * 3)
    if d.peek(IN_BATTLE)[0] == 0:
        # not in a fight yet: walk up and down in the grass until one starts, then page to the first menu
        for i in range(400):
            d.press(("up", "down")[i % 2], hold=16, after=8)
            if d.peek(IN_BATTLE)[0]:
                break
        for _ in range(30):
            if asks(d):
                break
            d.press("a", hold=4, after=40)
    fight = Fight()
    none = (lambda img: tiletext.read(img, TEXT)) if ocr else (lambda img: "")
    turns, chose, ranked = 0, [], 0
    while turns < max_turns and d.peek(IN_BATTLE)[0] not in (0, 0xFF):
        # at FIGHT / ITEM / RUN: open the move list
        d.press("a", hold=4, after=40)
        moves = [m for m in d.peek(MOVES, 4) if m]
        cur = max(0, min(len(moves) - 1, d.peek(MENU_ITEM)[0] - 1))   # the move list counts from 1
        entries = [["up"] * (cur - i) if i < cur else ["down"] * (i - cur) for i in range(len(moves))]
        if policy == "cursor":
            pick = cur
        elif policy == "random":
            pick = rng.randrange(len(moves))
        else:
            effects = {i: fight.effect(str(i), play_out(d, keys + ["a"], none, max_frames=2400))
                       for i, keys in enumerate(entries)}
            order = fight.rank(effects)
            pick = order[0] if order else cur
            ranked += bool(order)
        chose.append(moves[pick])
        play_out(d, entries[pick] + ["a"], none, max_frames=3000, restore=False)
        turns += 1
        if not asks(d):
            for _ in range(60):          # the fight ended: page through what follows
                if d.peek(IN_BATTLE)[0] in (0, 0xFF):
                    break
                d.press("a", hold=4, after=30)
    won = word(d, ENEMY_HP) == 0 and word(d, MY_HP) > 0
    return {"seed": seed, "won": won, "enemy": d.peek(0xCFE5)[0], "turns": turns, "my_hp": word(d, MY_HP), "enemy_hp": word(d, ENEMY_HP),
            "moves": chose, "ranked_turns": ranked}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("state")
    ap.add_argument("--policy", default="fight")
    ap.add_argument("--seeds", type=int, default=20)
    a = ap.parse_args()
    rows = [fight_once(a.state, a.policy, s) for s in range(a.seeds)]
    for r in rows:
        print(json.dumps(r))
    wins = sum(r["won"] for r in rows)
    print(json.dumps({"policy": a.policy, "state": Path(a.state).name, "wins": wins, "of": len(rows),
                      "turns": sum(r["turns"] for r in rows) / len(rows)}))


if __name__ == "__main__":
    main()
