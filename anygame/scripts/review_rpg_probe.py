"""Design-review probe: what today's screen machinery does on a Game Boy RPG.

Plays a ROM in PyBoy with uniform random presses (the `random` decider's floor, one press per tick like the loop),
samples a frame every `--every` emulator frames and measures:
  - how many "screens" the 16x16 fingerprint index (anygame/fingerprint.py, new screen at distance > 40) creates,
    and how that count grows with play time: the classifier the loop uses to pick a mode
  - how often consecutive samples are "a different screen" by that test
  - how long a fingerprint, a full-frame OCR pass (the read a text box would need) and a 1 KB RAM read take

    python scripts/review_rpg_probe.py /mnt/project-files/roms/homebrew/aevilia.gbc --frames 36000
"""
from __future__ import annotations
import argparse
import json
import random
import time
import numpy as np
import cv2

from anygame.fingerprint import Index, distance, fingerprint

BUTTONS = ["a", "b", "start", "select", "up", "down", "left", "right"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("--frames", type=int, default=36000)     # 10 minutes of game time at 60 fps
    ap.add_argument("--every", type=int, default=30)          # one tick every half second, as at tick_hz 2
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--ocr", type=int, default=20)            # OCR passes to time
    a = ap.parse_args()
    from pyboy import PyBoy
    rng = random.Random(a.seed)
    pb = PyBoy(a.rom, window="null", sound_emulated=False)
    pb.set_emulation_speed(0)
    pb.tick(240, render=False)
    idx = Index(40.0)
    growth, changes, fp_ms, ram_ms, still = [], 0, [], [], 0
    prev_fp, prev_raw, frames_out = None, None, []
    for t in range(0, a.frames, a.every):
        b = rng.choice(BUTTONS)
        pb.button_press(b)
        pb.tick(6, render=False)
        pb.button_release(b)
        pb.tick(a.every - 7, render=False)
        pb.tick(1, render=True)
        raw = np.ascontiguousarray(pb.screen.ndarray[:, :, :3])
        frame = cv2.resize(cv2.cvtColor(raw, cv2.COLOR_RGB2BGR), (480, 432), interpolation=cv2.INTER_NEAREST)
        t0 = time.perf_counter()
        fp = fingerprint(frame)
        fp_ms.append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        _ = bytes(pb.memory[0xC000:0xC400])                       # 1 KB of work RAM
        ram_ms.append((time.perf_counter() - t0) * 1000)
        if idx.known(fp) is None:
            idx.add(f"s{len(idx.entries)}", fp)
        if prev_fp is not None and distance(prev_fp, fp) > 40:
            changes += 1
        if prev_raw is not None and np.array_equal(prev_raw, raw):
            still += 1
        prev_fp, prev_raw = fp, raw
        if len(frames_out) < a.ocr and t % (a.every * 37) == 0:
            frames_out.append(frame)
        growth.append(len(idx.entries))
    pb.stop(save=False)
    n = len(growth)
    from anygame.perceive.ocr import engine
    eng = engine()
    eng(frames_out[0])                                            # load the model before timing
    ocr_ms = []
    for f in frames_out:
        t0 = time.perf_counter()
        eng(f)
        ocr_ms.append((time.perf_counter() - t0) * 1000)
    minute = 60 * 60 // a.every
    out = {
        "rom": a.rom.rsplit("/", 1)[-1], "ticks": n, "game_minutes": round(a.frames / 3600, 1),
        "screens_after_minute": {m: growth[min(n, m * minute) - 1] for m in (1, 2, 5, 10) if m * minute <= n},
        "screens_total": growth[-1],
        "changed_screen_share": round(changes / max(1, n - 1), 3),
        "identical_frame_share": round(still / max(1, n - 1), 3),
        "fingerprint_ms_median": round(float(np.median(fp_ms)), 3),
        "ram_1kb_ms_median": round(float(np.median(ram_ms)), 3),
        "ocr_full_frame_ms_median": round(float(np.median(ocr_ms)), 1),
    }
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
