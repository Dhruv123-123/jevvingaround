"""Capture what a screen-only agent would see: the frame after each press, for a fixed budget of random presses.

The agent side is pixels only. Beside each frame the script stores grader-side truth that the perception pass never
reads, only scores against: sprite boxes from OAM (where entities are), the scroll registers, and for Pokemon Red
and Aevilia the player's position bytes (and Pokemon's on-screen tile map, decoded with pret's charmap for text).

    python scripts/screenonly_capture.py --out runs/screenonly [--games tobutobugirl,pokemon] [--presses 1500]
"""
from __future__ import annotations
import argparse
import json
import os
import random
import sys
import time

import numpy as np

ROMS = "/mnt/project-files/roms"
GAMES = {
    "tobutobugirl": {"rom": f"{ROMS}/heldout/tobutobugirl.gb"},
    "postbot": {"rom": f"{ROMS}/heldout/postbot.gb"},
    "renegade-rush": {"rom": f"{ROMS}/heldout/renegade-rush.gb"},
    "gbhack": {"rom": f"{ROMS}/heldout/gbhack.gbc"},
    "aevilia": {"rom": f"{ROMS}/heldout/aevilia.gbc"},
    "pokemon": {"rom": f"{ROMS}/pokemon-red.gb",
                "state": "/mnt/project-files/anygame/pokemon-red/longhorizon/ck45700/emulator.state"},
    "pokemon-cold": {"rom": f"{ROMS}/pokemon-red.gb"},
}
# random presses, directions weighted up so the player moves (as the held-out random floor does, give or take)
BUTTONS = ["up", "down", "left", "right", "a", "b", "start", "select"]
WEIGHTS = [3, 3, 3, 3, 2, 1, 0.4, 0.2]


def truth(pb, game: str) -> dict:
    m = pb.memory
    lcdc = m[0xFF40]
    tall = bool(lcdc & 0x04)
    sprites, slots = [], []
    if lcdc & 0x02:
        for i in range(40):
            s = pb.get_sprite(i)
            if s.on_screen:
                sprites.append([s.x, s.y, 8, 16 if tall else 8])
                slots.append([i, s.tile_identifier])
    # slots: OAM slot and tile of each sprite box (grader side: which sprites are the player is found from these)
    t = {"scx": m[0xFF43], "scy": m[0xFF42], "win": bool(lcdc & 0x20), "wx": m[0xFF4B], "wy": m[0xFF4A],
         "sprites": sprites, "slots": slots}
    if game.startswith("pokemon"):
        t.update({"x": m[0xD362], "y": m[0xD361], "map": m[0xD35E], "facing": m[0xC109],
                  "tilemap": [m[0xC3A0 + i] for i in range(360)]})
    elif game == "aevilia":
        t.update({"x": m[0xD712] | m[0xD713] << 8, "y": m[0xD710] | m[0xD711] << 8, "map": m[0xC3C4]})
    return t


def capture(game: str, out: str, presses: int, seed: int, hold: int, after: int, every: int = 0) -> dict:
    from pyboy import PyBoy
    g = GAMES[game]
    pb = PyBoy(g["rom"], window="null", sound_emulated=False)
    pb.set_emulation_speed(0)
    if g.get("state"):
        pb.load_state(open(g["state"], "rb"))
        pb.tick(1, True)
    else:
        pb.tick(120, True)
    rng = random.Random(seed)
    frames = [np.array(pb.screen.ndarray[:, :, :3])]
    rows = [{"i": 0, "press": None, "truth": truth(pb, game)}]
    fine, fine_rows = [frames[0]], [{"i": 0, "k": 0, "press": None, "held": False, "truth": rows[0]["truth"]}]

    def run(n: int, i: int, b: str, held: bool, k0: int) -> int:
        """Tick n frames; with `every`, keep a frame every `every` ticks (same emulation either way)."""
        if not every:
            pb.tick(n, False)
            return k0
        k = k0
        while n > 0:
            step = min(every, n)
            pb.tick(step - 1, False) if step > 1 else None
            pb.tick(1, True)
            n -= step
            k += step
            fine.append(np.array(pb.screen.ndarray[:, :, :3]))
            fine_rows.append({"i": i, "k": k, "press": b, "held": held, "truth": truth(pb, game)})
        return k

    t0 = time.time()
    for i in range(1, presses + 1):
        b = rng.choices(BUTTONS, WEIGHTS)[0]
        pb.button_press(b)
        k = run(hold, i, b, True, 0)
        pb.button_release(b)
        if every:
            run(after, i, b, False, k)       # its last kept frame is the press's frame below
        else:
            pb.tick(after - 1, False)
            pb.tick(1, True)
        frames.append(np.array(pb.screen.ndarray[:, :, :3]))
        rows.append({"i": i, "press": b, "truth": truth(pb, game)})
    pb.stop(save=False)
    os.makedirs(out, exist_ok=True)
    if every:
        np.savez_compressed(os.path.join(out, f"{game}-fine.npz"), frames=np.stack(fine))
        with open(os.path.join(out, f"{game}-fine.jsonl"), "w") as f:
            for r in fine_rows:
                f.write(json.dumps(r) + "\n")
    np.savez_compressed(os.path.join(out, f"{game}.npz"), frames=np.stack(frames))
    with open(os.path.join(out, f"{game}.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return {"game": game, "frames": len(frames), "game_frames": presses * (hold + after), "wall_s": round(time.time() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--games", default=",".join(GAMES))
    ap.add_argument("--presses", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--hold", type=int, default=8)
    ap.add_argument("--after", type=int, default=16)
    ap.add_argument("--every", type=int, default=0, help="also keep a frame every N ticks (GAME-fine.npz)")
    a = ap.parse_args()
    for game in a.games.split(","):
        print(json.dumps(capture(game, a.out, a.presses, a.seed, a.hold, a.after, a.every)), flush=True)


if __name__ == "__main__":
    sys.exit(main())
