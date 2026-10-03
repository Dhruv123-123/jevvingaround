# Go rounds two to four: playout results for Jev's candidate moves (2026-10-03)

## Round four: follow the playout leader past a 0.06 gap (the current pack)

Only the pack paragraph changed: when the move with the highest `win` beats the first `best` move's `win` by 0.06 or
more, play it even if its `worth` is lower; below 0.06, keep the first `best` move. The 0.06 comes from rechecking all
432 round-three positions where the two tops differed with 512 playouts each:

| In-game win gap (leader minus `worth` top) | Positions | Leader better | Leader worse |
|---|---|---|---|
| under 0.03 | 124 | 14 | 10 |
| 0.03 to 0.06 | 77 | 25 | 11 |
| 0.06 to 0.10 | 109 | 43 | 6 |
| 0.10 to 0.15 | 51 | 20 | 2 |
| 0.15 and up | 71 | 53 | 4 |

Below 0.06 the leader is close to a coin flip; from 0.06 it was better 116 times and worse 12. How far the leader
trailed on `worth` made no difference.

Same 16 seeds, same fixed white (`ai=mc&playouts=400`):

| Pack | Won | Lost | Mean final lead | Median | Cost |
|---|---|---|---|---|---|
| v3, no playouts | 3 | 13 | −6.5 | −5.5 | $0.064 |
| v5, focused playouts | 8 | 8 | +12.5 | +0.5 | $0.077 |
| **v6, follow the leader past 0.06** | **9** | **7** | **+17.0** | **+10.5** | $0.078 |

Jev now follows the rule more often: where the gap was 0.06 or more, it played the leader 132 of 234 times (v5:
78 of 231), and it took the `worth` top 454 of 628 free choices (v5: 517). It is still not mechanical: 102 times it
kept a lower-`win` move past the gap. One more win than v5 is within noise; the median lead moved most (+0.5 to
+10.5). Kept, since it did not do worse. Logs: `/mnt/project-files/anygame/go-run-logs/v6-follow-leader/`.

## Round three: a fixed white and focused playouts

- White can now play a fixed number of playouts a move (`go.html?ai=mc&playouts=400`) instead of 500 ms of
  thinking, so it plays the same on any machine and the same seed replays the same game for the same black moves.
  400 is what 500 ms buys on this machine (measured 366 to 431 a move); yesterday's ~300 was a weaker white.
- Playouts are concentrated: every candidate gets 32 games, the three leaders by that first pass go on to 160
  (`playouts: 32, playouts_top: 3, playouts_top_n: 160`), and each result carries `n`. The pack says a 0.06 gap
  between two 160-game moves is real. About 370 ms per new board: perception on Jev's turns went from 427 ms to 718 ms p50 (Go has no clock).
  Jev's own latency 329 ms p50.

16 seeds, `web://games/go.html?seed={seed}&ai=mc&playouts=400`:

| Pack | Decider | Won | Lost | Mean final lead | Median | Cost |
|---|---|---|---|---|---|---|
| v3 (no playouts) | Jev | 3 | 13 | −6.5 | −5.5 | $0.064 |
| **v5 (focused playouts)** | **Jev** | **8** | **8** | **+12.5** | **+0.5** | $0.077 |
| v5 | random | 0 | 16 | −17.5 | −13.5 | $0 |

8 of 16 against 3 of 16 is the first Go result here that 16 games can call (one-sided Fisher p ≈ 0.07), and the mean
lead moved by 19 points. Random under the same rules still loses every game, so the compiler alone does not win.

Jev vs the rankings (`scripts/go_agree.py`, 512-playout recheck): v3 took the `worth` top on 603 of 606 free choices.
v5 left it on 111 of 628 (18%), 104 of those for the playout top. Of the 111: **64 better, 5 worse, 42 even**
(mean +0.04 win rate). Its clearest calls passed up a `worth` 1 to 6 points higher for a much better win rate: seed
1 tick 61 (0.94 vs 0.73), seed 3 tick 49 (0.89 vs 0.69), seeds 2 and 12 (+0.16 each). The worst was seed 10 tick 7
(0.43 vs 0.50). It still stays with `worth` more than the playouts justify: where the two tops differ (432), the
playout top was better 155 times, worse 33.

Logs: `/mnt/project-files/anygame/go-run-logs/v5-fixed-white/` (v3-baseline, v5-focused, random, jev-vs-rankings.txt).

## Round two: 64 playouts for every candidate (time-bounded white)

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
