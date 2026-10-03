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
| v3: plus ladder reading | Jev | 8 | 0 | $0.036 |
| v3 | random | 5 | 3 | $0 |

v1 losses: three games ended 0 to 87.5. Jev drew lines through its own area (c5r1..c5r9, then row 1) instead of
claiming space, and white captured 54 to 62 stones. v2 wins by 2.5 to 74.5 points; its two losses (seeds 5 and 7)
are chains left on two liberties that white chased down (13 and 15 stones captured).

A run of v2 before the loop fix stalled two Jev games and three random ones at the tick cap: a ko recapture looks
legal to the stateless compiler, the page refuses it, and the loop kept offering the same point. The loop removed a
refused tap only from questions that existed before it built the grid-cell question, so a tap on an auto-generated
cell question was never dropped. Fixed in `loop.py` and `ext/src/core/loop.ts` (this would also have hit a full
Connect Four column); the v2 numbers above are after the fix.

v3 reads ataris to the end (ladders and short chases, up to 12 moves): `danger` lists our chains white can chase
down if it moves first, a move whose chain white could then chase down is `doomed` and rated far down, a move that
gets a danger chain away earns its stones, and an atari white cannot escape counts double. Jev won all 8, four of
them by wiping white off the board (81 to 6.5); white captured at most 3 stones in any game. Perception stayed at
0 wrong reads on 852 acting ticks; the whole read, ladders included, takes 51 ms median per tick (77 ms p95).

## A stronger white (`?ai=mc`)

The page now takes `ai=mc`: the old heuristic still plays a capture or a save outright; otherwise its top 12
candidates each get quick random playouts to the end of the game, round robin for `think` ms (default 500, about
300 playouts a move), and white plays the best win rate. No dependencies; a game takes 36 to 73 s.

| Decider (pack v3) | vs old white | vs playout white |
|---|---|---|
| Jev | 8 won, 0 lost | 5 won, 3 lost ($0.031) |
| random, same rules | 5 won, 3 lost | 2 won, 6 lost |

Perception stayed at 0 wrong reads on 805 acting ticks. Jev's three losses were by 3.5 to 11.5 points (white
captured 4 to 16 stones), against wins by up to 74.5. The old heuristic stays the default so the earlier numbers
remain reproducible.

## Perception

0 wrong reads on the 1,674 ticks where the agent acted, across 32 games. The board read differs from the page's
state on 508 other ticks, all white's reply landing between the frame grab and the state read (a white stone
missing, plus the stones it captured), never on a tick the agent acted. The compiled legal points and chains in
atari match the page's own rules engine on every tick (0 of 2,666 wrong); 14 ticks showed one extra legal point,
each a ko the page refuses.

Jev latency: median 336 ms, p95 608 ms per call (394 calls in v2). About 46 decisions per game.

## What would move it next

- Done in v3: ladder reading. Done: a playout opponent (`ai=mc`).
- Tried and dropped: replacing the nearest-stone area count in `worth` with an influence map (Bouzy dilation and
  erosion, 5/10, so walls block influence). Against the playout white it made things worse: Jev 2 won, 6 lost
  (was 5/3), black's mean score 39 (was 51), $0.031; random under the same rules 1/7 (was 2/6) though its mean
  score rose from 32 to 38. Its early-game counts are small and flat, so the ranking leans on tactics and loses
  the opening. Not kept.
- Next, if Go work resumes: give Jev the playout result for its top moves (the same playouts white uses), or
  blend the two estimates (distance early, influence once the board fills).
- The first-run lesson matches Tetris: Jev chooses well among a short ranked list and poorly among 60 flat options.

Reproduce: `ANYGAME_LOG_TRUTH=1 anygame bench go --device "web://games/go.html?seed={seed}#state=window.__state()"
--sensor jev --seeds 1,2,3,4,5,6,7,8 --max-ticks 900 --out <dir>/logs`, then `scripts/check_truth.py <dir>/logs/*.jsonl`.
