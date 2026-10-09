"""Press-and-watch over captured frames (phase 1 of the screen-only roadmap), scored against grader-side truth.

The watcher sees the frames and the presses, nothing else. Truth it never reads: which OAM sprite slots are the player
(found per game as the slots whose world position follows the d-pad, scroll registers included), and for Pokemon Red
and Aevilia the position bytes (did a direction press move the player). $0: no model.

    python scripts/screenonly_watch.py --cap CAP --out OUT [--games pokemon,aevilia]
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from anygame.perceive.watch import Watcher, DIRS  # noqa: E402

PER_MIN = 150


def wrap(d: int) -> int:
    return ((d + 128) % 256) - 128


def player_slots(rows: list[dict]) -> set[int]:
    """Grader side: the OAM slots whose world position (screen position plus scroll) moved the way a direction press
    pointed most often. Empty when no slot follows the d-pad (a game drawn without sprites)."""
    sc = defaultdict(lambda: [0, 0])
    for i in range(1, len(rows)):
        d = DIRS.get(rows[i]["press"] or "")
        if not d:
            continue
        a, b = rows[i - 1]["truth"], rows[i]["truth"]
        sa = {s[0]: xy for s, xy in zip(a.get("slots", []), a["sprites"])}
        sb = {s[0]: xy for s, xy in zip(b.get("slots", []), b["sprites"])}
        dsx, dsy = wrap(b["scx"] - a["scx"]), wrap(b["scy"] - a["scy"])
        for k in sa.keys() & sb.keys():
            wx, wy = sb[k][0] - sa[k][0] + dsx, sb[k][1] - sa[k][1] + dsy
            sc[k][0] += wx * d[0] + wy * d[1] > 0
            sc[k][1] += 1
    ratio = {k: v[0] / v[1] for k, v in sc.items() if v[1] >= 30}
    if not ratio or max(ratio.values()) < 0.3:
        return set()
    top = max(ratio.values())
    return {k for k, r in ratio.items() if r >= 0.85 * top}


def truth_box(t: dict, slots: set[int]) -> tuple[int, int, int, int] | None:
    boxes = [xy for s, xy in zip(t.get("slots", []), t["sprites"]) if s[0] in slots]
    if not boxes:
        return None
    x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes); y1 = max(b[1] + b[3] for b in boxes)
    if x1 <= 0 or y1 <= 0 or x0 >= 160 or y0 >= 144:
        return None
    return x0, y0, x1 - x0, y1 - y0


def inside(box, truth, slack: int = 4) -> bool:
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    tx, ty, tw, th = truth
    return tx - slack <= cx <= tx + tw + slack and ty - slack <= cy <= ty + th + slack


def truth_moved(game: str, a: dict, b: dict, press: str) -> bool | None:
    """Grader side: did this direction press move the player (True), leave it in place facing that way (False), or
    neither / unknown (None)."""
    if "x" not in a or a.get("map") != b.get("map"):
        return None
    dx, dy = DIRS[press]
    mx, my = wrap(b["x"] - a["x"]) if game.startswith("pokemon") else b["x"] - a["x"], \
        wrap(b["y"] - a["y"]) if game.startswith("pokemon") else b["y"] - a["y"]
    if mx * dx + my * dy > 0:
        return True
    if (mx, my) == (0, 0):
        if game.startswith("pokemon"):
            facing = {"down": 0, "up": 4, "left": 8, "right": 12}[press]
            if a["facing"] == facing and a["tilemap"][240] != 0x79 and b["tilemap"][240] != 0x79:
                return False
            return None
        return False
    return None


def run(game: str, cap: str) -> dict:
    frames = np.load(os.path.join(cap, f"{game}.npz"))["frames"]
    rows = [json.loads(l) for l in open(os.path.join(cap, f"{game}.jsonl"))]
    slots = player_slots(rows)
    w = Watcher()
    per_min: dict[int, Counter] = defaultdict(Counter)
    walk = Counter()
    t0 = time.perf_counter()
    for i in range(1, len(frames)):
        press = rows[i]["press"]
        eff = w.see(frames[i - 1], press, frames[i])
        m = per_min[min(i // PER_MIN, (len(frames) - 2) // PER_MIN)]
        tb = truth_box(rows[i]["truth"], slots) if slots else None
        m["frames"] += 1
        m["truth"] += tb is not None
        m["pred"] += eff.player is not None
        if eff.player is not None:
            ok = tb is not None and inside(eff.player, tb)
            m["pred_ok"] += ok
            m["found"] += ok
        m["scene"] += eff.scene
        if press in DIRS and eff.moved is not None:
            tm = truth_moved(game, rows[i - 1]["truth"], rows[i]["truth"], press)
            k = ("moved" if eff.moved else "blocked") + "_" + {True: "truth_moved", False: "truth_blocked", None: "truth_unknown"}[tm]
            walk[k] += 1
        elif press in DIRS:
            tm = truth_moved(game, rows[i - 1]["truth"], rows[i]["truth"], press)
            if tm is not None:
                walk["unjudged_truth_" + ("moved" if tm else "blocked")] += 1
    ms = 1000 * (time.perf_counter() - t0) / (len(frames) - 1)
    tot = Counter()
    warm = Counter()
    for k, c in per_min.items():
        tot.update(c)
        if k >= 5:
            warm.update(c)

    def rates(c):
        return {"recall": round(c["found"] / c["truth"], 3) if c["truth"] else None,
                "precision": round(c["pred_ok"] / c["pred"], 3) if c["pred"] else None,
                "truth_frames": c["truth"], "pred_frames": c["pred"]}
    p = w.player
    return {"game": game, "player_slots": sorted(slots), "all": rates(tot), "warm": rates(warm),
            "player_track": None if p is None else {"agree": p.agree, "against": p.against, "poses": len(p.poses)},
            "tracks": len(w.tracks), "steps": dict(w.steps.most_common(5)), "walk": dict(walk),
            "scene_frames": tot["scene"], "ms_per_frame": round(ms, 2)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", default="/mnt/project-files/anygame/screen-only-phase1/cap")
    ap.add_argument("--out", required=True)
    ap.add_argument("--games", default="tobutobugirl,postbot,renegade-rush,gbhack,aevilia,pokemon,pokemon-cold")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    res = []
    for g in a.games.split(","):
        r = run(g, a.cap)
        res.append(r)
        print(json.dumps(r), flush=True)
        with open(os.path.join(a.out, "watch.json"), "w") as f:
            json.dump(res, f, indent=1)


if __name__ == "__main__":
    sys.exit(main())
