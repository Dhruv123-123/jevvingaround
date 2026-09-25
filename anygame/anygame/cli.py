from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path

PACKS_DIRS = [os.environ.get("ANYGAME_PACKS"), os.path.join(os.path.dirname(__file__), "..", "packs")]


def find_pack(name: str) -> str:
    if os.path.exists(name):
        return name
    for d in PACKS_DIRS:
        if not d:
            continue
        for cand in (os.path.join(d, name, "pack.yaml"), os.path.join(d, name + ".yaml")):
            if os.path.exists(cand):
                return cand
    sys.exit(f"pack '{name}' not found in {[d for d in PACKS_DIRS if d]}")


def cmd_packs(_):
    from .pack import load_pack
    for d in PACKS_DIRS:
        if not d or not os.path.isdir(d):
            continue
        for entry in sorted(os.listdir(d)):
            p = os.path.join(d, entry, "pack.yaml")
            if os.path.exists(p):
                try:
                    pk = load_pack(p)
                    print(f"{pk.name:14} {len(pk.reads)} reads, {len(pk.actions)} actions, {len(pk.questions)} questions, {len(pk.tests)} tests   {p}")
                except Exception as e:  # noqa: BLE001
                    print(f"{entry:14} invalid: {e}")


def cmd_play(a):
    from .device import open_device
    from .hud import Hud
    from .jev import Jev
    from .loop import Agent
    from .pack import load_pack
    pack = load_pack(find_pack(a.pack))
    device = open_device(a.device, pack.size)
    jev = None if a.sensor == "none" else Jev()
    hud = Hud(a.hud) if a.hud else None
    if hud:
        print(f"HUD on http://localhost:{a.hud}", file=sys.stderr)
    agent = Agent(pack, device, jev, hud, log_path=a.log, max_ticks=a.max_ticks)
    try:
        last = agent.run()
    finally:
        device.close()
    print(json.dumps({"ticks": agent.tick, "last": last.get("action"), "total_cost_usd": round(agent.total_cost, 6), "final_screen": last.get("screen")}, indent=1))
    if a.hud and a.hold:
        print("HUD still up; Ctrl-C to exit", file=sys.stderr)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


def _match(expected, got, tol=0.05):
    if isinstance(expected, dict) and isinstance(got, dict):
        return all(_match(v, got.get(k), tol) for k, v in expected.items())
    if isinstance(expected, (int, float)) and isinstance(got, (int, float)):
        return abs(expected - got) <= max(tol * abs(expected), 0.5 if isinstance(expected, int) else tol)
    if isinstance(expected, list):
        return list(expected) == list(got or [])
    return expected == got


def cmd_eval(a):
    import cv2
    from .jev import Jev
    from .loop import Agent
    from .pack import load_pack
    from .perceive import read_all
    pack = load_pack(find_pack(a.pack))
    jev = Jev() if a.sensor == "jev" else None
    failed = 0
    print(f"{pack.name}  sensor={a.sensor}")
    for t in pack.tests:
        frame = cv2.imread(str(pack.path.parent / t["frame"]))
        t0 = time.perf_counter()
        values, _, timings = read_all(pack, frame, only=set(t["expect"].keys()))
        ms = (time.perf_counter() - t0) * 1000
        misses = {k: (v, values.get(k)) for k, v in t["expect"].items() if not _match(v, values.get(k))}
        ok = not misses
        line = f"  {'✓' if ok else '✗'} {t['frame']}  reads {ms:.0f} ms"
        if misses:
            line += "  mismatch: " + "; ".join(f"{k}: expected {e} got {g}" for k, (e, g) in misses.items())
        if t.get("expect_action"):
            if jev is None:
                line += "  (action check skipped: no sensor)"
            else:
                ag = Agent(pack, device=_Dummy(pack.size), jev=jev)
                vals, _, _ = read_all(pack, frame)
                res = jev.ask({"game": pack.name, "how_to_play": pack.play, "screen": vals, "recent_actions": []}, ag.questions(vals))
                choice = res["answers"]["action"]["choice"]
                ea = t["expect_action"]
                want = ea.get("one_of") or ([ea["is"]] if "is" in ea else None)
                good = (choice in want) if want else (choice not in ea.get("not", []))
                want = want or [f"anything but {'|'.join(ea.get('not', []))}"]
                ok = ok and good
                line += f"  action {choice} {'✓' if good else '✗ expected ' + '|'.join(want)}  jev {res['latency_ms']} ms ${res['cost_usd']:.6f}"
        print(line)
        failed += 0 if ok else 1
    print(f"  {len(pack.tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


class _Dummy:
    def __init__(self, size):
        self._s = size

    def size(self):
        return self._s


def cmd_record(a):
    import cv2
    from .device import open_device
    from .pack import load_pack
    size = load_pack(find_pack(a.pack)).size if a.pack else (540, 960)
    dev = open_device(a.device, size)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    n, t_end = 0, time.time() + a.seconds
    try:
        while time.time() < t_end:
            cv2.imwrite(os.path.join(a.out, f"{n:05d}.png"), dev.frame())
            n += 1
            time.sleep(1.0 / a.hz)
    finally:
        dev.close()
    print(f"saved {n} frames to {a.out}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="anygame", description="One paragraph, any game.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("packs").set_defaults(fn=cmd_packs)
    pl = sub.add_parser("play"); pl.add_argument("pack"); pl.add_argument("--device", default=os.environ.get("DEVICE", "adb")); pl.add_argument("--sensor", default="jev", choices=["jev", "none"])
    pl.add_argument("--hud", type=int, default=int(os.environ.get("HUD_PORT", "8080"))); pl.add_argument("--no-hud", dest="hud", action="store_const", const=0); pl.add_argument("--log", default="anygame.log.jsonl")
    pl.add_argument("--max-ticks", type=int); pl.add_argument("--hold", action="store_true", help="keep the HUD up after the game ends"); pl.set_defaults(fn=cmd_play)
    ev = sub.add_parser("eval"); ev.add_argument("pack"); ev.add_argument("--sensor", default="none", choices=["jev", "none"]); ev.set_defaults(fn=cmd_eval)
    rc = sub.add_parser("record"); rc.add_argument("--device", required=True); rc.add_argument("--out", required=True); rc.add_argument("--seconds", type=int, default=20); rc.add_argument("--hz", type=float, default=2); rc.add_argument("--pack"); rc.set_defaults(fn=cmd_record)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
