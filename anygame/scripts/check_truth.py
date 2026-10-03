"""Check a bench run's pixel reads against the page's own state, tick by tick.

Run the bench with ANYGAME_LOG_TRUTH=1 and `#state=window.__state()` on the device URL, so every log record carries
`truth` beside `screen`; then `python scripts/check_truth.py <log.jsonl>...` prints, per log, how many ticks read
the board, the status and the located things the way the game itself has them. The frame is grabbed a few
milliseconds before the state is evaluated, so on a real-time game a tick where the game stepped in between shows
as a mismatch; `--settled` counts only ticks whose truth equals the previous tick's (nothing moved while the frame was taken).
Covers the bundled games: snake, connect4, 2048, tetris, go."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


def cell(c, r):
    return f"c{c}r{r}"


def at(board, c, r):
    """A matrix read as the log has it (a list of row strings, r1 on top) or as a c<col>r<row> dict."""
    if isinstance(board, dict):
        return board.get(cell(c, r))
    if isinstance(board, list) and 0 < r <= len(board) and 0 < c <= len(board[r - 1]):
        return board[r - 1][c - 1]
    return None


def check_connect4(scr, tr):
    out = {}
    board, grid = scr.get("board"), tr.get("grid")
    if board and grid:
        sym = {0: ".", 1: "R", 2: "Y"}
        bad = [f"{cell(i % 7 + 1, i // 7 + 1)}:{at(board, i % 7 + 1, i // 7 + 1)}!={sym.get(v)}" for i, v in enumerate(grid) if at(board, i % 7 + 1, i // 7 + 1) != sym.get(v)]
        out["board"] = bad
    over = tr.get("over")
    want = {0: None, 1: "we_won", 2: "we_lost", 3: "draw"}.get(over)
    st = scr.get("status")
    if want is not None:
        out["status"] = [] if st == want else [f"{st}!={want}"]
    elif st in ("we_won", "we_lost", "draw"):
        out["status"] = [f"{st} while playing"]
    else:
        out["status"] = []
    return out


def check_2048(scr, tr):
    tiles, grid = scr.get("tiles"), tr.get("grid")
    out = {}
    if isinstance(tiles, dict) and grid:
        out["board"] = [f"{cell(i % 4 + 1, i // 4 + 1)}:{tiles.get(cell(i % 4 + 1, i // 4 + 1))}!={v}" for i, v in enumerate(grid) if tiles.get(cell(i % 4 + 1, i // 4 + 1)) != v]
    over = scr.get("over")
    out["status"] = [] if (over == "over") == bool(tr.get("over")) else [f"over={over} truth={tr.get('over')}"]
    return out


def check_snake(scr, tr):
    out = {}
    snake = tr.get("snake") or []
    if snake:
        hx, hy = snake[0]
        want = cell(hx + 1, hy + 1)
        out["head"] = [] if scr.get("head") == want else [f"{scr.get('head')}!={want}"]
    f = tr.get("food")
    if f:
        want = cell(f[0] + 1, f[1] + 1)
        out["food"] = [] if scr.get("food") == want else [f"{scr.get('food')}!={want}"]
    dead = scr.get("status") == "dead"
    out["status"] = [] if dead == bool(tr.get("over")) else [f"status={scr.get('status')} over={tr.get('over')}"]
    return out


def check_tetris(scr, tr):
    out = {}
    board, rows = scr.get("board"), tr.get("grid")
    if board and rows:
        # the page joins each row's cells with "", so empties vanish: compare filled cells per row (settled stack only)
        cur = tr.get("cur")
        bad = []
        for y, row in enumerate(rows):
            got = sum(1 for x in range(10) if at(board, x + 1, y + 1) not in (".", None))
            if got != len(row):
                bad.append(f"r{y + 1}:{got}!={len(row)}")
        out["stack_rows"] = bad if cur is None else [b for b in bad if int(b.split(":")[0][1:]) > 4]   # the falling piece adds cells near the top
    piece = scr.get("piece") or {}
    if piece.get("phase") == "spawned" and tr.get("cur"):
        out["piece"] = [] if piece.get("shape") == tr["cur"].get("s") else [f"{piece.get('shape')}!={tr['cur'].get('s')}"]
    if piece.get("next") and tr.get("next"):
        out["next"] = [] if piece.get("next") == tr["next"] else [f"{piece.get('next')}!={tr['next']}"]
    over = scr.get("status") == "over"
    out["status"] = [] if over == bool(tr.get("over")) else [f"status={scr.get('status')} over={tr.get('over')}"]
    return out


def check_go(scr, tr):
    """Board and status against the page; the compiled go read (legal points, stones in atari) against the page's own
    rules engine. A legal point the page refuses is a ko (the compiler is stateless and cannot see one): counted apart."""
    out = {}
    board, grid = scr.get("board"), tr.get("grid")
    if board and grid:
        sym = {0: ".", 1: "B", 2: "W"}
        out["board"] = [f"{cell(i % 9 + 1, i // 9 + 1)}:{at(board, i % 9 + 1, i // 9 + 1)}!={sym.get(v)}" for i, v in enumerate(grid) if at(board, i % 9 + 1, i // 9 + 1) != sym.get(v)]
    want = {0: None, 1: "we_won", 2: "we_lost"}.get(tr.get("over"))
    st = scr.get("status")
    out["status"] = ([] if st == want else [f"{st}!={want}"]) if want else ([f"{st} while playing"] if st in ("we_won", "we_lost") else [])
    g = scr.get("go")
    if isinstance(g, dict) and "legal_black" in tr and not out.get("board"):
        page = {cell(i % 9 + 1, i // 9 + 1) for i in tr["legal_black"]}
        ours = set(g.get("legal") or [])
        extra = ours - page
        out["legal"] = sorted(page - ours) + ([] if len(extra) <= 1 else sorted(extra))   # one extra point is a ko
        out["ko"] = sorted(extra) if len(extra) == 1 else []
        for side, key in (("black", "our_atari"), ("white", "their_atari")):
            want_a = {cell(i % 9 + 1, i // 9 + 1) for i in tr.get("atari", {}).get(side, [])}
            got = set(g.get(key) or [])
            out[key] = sorted(want_a ^ got)
    return out


CHECKS = {"go": check_go, "connect4": check_connect4, "2048": check_2048, "snake": check_snake, "tetris": check_tetris}


def check_log(path: str, settled: bool) -> dict:
    game = Path(path).name.split("-")[0]
    fn = CHECKS.get(game)
    recs = [json.loads(l) for l in open(path) if l.strip()]
    recs = [r for r in recs if r.get("truth") is not None and r.get("screen")]
    res: dict = {"log": Path(path).name, "game": game, "ticks": len(recs), "fields": {}}
    if fn is None:
        res["error"] = "no checker"
        return res
    for i, r in enumerate(recs):
        if settled and (i == 0 or recs[i - 1]["truth"] != r["truth"]):
            continue
        for field, bad in fn(r["screen"], r["truth"]).items():
            f = res["fields"].setdefault(field, {"checked": 0, "wrong": 0, "examples": []})
            f["checked"] += 1
            if bad:
                f["wrong"] += 1
                if len(f["examples"]) < 3:
                    f["examples"].append({"tick": r["tick"], "bad": bad[:4]})
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--settled", action="store_true", help="only ticks where the page state had not changed since the previous tick")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    out = [check_log(p, a.settled) for p in a.logs]
    if a.json:
        print(json.dumps(out, indent=1))
        return
    for r in out:
        parts = [f"{k} {v['wrong']}/{v['checked']} wrong" for k, v in r["fields"].items()]
        print(f"{r['log']}: {r['ticks']} ticks; " + ("; ".join(parts) or r.get("error", "nothing checked")))
        for k, v in r["fields"].items():
            for e in v["examples"]:
                print(f"    {k} tick {e['tick']}: {e['bad']}")


if __name__ == "__main__":
    sys.exit(main())
