"""Tables for the screen-only perception write-up from screenonly_run.py summaries.

    python scripts/screenonly_report.py runs/screenonly/pass/*/summary.json
"""
from __future__ import annotations
import json
import sys

WARM = range(5, 10)        # game-minutes 6-10: the book has seen the first half of the run


def row(r: dict) -> dict:
    c = r["curve"]
    w = [x for x in c if x["minute"] - 1 in WARM]
    mean = lambda k, xs: sum(x[k] for x in xs) / len(xs)
    keys_spent = r["labelled_cells"] or 1
    per_key = r["usd"] / keys_spent if r["usd"] else None
    warm_keys = mean("new_keys", w)
    ns = r["novel_cells_under_sprites"]
    acc = r["accuracy"]
    walk = acc.get("walk_vs_ram") or {}
    return {
        "game": r["game"], "unique_cells": r["book"]["cells"],
        "hit_m1": c[0]["cell_hit"], "hit_warm": mean("cell_hit", w), "full_warm": mean("frames_full", w),
        "screen_warm": mean("screen_hit", w), "new_keys_warm_per_min": warm_keys,
        "screens_needing_call_warm_per_min": mean("screens_needing_call", w),
        "calls": r["calls"], "usd": r["usd"], "labelled": r["labelled_cells"], "usd_per_key": per_key,
        "usd_per_hour_warm": warm_keys * 60 * per_key if per_key else None,
        "usd_first_10min_all_labelled": r["book"]["cells"] * per_key if per_key else None,
        "sprite_share_novel": ns.get("sprite", 0) / max(1, sum(ns.values())),
        "misaligned": r["misaligned_frames"] / r["frames"],
        "entity_p": acc["entity_vs_sprites"]["precision"], "entity_r": acc["entity_vs_sprites"]["recall"],
        "text_p": (acc.get("text_vs_tilemap") or {}).get("precision"), "text_r": (acc.get("text_vs_tilemap") or {}).get("recall"),
        "walk": walk, "walk_checks": r.get("walk_checks"), "states": r["book"]["states"],
        "contradictions": r["book"]["contradictions"], "lookup_ms": r["lookup_ms_per_frame"],
    }


def fmt(v, pct=False, money=False):
    if v is None:
        return "–"
    if pct:
        return f"{100 * v:.1f}%"
    if money:
        return f"${v:.2f}" if v >= 0.1 else f"${v:.3f}"
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def main() -> None:
    rows = []
    for p in sys.argv[1:]:
        rows += [row(r) for r in json.load(open(p))]
    print("| game | unique cells | cell hit, min 1 | cell hit, min 6-10 | frames fully answered, min 6-10 | same whole screen seen before | new cells per min, warm | share of new cells under sprites | frames off the 8-px grid |")
    print("|---|---|---|---|---|---|---|---|---|")
    for x in rows:
        print(f"| {x['game']} | {x['unique_cells']} | {fmt(x['hit_m1'], pct=True)} | {fmt(x['hit_warm'], pct=True)} | {fmt(x['full_warm'], pct=True)} | {fmt(x['screen_warm'], pct=True)} | {x['new_keys_warm_per_min']:.0f} | {fmt(x['sprite_share_novel'], pct=True)} | {fmt(x['misaligned'], pct=True)} |")
    print()
    print("| game | Azure calls | dollars | cells labelled | dollars per 1,000 cells | dollars to label all of the first 10 min | projected dollars per game-hour, warm | entity precision / recall (vs sprites) | text precision / recall (Pokemon tile map) |")
    print("|---|---|---|---|---|---|---|---|---|")
    for x in rows:
        print(f"| {x['game']} | {x['calls']} | {fmt(x['usd'], money=True)} | {x['labelled']} | {fmt(x['usd_per_key'] * 1000 if x['usd_per_key'] else None, money=True)} | {fmt(x['usd_first_10min_all_labelled'], money=True)} | {fmt(x['usd_per_hour_warm'], money=True)} | {fmt(x['entity_p'])} / {fmt(x['entity_r'])} | {fmt(x['text_p'])} / {fmt(x['text_r'])} |")
    print()
    for x in rows:
        print(x["game"], "walk vs RAM:", json.dumps(x["walk"]), "| pixel walk checks:", json.dumps(x["walk_checks"]),
              "| states:", json.dumps(x["states"]), "| contradictions:", x["contradictions"], "| lookup ms/frame:", x["lookup_ms"])


if __name__ == "__main__":
    main()
