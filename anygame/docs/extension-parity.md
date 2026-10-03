# Extension parity with the CLI

Branch `claude/anygame-extension-parity-nknhcy`, PR #4 (https://github.com/Dhruv123-123/jevvingaround/pull/4), based on
`claude/anygame-integration` (PR #3), merged up to the Go round four commits. CI green.

## Gaps found and how each was verified

| Feature (Python CLI) | Extension before | Now | Verified by |
|---|---|---|---|
| `reflex:` pack line (rules act on Jev's last answers when the reflex fires) | ignored | `loop.ts` | unit tests mirroring the Python ones; snake e2e below |
| rule `unless:` / `if:` lists | done by integration | kept integration's version | existing + new tests |
| rule shape checks (`set`/`avoid`/`only` are maps) | none | `pack.ts` | loader tests |
| take the one action the rules leave, even if Jev never offered it | missing | `loop.ts` | unit test |
| `plausible:` checks (sticky, max_changes, count/diff, require/when/line), re-read twice, stop after 6 bad ticks | missing (whole module) | new `plausible.ts` | tests mirroring `test_plausible.py` with the same messages; it caught a real misread in CI (below) |
| Tetris `lookahead: true` (rank each landing after the preview piece too) | one piece deep | `tetris.ts` | same ranking as `perceive/tetris.py` on 60 random boards (lookahead reorders 43 of them); Tetris e2e |
| Go `playouts: n` win rate and margin per candidate | missing | `go.ts`, seeded and cached per board | same candidates and worth as Python on 12 real boards; win rates within sampling error (mean gap 0.022 at 512 games, no bias) |
| Go `playouts_top` / `playouts_top_n` (round three: 32 games each, top 3 to 160) | missing | `go.ts` | test mirroring the Python one; ~85–180 ms per board (Python ~700 ms); Go e2e |
| 2048 ranked swipes | already ported | unchanged | same as Python on 40 random boards |
| dino: `gap` read | missing | new `gap.ts` | unit test |
| dino: `ask: async` / `ask_when` (Jev asked once per obstacle, loop keeps running) | missing | `loop.ts` | fake-device test: 2 decider calls, 1 async, jump on the frame at ttc ≤ 205 ms |
| dino: `release: later`, `repeat: hold` (key held without freezing the loop) | blocking holds | `loop.ts`, `TabDevice` lets go on the next frame | same test |
| authoring prompt text for `plausible:` | missing | `author.ts` | text matches `author.py` |

Extension tests: 59 pass (41 before), and `tsc` is clean. Python: 81 pass.

## Played in headless Chromium from the extension panel

All runs use `ext/test/e2e_parity.py` on the bundled game pages. Logs are in `/mnt/project-files/anygame/extension-parity/`.

- **Snake**, CLM stand-in slowed to 700 ms, 150-tick cap, 8 seeds.
  - With the reflex: 0 of 8 died. The reflex fired 22–24 times a game and acted ~130 ms after the frame, against ~817 ms for a normal decision.
  - Without the reflex: 8 of 8 died, by tick 8–42. This matches the CLI (7–8 of 8 → 0 of 8).
  - Note: the stand-in only survives. It never ate (length stayed 3).
- **Tetris**, stand-in, 400 ticks, 8 seeds.
  - With lookahead: 0 of 8 over, 158–162 lines.
  - Without lookahead: 2 of 8 over (122 lines each).
  - This matches the CLI.
- **Go**, v6 pack (playouts 32 / top 3 at 160 / 0.06 rule), against the fixed white `go.html?ai=mc&playouts=400`.
  - Real Jev, 8 seeds: **6 of 8 won**, mean lead +12.8, median +8.5, $0.037. Jev played the playout leader in 64 of the 143 moves where it led the first best move by ≥0.06.
  - CLI round four, for comparison: 9 of 16, mean +17.0.
  - Stand-in, 4 seeds: 0 of 4 (it always takes the first best move).
  - Go read: 64–82 ms median per board.
- **Go** with the older 64-playout pack against the time-boxed `?ai=mc` white: Jev won 3 of 8 ($0.036) and the stand-in 0 of 4. On a fast machine the CLI got 2 of 8 against this white, and 5 of 8 on a slow one.

## Found along the way

- **The debugger infobar ("… started debugging this browser") shrinks the tab by ~40 px.** That clipped the bottom board rows of the bundled 540×560 regions, and the new plausible check caught it in CI on tic-tac-toe ("count(X)-count(O) is 1 while status equals our_turn"). The e2e scripts now open a 540×900 window. Real users with a short window could hit the same clipping.
- **Python `go.py` `_playout` can list the same captured chain twice** when two neighbours belong to one chain. A later move can then overwrite a stone. This is rare and was left unfixed in Python. The TS port de-duplicates.
- TS and Python playouts use different random streams, so they agree statistically rather than game for game.

## Still CLI-only

- **Background read pool and the `wait` setting.** The Python loop reads in a background pool; the extension reads in the tab, one frame at a time.
- **Truth logging (`ANYGAME_LOG_TRUTH`)** for grading reads.
- **Probe and authoring changes in `author.py`** beyond the prompt text.
- **The `learn` loop, task setter and rater.** The panel has setter and rater controls, but the rewrite loop runs only from the CLI.
- **The dino 30 fps screen-stream setting (round three),** if it lands. It is not in integration yet.
