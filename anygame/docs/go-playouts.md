# Go round two: playout results for Jev's candidate moves (2026-10-03)

Branch `claude/anygame-go-playouts` (on `claude/anygame-go-554rhu`). Follows [go-run-jev.md](go-run-jev.md).

## What changed

- The `go` read takes `playouts: n`. Each `best` move, capture and save is played out n times to the end by random
  moves on both sides (never filling an own eye, never suicide: the same policy as the page's `?ai=mc` white), and
  gets `playouts: {cell: {win, margin}}`: black's win rate and mean final lead after komi. Seeded from the board and
  cached per board, so an unchanged board reads the same and costs nothing.
- `packs/go` sets `playouts: 64` and tells Jev to weigh `win`/`margin` against `worth`: a clearly higher win rate
  (0.1+) or margin (5+) is the better move unless its `worth` is far lower. `best` is still ordered by `worth`; the
  pack does not re-rank by playouts, so Jev chooses.
- Budget: 64 playouts per candidate, about 6 candidates, 250 ms p50 / 270 ms p95 per new board in Python (0.5 ms per
  playout). 100 per candidate would be 380 ms. Jev's turn went from ~0.8 s to ~1.1 s from frame to tap; Go has no
  clock, and white thinks 500 ms. Jev latency unchanged (331 ms p50).
- `scripts/go_agree.py <logs>` checks each of Jev's picks against both rankings with 512 playouts per move.
- The extension's TypeScript `go` read does not do playouts yet.

## Results (8 seeds, `?ai=mc` white, 900-tick cap)

| Run | Won | Lost | Mean final lead | Cost |
|---|---|---|---|---|
| v3 (yesterday's report) | 5 | 3 | +14.5 | $0.031 |
| v3 rerun today, same pack, same machine as v4 | 2 | 6 | −2.8 | $0.029 |
| **v4: v3 plus playouts, Jev** | **3** | **5** | **+12.8** | $0.039 |
| v4, random decider under the same rules | 0 | 8 | −19.5 | $0 |

The playout white got stronger on today's machine (its think time is wall-clock, so a faster box gives it more
playouts): the same v3 pack fell from 5/8 to 2/8 and random from 2/8 to 0/8. Against that like-for-like baseline,
playouts are +1 win and +15.6 points of mean lead. Two v4 wins wiped white off the board (81 to 6.5); v4's losses ran
1.5 to 31.5 points. With 8 games this is a lean, not a proven gain.

Perception: 0 read errors reported by the sensor; Jev 331 ms p50.

## Did Jev disagree with the rankings, and was it right?

319 free choices (no capture or save forced) across the 8 v4 games:

- **v3: Jev took the `worth` top on 298 of 298 free choices.** It was rubber-stamping, as on Tetris and 2048.
- **v4: Jev took the `worth` top 285 times (89%) and left it 34 times; 33 of those went to the playout top.** 8 of
  the 34 were the same opening move (c6r4 over c4r4, equal `worth`, 0.61 vs 0.45 at 64 playouts).
- Rechecked with 512 playouts per move: of Jev's 34 departures, **13 were better (by more than 0.03 win rate), 1
  worse, 20 even**; mean +0.03. Its best calls were mid-game, where the playout top was worth 2 to 3 points less
  but won more: seed 3 tick 41 (c4r7 over c9r2, 0.72 vs 0.52), seed 1 tick 39 (+0.10), seed 1 tick 80 (+0.09),
  seed 5 tick 29 (+0.09). The one bad departure was seed 5 tick 5 (0.49 vs 0.53).
- Jev was cautious: where the two rankings differed (227 times) it stayed with `worth` most of the time, and on
  those, the 64-playout top would have been better 69 times, worse 31, even 127 (mean +0.011). So Jev left `worth`
  less often than the playouts would justify, but almost never wrongly. Games with more departures were wins
  (seeds 1, 3, 6); the losses (2, 4, 7) had only the opening departure, so the departures did not cause losses.
- 64 playouts are noisy (±6% win rate) and candidates often sit within a few percent, so many "playout top" picks
  are ties at 512.

## What would move it next

- Bigger playout budget where it matters: more playouts only for the top 2 or 3 candidates (or across processes),
  so the win rates separate.
- Make the pack's threshold match what the recheck showed: Jev could follow a 0.1 win-rate gap more often.
- White's strength depends on CPU; for comparable numbers across machines, white should play a fixed number of
  playouts rather than a time budget.

Logs: `/mnt/project-files/anygame/go-run-logs/v4-playouts/` (jev, random, v3-rerun-same-day, jev-vs-rankings.txt).
Reproduce: `OPENROUTER_API_KEY=… ANYGAME_LOG_TRUTH=1 anygame bench go --device
"web://games/go.html?seed={seed}&ai=mc#state=window.__state()" --sensor jev --seeds 1,2,3,4,5,6,7,8 --max-ticks 900
--out <dir>/logs`, then `scripts/go_agree.py <dir>/logs`.
