"""Whether anygame/battle.py stays silent where nothing is a fight: each save state's menu entries are played out
(the cursor's entry and the next two down, as the menu reader would) and compared. A ranking where nothing was hurt
would push the decider toward one entry for no reason.

    python scripts/battle_silence.py ROM STATE [ROM STATE ...]"""
from __future__ import annotations
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from anygame.device.pyboy import PyBoyDevice
from anygame.playout import play_out
from anygame.battle import Fight

ENTRIES = (["a"], ["down", "a"], ["down", "down", "a"], ["right", "a"], ["up"], ["down"], ["left"], ["right"])


def main():
    args = sys.argv[1:]
    for rom, state in zip(args[::2], args[1::2]):
        d = PyBoyDevice(f"pyboy://{rom}?state={state}")
        f = Fight()
        out = []
        for step in range(6):                       # a few moments: the state, then after each wait
            effects = {" ".join(k): f.effect(" ".join(k), play_out(d, k, lambda img: "", max_frames=900, restless=300))
                       for k in ENTRIES}
            order = f.rank(effects)
            out.append({"order": order, "scores": {k: (e or {}).get("score") for k, e in effects.items()},
                        "ended": {k: (e or {}).get("ended") for k, e in effects.items()}})
            d.wait(60)
        print(json.dumps({"state": Path(state).name, "ranked": sum(bool(o["order"]) for o in out), "of": len(out),
                          "moments": out}))


if __name__ == "__main__":
    main()
