# Go with real Jev (2026-10-02)

anygame now plays Go on a 9x9 board: `games/go.html`, `packs/go`, and a `go` compiler read (Python and the extension).

## Setup

- Page: we are black and move first; the page plays white. Area scoring, komi 6.5, positional superko, ends after
  two passes in a row (or 180 moves). White's heuristic: capture the biggest chain it can, else save its own chain
  in atari, else a random move that neither fills its own eye nor puts itself in atari, mildly preferring points
  next to stones. `window.__state()` exposes the board, black's legal points and the stones in atari, so the
  compiled read is graded against the page's own rules, not against a copy of the compiler.
- Pack: the board is a 9x9 colour read; `go` (kind: go) computes legal points, good points (not our own eye, not
  self-atari), captures, saves, chains in atari, an exact area score, and (second version) `best`: the top 6 moves
  by a one-move rating (rough area swing, stones saved or put in atari, minus a chain left on two liberties).
  Rules offer only good points; a capture or save if there is one; else only `best`. Pass only when no good point.
- 8 seeds per row, Jev = typesafe/jev-1.13 via OpenRouter. "Random" is the random decider under the same pack
  rules, so it is the compiler with no judgment.

## Results

| Pack version | Decider | Won | Lost | Cost |
|---|---|---|---|---|
| v1: good points, captures/saves forced | Jev | 2 | 6 | $0.036 |
| v1 | random | 2 | 6 | $0 |
| v2: plus top-6 ranked moves | Jev | 6 | 2 | $0.029 |
| v2 | random | 3 | 5 | $0 |

v1 losses: three games ended 0 to 87.5. Jev drew lines through its own area (c5r1..c5r9, then row 1) instead of
claiming space, and white captured 54 to 62 stones. v2 wins by 2.5 to 74.5 points; its two losses (seeds 5 and 7)
are chains left on two liberties that white chased down (13 and 15 stones captured).

A run of v2 before the loop fix stalled two Jev games and three random ones at the tick cap: a ko recapture looks
legal to the stateless compiler, the page refuses it, and the loop kept offering the same point. The loop removed a
refused tap only from questions that existed before it built the grid-cell question, so a tap on an auto-generated
cell question was never dropped. Fixed in `loop.py` and `ext/src/core/loop.ts` (this would also have hit a full
Connect Four column); the v2 numbers above are after the fix.

## Perception

0 wrong reads on the 1,674 ticks where the agent acted, across 32 games. The board read differs from the page's
state on 508 other ticks, all white's reply landing between the frame grab and the state read (a white stone
missing, plus the stones it captured), never on a tick the agent acted. The compiled legal points and chains in
atari match the page's own rules engine on every tick (0 of 2,666 wrong); 14 ticks showed one extra legal point,
each a ko the page refuses.

Jev latency: median 336 ms, p95 608 ms per call (394 calls in v2). About 46 decisions per game.

## What would move it next

- Two-move reading: the losses are two-liberty chains that a ladder or a net catches. A `danger` list (our chains
  white can atari next move with no escape) and a ladder check in the compiler would remove those.
- A stronger opponent (a few hundred Monte Carlo playouts in the page) to keep the benchmark meaningful once Jev
  wins every game against the heuristic.
- The first-run lesson matches Tetris: Jev chooses well among a short ranked list and poorly among 60 flat options.

Reproduce: `ANYGAME_LOG_TRUTH=1 anygame bench go --device "web://games/go.html?seed={seed}#state=window.__state()"
--sensor jev --seeds 1,2,3,4,5,6,7,8 --max-ticks 900 --out <dir>/logs`, then `scripts/check_truth.py <dir>/logs/*.jsonl`.
