# Integration branch: every finished anygame branch stacked on one base

Branch `claude/anygame-integration`, built 2026-10-03. Merge commits only, no rebases, no force-pushes. No model calls
were made (offline deciders only).

## Merge order and conflicts

Base: `claude/anygame-jev-scale-run-dubj38` (which already contains `scale-run`).

| # | Branch | Conflicts | Resolution |
|---|---|---|---|
| 1 | snake-double-turn-avcj32 | none | |
| 2 | tetris-landing-3xsdkp | none | |
| 3 | go-554rhu | none | |
| 4 | 2048-lookahead | `pack.py`, `ext/src/core/pack.ts`, `ext/src/core/reads.ts`, `ext/test/eval.test.mjs`, `test/test_anygame.py` | Additive: the read-kind lists keep both `go` and `slide`; the extension's `readAll` keeps the `go` case and skips `slide` with the other loop-derived reads; both sides' tests kept |
| 5 | fix-ci-i0vuxg (PR #1) | none | |
| 6 | remove-sonnet-fallback-liqdl6 | none | |
| 7 | task-setter-limits-rahuj9 | none | |
| 8 | author-real-games-qzqqin (PR #2, contains real-web-trial-7zpmin) | `pack.py`, `perceive/__init__.py`, `ext/src/core/pack.ts`, `ext/src/core/reads.ts`, `ext/test/eval.test.mjs` | Additive: read kinds `go`, `slide`, `head` all kept (Python and TS); the extension test imports both `goRead` and `isHollow` |
| 9 | plausible-reads | `pack.py` | Additive: `MODE_KEYS` keeps `reflex` and `plausible`; `load_pack` keeps the rule shape checks and runs the plausible spec check after the rule loop |
| 10 | go-playouts (merged again for rounds three and four, no conflicts) | `test/test_anygame.py` | Both tests kept |
| 11 | dino-reflex (merged again for the 30 fps round, no conflicts) | `pack.py`, `perceive/__init__.py` | Additive: read kinds add `gap`; `MODE_KEYS` keeps `reflex`, `plausible`, `ask`, `ask_when` |
| 12 | dino-framerate-wtqykg (PR #7) | none | |

No conflict needed one side's behaviour dropped. The auto-merged question builder was checked by hand: 2048's
`criteria_from` replaces options first, Go's refused-move filter runs after the parameter questions are built, and
snake's `reflex` branch and the budget skip sit side by side, in both `loop.py` and `loop.ts`.

The dino branch's `web-dino` pack did not load in the extension; its own branch fails the extension test the same way.
The merge commit adds the smallest port that loads and runs it: the TS runtime accepts a `gap` read (null there,
like OCR) and runs rules like the Python loop (an `if` list must all hold, `unless` cancels a rule, `contains` matches
an item of a list or comma-joined read), with a test. The async ask, the frame-timed jump and key holds are still
CLI-only; that is the extension-parity thread's work.

## Tests (final head)

- Python: 86 passed, 1 failed. The failure is `test_nested_display_runs_the_game_in_a_sandbox_the_runtime_owns`, which
  fails the same way on the base branch: this container has no X display for pynput. It needs the `desktop` extra and an X
  server, which CI provides.
- Extension: `tsc --noEmit` clean, `npm test` 42/42.
- Pack evals: all 15 bundled packs pass, including 2048 and 2048gb, which failed on every branch before PR #1's
  OCR wait fix came in.

## Offline smoke check

`anygame bench` on the bundled pages, random and the CLM stand-in, no Jev. Run A after the first four merges (3 seeds),
run B after all older branches (2 seeds), run C for Go after go-playouts (2 seeds).

| Game | Decider | A | B |
|---|---|---|---|
| Connect Four | stand-in | won 2, cap 1 | won 2 |
| Connect Four | random | lost 2, won 1 | lost 2 |
| Snake (400 ticks) | stand-in | alive 3/3, length 3 | alive 2/2, length 3 |
| Snake | random | alive 3/3 | alive 2/2 |
| Tetris (400 ticks) | stand-in | alive 3/3, lines median 158 | alive 2/2, lines 158.5 |
| Tetris | random | over 3/3 | over 2/2 |
| 2048 (300 ticks) | stand-in | alive 3/3, 512 tile, score 4596 | alive 2/2, 512, 4628 |
| 2048 | random | over 3/3, score 624 | over 2/2, 532 |
| Go | stand-in | won 2, lost 1 | won 1, lost 1 |
| Go | random | won 3 | won 2 |

Run C (Go, playouts on): random won 2/2, stand-in won 1 lost 1, 0 errors.

All match the earlier single-branch runs (stand-in Snake never eats, as in the offline scale run; Tetris and 2048 match
the lookahead reports). Perception against the page's own state, settled ticks: 0 wrong on Connect Four, Snake and
2048. Tetris had 15 settled mismatches, all in one random episode with the stack at the ceiling: the checker skips rows
1 to 4 for the falling piece, and there the piece sat on row 5. No Tetris read code changed in the merge.

## Supersedes

This branch contains PR #1 (CI fix) and PR #2 (real-game packs) in full, plus every other finished branch, so merging
it lands all of them.
