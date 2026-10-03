# Go: re-rank moves by playout win rate (2026-10-03)

Follows [go-playouts.md](go-playouts.md) and the learn loop's Go discovery test (learn-loop-v2.md). In 4 of 7
diagnosed losses Jev passed up a move the playouts rated far higher and took the `worth` top instead, against the
pack paragraph. A pack rule can't fix that, because rules only compare reads to constants. So the compiler now
applies the rule itself.

## Result

With the compiler taking its own top pick, 16 seeds against the fixed white (`go.html?ai=mc&playouts=400`), run
the same day on the same machine:

| Decider | Pack | Won | Lost | Mean final lead | Median |
|---|---|---|---|---|---|
| stand-in (top pick) | v6, `best` in `worth` order | 3 | 13 | −8.1 | −6.5 |
| **stand-in (top pick)** | **v7, `rerank: playouts`** | **14** | **2** | **+29.8** | **+15.5** |
| Jev (earlier, round four) | v6 | 9 | 7 | +17.0 | +10.5 |

- **Re-ranking alone wins 14 of 16, against 3 of 16 without it.** The one-sided Fisher p is 0.0001. It also beats
  Jev's 9 of 16 on the old pack (p ≈ 0.06; that run was on an earlier day, but white plays a fixed playout count, so
  it is comparable).
- In 5 of the 16 games white was wiped off the board (+74.5 or +54.5). The two losses were by 1.5 and 5.5.
- The leader replaced the `worth` top on 239 of the 819 moves the stand-in played (29%). The rest were the `worth`
  top, or a capture or save that the pack's priority rule forces.
- The no-re-rank stand-in (3/16, mean −8.1) matches Jev on the v3 pack with no playouts (3/16, mean −6.5). That
  pack's Jev also took the `worth` top every time, so the stand-in baseline is a fair stand-in for "follows `worth`".

Per-game final leads (seeds 1 to 16):
- baseline: −37.5 −3.5 −11.5 +0.5 +6.5 −11.5 −17.5 −5.5 −3.5 −1.5 −11.5 −3.5 +28.5 −43.5 −7.5 −7.5
- re-rank: +8.5 −1.5 +12.5 −5.5 +8.5 +74.5 +6.5 +18.5 +54.5 +48.5 +74.5 +4.5 +4.5 +18.5 +74.5 +74.5

**Jev with the re-rank has not been run.** The OpenRouter account is still out of credit: `/api/v1/credits` reports
5.20 used of 5, checked once after the stand-in runs. The Jev comparison (16 seeds, same white, against 9/16) waits
on credit. With this pack Jev is likely to take the first `best` move nearly every time, as on Tetris and 2048. So
Go would then measure the compiler more than Jev.

## What changed

- `go` read: `rerank: playouts` (with `playouts:`) and `rerank_margin` (default 0.06, from round four's recheck,
  where a gap below 0.06 was a coin flip and one at or above it was better 116 times, worse 12). The leader is chosen
  among the `good` moves with the most games played (the `playouts_top` leaders at 160 games). A lucky 32-game result
  never jumps the queue, and an own eye or self-atari never leads. When the leader's `win` beats the `worth` top's by
  the margin or more, it goes first in `best`, and `reranked: {from, to, gap}` says so. Python only: the extension's
  TypeScript `go` read has no playouts yet.
- `packs/go` turns it on. Its paragraph now says `best` already applies the rule, and to play the first `best` move.
  Playout counts are unchanged (32 each, top 3 to 160).
- `test/clm_stub.py` takes `CLM_STUB_RANK=<dotted path>`, for example `screen.go.best`, to take the first offered
  criterion in that list. Without it the stand-in did not take the top pick on Go. Grid options are offered in board
  order, so "the first criterion that appears in the state" meant the top-left cell of `best` (5 of 40 moves were
  the `worth` top in a probe game). With it, every non-forced, non-refused move is `best[0]`.
- Tests cover the margin, the 160-game filter, non-`good` moves, the opt-in on `go.read`, the pack setting and the
  stub's ranked pick.

## Reproduce

```
CLM_STUB_RANK=screen.go.best python3 test/clm_stub.py 8731 &
ANYGAME_PACKS=<dir holding the go pack> anygame bench go \
  --device "web://games/go.html?seed={seed}&ai=mc&playouts=400#state=window.__state()" \
  --sensor clm:http://127.0.0.1:8731 --seeds 1,2,...,16 --max-ticks 900 --out <dir>/logs
python3 tally.py <dir>
```

The baseline is the same pack without the two `rerank` lines. Logs, `out.json` and `tally.py` are in
`/mnt/project-files/anygame/go-playout-rerank/` (`stand-in-baseline/`, `stand-in-rerank/`).
