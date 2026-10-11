"""Before/after table for phase 0 of the screen-only roadmap: the first experiment's cache (one phase per frame,
cells only) against the phase-0 cache (bands, sprites cut out as objects), both offline over the same captures.

    python scripts/screenonly_phase0.py BEFORE/summary.json AFTER/summary.json [--usd-per-item 0.00005]

Projected dollars per game-hour, warm = items a model would be asked about per warm minute (new cells no object
explains, plus new objects) x 60 x the first experiment's measured price per labelled cell.
"""
from __future__ import annotations
import argparse
import json

WARM = range(5, 10)        # game-minutes 6-10


def warm(r: dict, k: str) -> float:
    w = [x for x in r["curve"] if x["minute"] - 1 in WARM]
    return sum(x.get(k, 0) for x in w) / len(w)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--usd-per-item", type=float, default=0.05 / 1000, help="first experiment: ~$0.05 per 1,000 cells")
    a = ap.parse_args()
    before = {r["game"]: r for r in json.load(open(a.before))}
    after = {r["game"]: r for r in json.load(open(a.after))}
    print("| game | frames fully answered, warm: before | after | cells answered, warm: before | after | "
          "items for the model per warm min: before | after | projected $/game-hour: before | after |")
    print("|---|---|---|---|---|---|---|---|---|")
    for g, b in before.items():
        x = after.get(g)
        if not x:
            continue
        ib, ia = warm(b, "new_keys"), warm(x, "new_keys") + warm(x, "new_objects")
        print(f"| {g} | {100 * warm(b, 'frames_full'):.1f}% | {100 * warm(x, 'frames_full'):.1f}% | "
              f"{100 * warm(b, 'cell_hit'):.1f}% | {100 * warm(x, 'cell_hit'):.1f}% | {ib:.0f} | {ia:.0f} | "
              f"${ib * 60 * a.usd_per_item:.2f} | ${ia * 60 * a.usd_per_item:.2f} |")
    print()
    print("| game | frames cut in more than one band, warm | new objects answered by: exact / look-alike / tracking / "
          "still new (warm, per min) | object pixels under a sprite box (grader) | of which tracked | new cells under "
          "sprites the cut explained (grader) | lookup ms/frame |")
    print("|---|---|---|---|---|---|---|")
    for g, x in after.items():
        w = [c for c in x["curve"] if c["minute"] - 1 in WARM]
        oa = {h: sum(c["objects_answered"][h] for c in w) / len(w) for h in ("exact", "like", "track", "new")}
        cut = x["cut"]
        pct = lambda n, d: f"{100 * cut.get(n, 0) / cut[d]:.0f}%" if cut.get(d) else "–"
        print(f"| {g} | {100 * warm(x, 'banded_frames') / 150:.0f}% | {oa['exact']:.0f} / {oa['like']:.0f} / "
              f"{oa['track']:.0f} / {oa['new']:.0f} | {pct('obj_px_under_sprite', 'obj_px')} | "
              f"{pct('track_px_under_sprite', 'track_px')} | {pct('new_under_sprite_cut', 'new_under_sprite')} | "
              f"{x['lookup_ms_per_frame']:.1f} |")


if __name__ == "__main__":
    main()
