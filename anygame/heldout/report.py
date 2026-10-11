"""The score table from one or more run folders.

    python -m heldout.report runs/random runs/standin [runs/jev]

Per game and decider: the milestone fraction (mean over seeds) and the normalised score, where the random decider's
mean on the same game is 0 and every milestone is 1: (score - random) / (1 - random). The suite number is the median
normalised score over the held-out games, with the count of games above 0.1 beside it. Development games are listed
under the table and never enter the median.
"""
from __future__ import annotations
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def load(dirs: list[str]) -> list[dict[str, Any]]:
    rows = []
    for d in dirs:
        p = Path(d) / "runs.jsonl"
        rows += [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    return rows


def normalise(score: float, floor: float | None) -> float | None:
    if floor is None or floor >= 1:
        return None
    return (score - floor) / (1 - floor)


def table(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    skipped: dict[str, str] = {}
    for r in rows:
        if r.get("skipped"):
            skipped[r["game"]] = r["skipped"]
            continue
        by[(r["game"], r["decider"])].append(r)
    games = sorted({g for g, _ in by}, key=lambda g: (by_tier(rows, g) != "held_out", g))
    deciders = [d for d in ("random", "standin", "top", "jev") if any(k[1] == d for k in by)] + sorted({d for _, d in by} - {"random", "standin", "top", "jev"})
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    for (g, d), rs in by.items():
        score = statistics.mean(r["score"] for r in rs)
        cells[(g, d)] = {"score": score, "seeds": len(rs), "rows": rs}
    for (g, d), c in cells.items():
        floor = cells.get((g, "random"), {}).get("score")
        c["norm"] = normalise(c["score"], floor)
    suite = {}
    for d in deciders:
        norms = [cells[(g, d)]["norm"] for g in games if by_tier(rows, g) == "held_out" and (g, d) in cells and cells[(g, d)]["norm"] is not None]
        suite[d] = {"median": statistics.median(norms) if norms else None, "above_0_1": sum(1 for n in norms if n > 0.1), "games": len(norms)}
    return {"games": games, "deciders": deciders, "cells": cells, "suite": suite, "skipped": skipped, "tiers": {g: by_tier(rows, g) for g in games}}


def by_tier(rows, game):
    return next((r.get("tier") for r in rows if r["game"] == game and r.get("tier")), "held_out")


def markdown(t: dict[str, Any]) -> str:
    ds = t["deciders"]
    out = ["| game | kind | " + " | ".join(f"{d} (milestones, normalised)" for d in ds) + " |",
           "|---|---|" + "---|" * len(ds)]
    for g in t["games"]:
        kind = next(iter(t["cells"][(g, ds[0])]["rows"]))["kind"] if (g, ds[0]) in t["cells"] else ""
        dev = " (development)" if t["tiers"][g] != "held_out" else ""
        cols = []
        for d in ds:
            c = t["cells"].get((g, d))
            if not c:
                cols.append("–")
                continue
            n = c["norm"]
            cols.append(f"{c['score']:.2f}, {'–' if n is None else f'{n:+.2f}'}")
        out.append(f"| {g}{dev} | {kind} | " + " | ".join(cols) + " |")
    s = t["suite"]
    out.append("| **held-out suite** | median normalised (games above 0.1) | " + " | ".join(
        "–" if s[d]["median"] is None else f"**{s[d]['median']:+.2f}** ({s[d]['above_0_1']} of {s[d]['games']})" for d in ds) + " |")
    out.append("")
    out.append("Where each run stalled (mean over seeds): the first milestone not reached, how often the screen the agent "
               "decided on was the same as the one before (a press that did nothing), and how many different screens it saw.")
    out.append("")
    out.append("| game | decider | reached (per seed) | stalled before | unchanged screen | distinct screens | presses | wall s |")
    out.append("|---|---|---|---|---|---|---|---|")
    for g in t["games"]:
        for d in ds:
            c = t["cells"].get((g, d))
            if not c:
                continue
            rs = c["rows"]
            reached = " / ".join(str(len(r["reached"])) for r in rs) + f" of {rs[0]['milestones']}"
            stalls = sorted({r.get("stalled_before") or "nothing (all reached)" for r in rs})
            out.append(f"| {g} | {d} | {reached} | {'; '.join(stalls)} | {statistics.mean(r['unchanged_screen_rate'] for r in rs):.0%} | "
                       f"{statistics.mean(r['distinct_screens'] for r in rs):.0f} | {statistics.mean(r['presses'] for r in rs):.0f} | {statistics.mean(r['wall_s'] for r in rs):.1f} |")
    for g, why in t["skipped"].items():
        out.append(f"\nNot run: {why}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    dirs = argv if argv is not None else sys.argv[1:]
    if not dirs:
        raise SystemExit(__doc__)
    print(markdown(table(load(dirs))))


if __name__ == "__main__":
    main()
