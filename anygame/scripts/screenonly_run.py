"""The screen-only perception pass over captured frames: novelty cache in front of the Azure labeller, then scored
against grader-side truth the pass never reads.

Frames come from scripts/screenonly_capture.py (random presses, so play never depends on the labels and replaying the
frames in order is the same as labelling live). Every frame: cut into 8x8 cells from pixels, look each cell up in the
per-game book, queue the screen for the model if any cell is new, send four screens per call. Once the game's budget
is spent, new cells are still entered (unlabelled) so the hit-rate curve stays the one a labelled run would have, and
the screens that would have needed a call are counted.

    python scripts/screenonly_run.py --cap runs/screenonly/cap --out runs/screenonly/pass [--budget 0.4] [--offline]
    python scripts/screenonly_run.py --cap runs/screenonly/cap --out runs/screenonly/phase0 --offline --cache objects
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
from anygame.perceive.cellbook import CellBook, Labeller, ahead, player_cells, shift, WALKABLE, ENTITY  # noqa: E402

PER_MIN = 150          # presses per game-minute at 24 frames a press
# pret/pokered charmap: letters, digits and punctuation (scoring only)
POKEMON_TEXT = set(range(0x80, 0xC0)) | set(range(0xE0, 0xE9)) | set(range(0xF1, 0x100)) - {0xF2}


def sprite_mask(t: dict, rows: int = 18, cols: int = 20, min_px: int = 16) -> np.ndarray:
    """Cells that sprite boxes cover by at least `min_px` pixels (boxes, so transparent sprite pixels count too)."""
    cover = np.zeros((144, 160), bool)
    for x, y, w, h in t["sprites"]:
        cover[max(0, y):max(0, min(144, y + h)), max(0, x):max(0, min(160, x + w))] = True
    return cover.reshape(rows, 8, cols, 8).sum(axis=(1, 3)) >= min_px


def run_game(game: str, cap: str, out: str, chat, budget: float | None, offline: bool, per_call: int) -> dict:
    frames = np.load(os.path.join(cap, f"{game}.npz"))["frames"]
    rows = [json.loads(l) for l in open(os.path.join(cap, f"{game}.jsonl"))]
    book = CellBook()
    log = open(os.path.join(out, f"{game}-labeller.jsonl"), "w")
    start_cost = chat.cost if chat else 0.0
    lab = Labeller(chat if not offline else None, per_call=per_call, budget=budget,
                   spent=(lambda: chat.cost - start_cost) if chat else None,
                   log=lambda e: log.write(json.dumps(e) + "\n"))
    per_min: dict[int, Counter] = defaultdict(Counter)
    novel_sprite = Counter()
    keys_at: list[np.ndarray] = []
    misaligned = 0
    walk = Counter()
    t_lookup = 0.0
    queued_after_budget = 0
    for i, img in enumerate(frames):
        t = rows[i]["truth"]
        if t["scx"] % 8 or t["scy"] % 8:
            misaligned += 1
        t0 = time.perf_counter()
        keys = book.keys(img)
        seen = book.see(img, keys)
        t_lookup += time.perf_counter() - t0
        keys_at.append(keys)
        m = per_min[min(i // PER_MIN, (len(frames) - 2) // PER_MIN)]
        m["frames"] += 1
        m["cells"] += seen["cells"]
        m["known"] += seen["known"]
        m["full"] += seen["known"] == seen["cells"]
        m["screen_known"] += seen["screen_known"]
        if seen["novel"] and keys.shape == (18, 20):
            sm = sprite_mask(t)
            for j in seen["novel"]:
                novel_sprite["sprite" if sm.flat[j] else "background"] += 1
        # queue for the model; past the budget (or offline) enter the cells unlabelled so later frames hit
        if lab.over() or lab.chat is None:
            new = [k for k in set(keys.flat) if k not in book.cells and k not in book.pending]
            if new:
                m["need_call"] += 1
                m["new_keys"] += len(new)
                queued_after_budget += 1
                for k in new:
                    book.cells[k] = {"votes": {}, "label": "U", "state": "unlabelled", "seen": 1, "contradictions": 0,
                                     "source": "none"}
        else:
            before = len(book.pending)
            if lab.add(img, keys, book.phase, book, tag=i):
                m["need_call"] += 1
                m["new_keys"] += len(book.pending) - before
            while lab.ready() and not lab.over():
                lab.flush(book)
                m["calls"] += 1
        # press-and-watch on pixels: a direction press that scrolled the screen or moved the player's cells walked
        press = rows[i]["press"]
        if i and press in ("up", "down", "left", "right"):
            prev_keys = keys_at[i - 1]
            if prev_keys.shape == keys.shape:
                labels_prev = book.labels(prev_keys)
                pc = player_cells(labels_prev)
                if pc:
                    s = shift(frames[i - 1], img, press, steps=(16, 8))
                    moved = s > 0 or set(player_cells(book.labels(keys))) - set(pc) != set()
                    if moved:
                        for r, c in ahead(pc, press, keys.shape, reach=2 if s == 16 else 1):
                            walk["confirm_" + book.confirm(prev_keys[r, c], True)] += 1
    while lab.queue and not lab.over() and lab.chat is not None and lab.failed < 50:
        lab.flush(book)
    for k in list(book.pending):          # queued but never answered (budget): unlabelled, like the cells after it
        book.cells.setdefault(k, {"votes": {}, "label": "U", "state": "unlabelled", "seen": 1, "contradictions": 0, "source": "none"})
    log.close()
    book.save(os.path.join(out, f"{game}-book.json"))
    acc = score(game, frames, rows, keys_at, book)
    mins = sorted(per_min)
    curve = [{"minute": k + 1, "cell_hit": round(per_min[k]["known"] / per_min[k]["cells"], 4),
              "frames_full": round(per_min[k]["full"] / per_min[k]["frames"], 4),
              "screen_hit": round(per_min[k]["screen_known"] / per_min[k]["frames"], 4),
              "screens_needing_call": per_min[k]["need_call"], "new_keys": per_min[k]["new_keys"],
              "calls": per_min[k]["calls"]} for k in mins]
    labelled_cells = sum(1 for e in book.cells.values() if e["state"] != "unlabelled")
    return {"game": game, "frames": len(frames), "misaligned_frames": misaligned, "curve": curve,
            "novel_cells_under_sprites": dict(novel_sprite), "book": book.stats(), "labelled_cells": labelled_cells,
            "calls": lab.calls, "failed_calls": lab.failed, "usd": round((chat.cost - start_cost) if chat else 0.0, 4),
            "screens_after_budget": queued_after_budget, "walk_checks": dict(walk), "accuracy": acc,
            "lookup_ms_per_frame": round(1000 * t_lookup / len(frames), 3)}


def run_objects(game: str, cap: str, out: str) -> dict:
    """The phase-0 cache, offline ($0): frames cut in bands, sprites cut out of new cells as objects. Every new cell
    and object is entered unlabelled, as a labelled run would after its answer comes back. Grader-side truth (the
    console's sprite boxes) only scores the cut afterwards."""
    frames = np.load(os.path.join(cap, f"{game}.npz"))["frames"]
    rows = [json.loads(l) for l in open(os.path.join(cap, f"{game}.jsonl"))]
    book = CellBook()
    per_min: dict[int, Counter] = defaultdict(Counter)
    cut = Counter()
    t_lookup = 0.0
    misaligned = 0
    for i, img in enumerate(frames):
        t = rows[i]["truth"]
        misaligned += bool(t["scx"] % 8 or t["scy"] % 8)
        t0 = time.perf_counter()
        r = book.read(img)
        t_lookup += time.perf_counter() - t0
        m = per_min[min(i // PER_MIN, (len(frames) - 2) // PER_MIN)]
        m["frames"] += 1
        m["cells"] += len(r.cells)
        m["known"] += len(r.cells) - len(r.new_cells)
        m["known_plain"] += sum(r.known)
        m["full"] += r.answered
        m["full_plain"] += all(r.known)
        m["screen_known"] += r.screen_known
        m["bands"] += len(r.bands) > 1
        in_new_obj = {j for o in (r.objects[k] for k in r.new_objects) for j in o["new_cells"]}
        new_keys = {r.cells[j][2] for j in r.new_cells if j not in in_new_obj}
        m["new_keys"] += len(new_keys)
        m["new_objects"] += len(r.new_objects)
        m["need_call"] += bool(new_keys or r.new_objects)
        for o in r.objects:
            if o["new_cells"]:
                m["obj_" + ("exact" if o["known"] and not o["how"] else o["how"] or "new")] += 1
        # grader side: how much of the objects' foreground is under a sprite box, how many new cells under sprites
        # the cut explained
        cover = np.zeros((144, 160), bool)
        for x, y, w, h in t["sprites"]:
            cover[max(0, y):max(0, min(144, y + h)), max(0, x):max(0, min(160, x + w))] = True
        for o in r.objects:
            fg = o["mask"]
            under = cover[o["y"]:o["y"] + o["h"], o["x"]:o["x"] + o["w"]][fg]
            cut["obj_px"] += int(fg.sum())
            cut["obj_px_under_sprite"] += int(under.sum())
            if o["how"] == "track":
                cut["track_px"] += int(fg.sum())
                cut["track_px_under_sprite"] += int(under.sum())
        explained = {j for o in r.objects for j in o["cells"]}
        for j, kn in enumerate(r.known):
            if kn:
                continue
            x, y, _ = r.cells[j]
            if cover[y:y + 8, x:x + 8].sum() >= 16:
                cut["new_under_sprite"] += 1
                cut["new_under_sprite_cut"] += j in explained
        book.learn(r)
    curve = [{"minute": k + 1, "cell_hit": round(per_min[k]["known"] / per_min[k]["cells"], 4),
              "cell_hit_plain": round(per_min[k]["known_plain"] / per_min[k]["cells"], 4),
              "frames_full": round(per_min[k]["full"] / per_min[k]["frames"], 4),
              "frames_full_plain": round(per_min[k]["full_plain"] / per_min[k]["frames"], 4),
              "screen_hit": round(per_min[k]["screen_known"] / per_min[k]["frames"], 4),
              "screens_needing_call": per_min[k]["need_call"], "new_keys": per_min[k]["new_keys"],
              "new_objects": per_min[k]["new_objects"], "banded_frames": per_min[k]["bands"],
              "objects_answered": {h: per_min[k]["obj_" + h] for h in ("exact", "like", "track", "new")},
              "calls": 0} for k in sorted(per_min)]
    return {"game": game, "cache": "objects", "frames": len(frames), "misaligned_frames": misaligned, "curve": curve,
            "book": book.stats(), "labelled_cells": 0, "calls": 0, "failed_calls": 0, "usd": 0.0,
            "cut": dict(cut), "lookup_ms_per_frame": round(1000 * t_lookup / len(frames), 3)}


def score(game: str, frames, rows, keys_at, book: CellBook) -> dict:
    """Labels (the book's final ones) against grader-side truth, over every cell sighting with a label."""
    ent = Counter()
    text = Counter()
    walk = Counter()
    for i, keys in enumerate(keys_at):
        if keys.shape != (18, 20):
            continue
        t = rows[i]["truth"]
        sm = sprite_mask(t)
        tm = t.get("tilemap")
        aligned = t["scx"] % 8 == 0 and t["scy"] % 8 == 0
        for r in range(18):
            for c in range(20):
                e = book.cells.get(keys[r, c])
                if not e or e["state"] == "unlabelled":
                    continue
                L = e["label"]
                if L == "U":
                    ent["unsure"] += 1
                    continue
                ent[("tp" if L in ENTITY else "fn") if sm[r, c] else ("fp" if L in ENTITY else "tn")] += 1
                if tm is not None and aligned:
                    is_text = tm[r * 20 + c] in POKEMON_TEXT
                    text[("tp" if L == "T" else "fn") if is_text else ("fp" if L == "T" else "tn")] += 1
        # walkability truth (Pokemon only): the press moved the player one step on the same map, or a press facing
        # the way it already faced left the position, map and screen alone outside a text box
        press = rows[i]["press"]
        if game.startswith("pokemon") and i and press in ("up", "down", "left", "right") and keys_at[i - 1].shape == (18, 20):
            a, b = rows[i - 1]["truth"], t
            if a["map"] != b["map"] or a["tilemap"][240] == 0x79 or not (a["scx"] % 8 == 0 and a["scy"] % 8 == 0):
                continue
            dx, dy = {"right": (1, 0), "left": (-1, 0), "down": (0, 1), "up": (0, -1)}[press]
            moved = (b["x"] - a["x"], b["y"] - a["y"]) == (dx, dy)
            facing = {"down": 0, "up": 4, "left": 8, "right": 12}[press]
            blocked = (b["x"], b["y"]) == (a["x"], a["y"]) and a["facing"] == facing and b["tilemap"][240] != 0x79
            if not (moved or blocked):
                continue
            # the player's feet are the 2x2 cells at rows 8-9, cols 8-9; the step ahead is the next 2x2
            cells = [(8 + dy * 2 + rr, 8 + dx * 2 + cc) for rr in (0, 1) for cc in (0, 1)]
            for r, c in cells:
                e = book.cells.get(keys_at[i - 1][r, c])
                if not e or e["state"] == "unlabelled":
                    walk["unlabelled"] += 1
                    continue
                L = e["label"]
                if L in WALKABLE:
                    walk["walk_says_walk" if moved else "blocked_says_walk"] += 1
                elif L == "W":
                    walk["walk_says_wall" if moved else "blocked_says_wall"] += 1
                else:
                    walk[("walk" if moved else "blocked") + "_says_" + L] += 1

    def prf(c):
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        return {"precision": round(tp / (tp + fp), 3) if tp + fp else None, "recall": round(tp / (tp + fn), 3) if tp + fn else None,
                **dict(c)}
    return {"entity_vs_sprites": prf(ent), "text_vs_tilemap": prf(text) if text else None, "walk_vs_ram": dict(walk) or None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--games", default="tobutobugirl,postbot,renegade-rush,gbhack,aevilia,pokemon,pokemon-cold")
    ap.add_argument("--budget", type=float, default=0.4, help="Azure dollars per game")
    ap.add_argument("--per-call", type=int, default=40)
    ap.add_argument("--offline", action="store_true", help="no model: hit rates only, $0")
    ap.add_argument("--cache", choices=("cells", "objects"), default="cells",
                    help="cells: one phase per frame, cells only (the first experiment); objects: bands and sprite "
                         "cut-out (phase 0, offline only)")
    a = ap.parse_args()
    if a.cache == "objects" and not a.offline:
        raise SystemExit("the object cache has no labeller yet: run it with --offline")
    os.makedirs(a.out, exist_ok=True)
    chat = None
    if not a.offline:
        from anygame.chat import Chat
        chat = Chat()
        if chat.api not in ("azure", "azure-models"):
            raise SystemExit("the labeller runs on Azure only (ANYGAME_LLM_API=azure)")
    res = []
    for g in a.games.split(","):
        r = run_objects(g, a.cap, a.out) if a.cache == "objects" else run_game(g, a.cap, a.out, chat, a.budget, a.offline, a.per_call)
        res.append(r)
        print(json.dumps({k: v for k, v in r.items() if k != "curve"}), flush=True)
        with open(os.path.join(a.out, "summary.json"), "w") as f:
            json.dump(res, f, indent=1)


if __name__ == "__main__":
    sys.exit(main())
