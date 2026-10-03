"""Usage: scripts/go_agree.py <logs dir> [ref playouts]. Jev vs the two rankings it was given (worth order, 64-playout win rate), checked with REF playouts per move."""
import glob, json, sys, statistics as st
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), ".."))
from anygame.perceive import go

REF = int(sys.argv[2]) if len(sys.argv) > 2 else 512
rows = []
for f in sorted(glob.glob(sys.argv[1] + "/*.jsonl")):
    recs = [json.loads(l) for l in open(f)]
    end = next((r["screen"].get("status") for r in reversed(recs) if r.get("screen", {}).get("status") in ("we_won", "we_lost")), None)
    for r in recs:
        if "screen" not in r:
            continue
        ch = (r.get("choices") or {}).get("place__cell")
        g = r["screen"].get("go") or {}
        po = g.get("playouts") or {}
        if not ch or r.get("choice") != "place" or g.get("urgent") or not g.get("best") or not all(c in po for c in g["best"]):
            continue
        best = g["best"]
        rows.append({"game": f.rsplit("-", 1)[-1][:-6], "end": end, "tick": r["tick"], "board": r["screen"]["board"], "jev": ch,
                     "w_top": best[0], "po_top": max(best, key=lambda c: (po[c]["win"], po[c]["margin"])), "po": po, "worth": g["worth"]})


def ref(r, cells):
    b, w, h = go._board(r["board"])
    pts = {go.cell(p): p for p in b}
    go._PLAYOUT_CACHE.clear()
    return go.playouts(b, [pts[c] for c in dict.fromkeys(cells)], "B", "W", w, h, ".", 6.5, REF)


n = len(rows)
off = [r for r in rows if r["jev"] != r["w_top"]]
print(f"free choices {n}; Jev took worth top {n - len(off)} ({(n - len(off)) / n:.0%}); playout top = worth top {sum(r['po_top'] == r['w_top'] for r in rows)}")
print(f"Jev off the worth top: {len(off)}, of which on the playout top {sum(r['jev'] == r['po_top'] for r in off)}")
ds = []
for r in off:
    R = ref(r, [r["jev"], r["w_top"]])
    d = R[r["jev"]]["win"] - R[r["w_top"]]["win"]
    ds.append(d)
    print(f"  g{r['game']} {r['end']} t{r['tick']}: jev {r['jev']} (worth {r['worth'].get(r['jev'])}, po64 {r['po'][r['jev']]['win']}) vs worth top {r['w_top']} "
          f"(worth {r['worth'][r['w_top']]}, po64 {r['po'][r['w_top']]['win']}) | ref{REF} {R[r['jev']]['win']} vs {R[r['w_top']]['win']} d {d:+.2f}")
if ds:
    print(f"  Jev right (+>0.03) {sum(d > 0.03 for d in ds)}, wrong (<-0.03) {sum(d < -0.03 for d in ds)}, even {sum(abs(d) <= 0.03 for d in ds)}, mean {st.mean(ds):+.3f}")
# would always taking the 64-playout top have beaten the worth top?
dd = []
for r in rows:
    if r["po_top"] != r["w_top"]:
        R = ref(r, [r["po_top"], r["w_top"]])
        dd.append(R[r["po_top"]]["win"] - R[r["w_top"]]["win"])
print(f"playout top vs worth top where they differ ({len(dd)}): better {sum(d > 0.03 for d in dd)}, worse {sum(d < -0.03 for d in dd)}, even {sum(abs(d) <= 0.03 for d in dd)}, mean {st.mean(dd):+.3f}")
