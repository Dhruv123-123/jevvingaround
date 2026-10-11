"""How well the tile-text read reads a game's text, against OCR, from power-on with scripted presses.

    python scripts/tiletext_check.py <rom> --presses 300 [--truth pokemon] [--labeller chat|ocr] [--out DIR]

Every press, the screen is read three ways: `kind: tiletext` (glyphs learned once), the pack's OCR read, and, for
Pokemon only, the truth: the screen's tile map in work RAM (0xC3A0, 20x18) through the published charmap. The truth
is for scoring here and nowhere else; the agent never reads it. Reports per-cell accuracy and coverage of the tile
read, a character-level similarity of each read to the truth, the labeller's calls and time, and read time.
"""
from __future__ import annotations
import argparse
import difflib
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# pret/pokered charmap.asm: the published one, used only to score
POKEMON = {**{0x80 + i: chr(65 + i) for i in range(26)}, **{0xA0 + i: chr(97 + i) for i in range(26)},
           **{0xF6 + i: str(i) for i in range(10)}, 0x7F: " ", 0x9A: "(", 0x9B: ")", 0x9C: ":", 0x9D: ";", 0x9E: "[",
           0x9F: "]", 0xBA: "é", 0xE0: "'", 0xE3: "-", 0xE6: "?", 0xE7: "!", 0xE8: ".", 0xF3: "/", 0xF4: ",",
           0xED: ">", 0xEE: "▼", 0xF1: "x"}
TWO = {0xBB: "'d", 0xBC: "'l", 0xBD: "'s", 0xBE: "'t", 0xBF: "'v", 0xE4: "'r", 0xE5: "'m", 0xE1: "PK", 0xE2: "MN"}


def truth_grid(pb) -> list[list[str | None]]:
    t = [pb.memory[0xC3A0 + i] for i in range(360)]
    return [[POKEMON.get(v, TWO.get(v)) for v in t[r * 20:(r + 1) * 20]] for r in range(18)]


def truth_text(grid) -> str:
    segs = []
    for row in grid:
        s = "".join(c if c is not None else "\x00" for c in row)
        for seg in s.split("\x00"):
            seg = seg.strip()
            if sum(1 for ch in seg if ch != " ") >= 2:
                segs.append(seg)
    return " ".join(segs)


def sim(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("--presses", type=int, default=300)
    ap.add_argument("--truth", choices=["pokemon", "none"], default="none")
    ap.add_argument("--labeller", choices=["chat", "ocr"], default="chat")
    ap.add_argument("--out", default=None)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    from pyboy import PyBoy
    import cv2
    from anygame.perceive import tiletext, ocr
    from anygame.geometry import Rect

    pb = PyBoy(a.rom, window="null", sound_emulated=False)
    pb.set_emulation_speed(0)
    pb.tick(400, False)
    rng = np.random.default_rng(a.seed)
    # the labeller answers before the next press: in a run it works in the background while ticks take ~1 s each,
    # here presses take milliseconds, so waiting for it is what makes the learning curve comparable
    r = {"kind": "tiletext", "labeller": a.labeller, "sync": True}
    reader = tiletext.reader(r)
    calls_log = []
    reader.log = calls_log.append
    stats = {"frames": 0, "text_frames": 0, "cells_truth": 0, "cells_read": 0, "cells_right": 0, "cells_right_nocase": 0, "sim_tile": [], "sim_ocr": [], "sim_blend": [], "sim_tile_sampled": [],
             "ms_tile": [], "ms_ocr": [], "wrong": {}}
    samples = []
    # mostly A (pages text, confirms), some START and directions: gets through a title, menus and a first room
    keys = ["a"] * 6 + ["start", "b", "down", "up", "left", "right"]
    for i in range(a.presses):
        k = keys[int(rng.integers(len(keys)))]
        pb.button_press(k)
        pb.tick(8, False)
        pb.button_release(k)
        pb.tick(40, True)
        frame = cv2.cvtColor(np.ascontiguousarray(pb.screen.ndarray[:, :, :3]), cv2.COLOR_RGB2BGR)
        frame = cv2.resize(frame, (480, 432), interpolation=cv2.INTER_NEAREST)
        stats["frames"] += 1
        t0 = time.perf_counter()
        text, st = reader.read(frame)
        stats["ms_tile"].append((time.perf_counter() - t0) * 1000)
        if a.truth != "pokemon":
            if text and i % 10 == 0:
                t0 = time.perf_counter()
                o = ocr.read(frame, Rect.parse([0, 0, 1, 1]), None, {"upscale": 0.67})
                stats["ms_ocr"].append((time.perf_counter() - t0) * 1000)
                samples.append({"press": i, "tiletext": text, "ocr": o, **st})
            continue
        g = truth_grid(pb)
        tt = truth_text(g)
        if not tt:
            continue
        stats["text_frames"] += 1
        # per cell: the tile read's label for the cell against the charmap's character
        _img, kk, kinds = tiletext.cells(frame)
        for rr in range(18):
            for q in range(20):
                c = g[rr][q]
                if c is None or c == " " or kinds[rr, q] != 1:
                    continue
                stats["cells_truth"] += 1
                lab = reader.book.labels.get(kk[rr][q])
                if lab is None or lab == tiletext.NOT_TEXT:
                    continue
                stats["cells_read"] += 1
                if lab.lower() == c.lower() or (len(c) == 2 and lab.lower() in c.lower()):
                    stats["cells_right_nocase"] += 1
                if lab == c or (len(c) == 2 and lab in c):
                    stats["cells_right"] += 1
                else:
                    w = f"{c}->{lab}"
                    stats["wrong"][w] = stats["wrong"].get(w, 0) + 1
        stats["sim_tile"].append(sim(text.lower(), tt.lower()))
        if i % 5 == 0:
            t0 = time.perf_counter()
            o = ocr.read(frame, Rect.parse([0, 0, 1, 1]), None, {"upscale": 0.67})
            stats["ms_ocr"].append((time.perf_counter() - t0) * 1000)
            stats["sim_ocr"].append(sim(o.lower(), tt.lower()))
            blend = o if st["unknown"] > max(2, st["known"]) else text        # what the pack reads with `fallback: ocr`
            stats["sim_blend"].append(sim(blend.lower(), tt.lower()))
            stats["sim_tile_sampled"].append(sim(text.lower(), tt.lower()))
            samples.append({"press": i, "truth": tt, "tiletext": text, "ocr": o, **st})
    reader.wait()
    b = reader.book
    md = lambda v: round(float(np.median(v)), 3) if v else None  # noqa: E731
    out = {
        "rom": os.path.basename(a.rom), "presses": a.presses, "labeller": a.labeller,
        "glyphs_labelled": len(b.labels), "labeller_calls": b.calls, "labeller_rejected_lines": b.rejected,
        "labeller_median_ms": md(b.ms), "labeller_total_s": round(sum(b.ms) / 1000, 1), "read_ms_median": md(stats["ms_tile"]), "ocr_ms_median": md(stats["ms_ocr"]),
        "frames": stats["frames"], "frames_with_text": stats["text_frames"],
    }
    if a.truth == "pokemon":
        out.update({
            "text_cells": stats["cells_truth"],
            "coverage": round(stats["cells_read"] / max(1, stats["cells_truth"]), 3),
            "accuracy_of_read_cells": round(stats["cells_right"] / max(1, stats["cells_read"]), 4),
            "accuracy_ignoring_case": round(stats["cells_right_nocase"] / max(1, stats["cells_read"]), 4),
            "similarity_to_truth_tiletext_median": md(stats["sim_tile"]),
            "similarity_to_truth_ocr_median": md(stats["sim_ocr"]),
            "similarity_tiletext_last_half_median": md(stats["sim_tile"][len(stats["sim_tile"]) // 2:]),
            "similarity_with_ocr_fallback_median": md(stats["sim_blend"]),
            "similarity_last_third": {k: md(stats[k][2 * len(stats[k]) // 3:]) for k in ("sim_tile_sampled", "sim_ocr", "sim_blend")},
            "wrong": dict(sorted(stats["wrong"].items(), key=lambda kv: -kv[1])[:20]),
        })
    print(json.dumps(out, indent=1, ensure_ascii=False))
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        json.dump(out, open(os.path.join(a.out, "summary.json"), "w"), indent=1, ensure_ascii=False)
        with open(os.path.join(a.out, "samples.jsonl"), "w") as f:
            for s in samples:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        with open(os.path.join(a.out, "labeller.jsonl"), "w") as f:
            for c in calls_log:
                f.write(json.dumps(c) + "\n")
        b.save(os.path.join(a.out, "glyphs.json"))


if __name__ == "__main__":
    main()
