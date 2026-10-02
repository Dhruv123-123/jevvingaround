"""Per-game numbers for a scripts/scale_run.sh directory, from the logs' `truth` (the page's own state), so the
outcome does not depend on the pack reading the end screen right.
  python scripts/tally_run.py <run dir> [--json]
Per episode: how it ended (won / lost / dead / over / alive at the cap / stalled at the cap), ticks, decisions, and the
game's own score (Snake length and score, 2048 best tile and score, Tetris lines and score). A stall is an episode
that hit the cap while the page state had not changed for its last 20 ticks."""
from __future__ import annotations
import argparse
import collections
import json
import statistics
from pathlib import Path


def episode(path: Path) -> dict:
    recs = [json.loads(l) for l in open(path) if l.strip()]
    game, sensor = path.name.split("-")[:2]
    seed = path.stem.rsplit("-", 1)[1]
    last = recs[-1] if recs else {}
    tr = next((r["truth"] for r in reversed(recs) if r.get("truth")), {}) or {}
    stopped = last.get("action") == "stop"
    tail = [json.dumps(r.get("truth"), sort_keys=True) for r in recs[-20:]]
    frozen = len(recs) >= 20 and len(set(tail)) == 1
    ep = {"game": game, "sensor": sensor, "seed": seed, "ticks": len(recs), "decisions": sum(1 for r in recs if "jev_ms" in r),
          "sensor_errors": sum(1 for r in recs if str(r.get("sensor", "")).startswith("error") or str(r.get("reason", "")).startswith("sensor error")),
          "budget_skips": sum(1 for r in recs if r.get("skipped") == "budget")}
    if game == "connect4":
        end = {1: "won", 2: "lost", 3: "draw"}.get(tr.get("over"))
    elif game == "snake":
        end = "won" if tr.get("won") else "dead" if tr.get("over") else None
        ep.update(length=len(tr.get("snake") or []), score=tr.get("score"))
    elif game == "2048":
        end = "over" if tr.get("over") else None
        ep.update(best_tile=max(tr.get("grid") or [0]), score=tr.get("score"))
    elif game == "tetris":
        end = "over" if tr.get("over") else None
        ep.update(lines=tr.get("lines"), score=tr.get("score"))
    else:
        end = None
    if end is None:
        end = "stalled at cap" if frozen else "alive at cap"
    elif not stopped:
        end += " (not noticed)"            # the game ended but the pack's stop_when never fired
    ep["end"] = end
    return ep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    eps = [episode(p) for p in sorted(Path(a.run, "logs").glob("*.jsonl"))]
    if a.json:
        print(json.dumps(eps, indent=1))
        return
    groups = collections.defaultdict(list)
    for e in eps:
        groups[(e["game"], e["sensor"])].append(e)
    print(f"{len(eps)} episodes")
    for (g, s), es in sorted(groups.items()):
        ends = collections.Counter(e["end"] for e in es)
        line = f"{g:9s} {s:7s} n={len(es)}  " + ", ".join(f"{k} {v}" for k, v in ends.most_common())
        line += f"  | ticks median {statistics.median(e['ticks'] for e in es):.0f}"
        for k in ("length", "best_tile", "lines", "score"):
            vals = [e[k] for e in es if e.get(k) is not None]
            if vals:
                line += f", {k} median {statistics.median(vals):g} max {max(vals):g}"
        errs = sum(e["sensor_errors"] for e in es)
        if errs:
            line += f", sensor errors {errs}"
        print(line)


if __name__ == "__main__":
    main()
