# anygame with real Jev: 32 episodes on four games (2026-10-02)

Branch `claude/anygame-jev-scale-run-dubj38` (built on `claude/anygame-scale-run`), not merged, no PR.
Decider: Jev (`typesafe/jev-1.13` on OpenRouter). Same harness, games, seeds 1–8 and caps as the offline run
(Snake 400 ticks at 700 ms per step, Connect Four 60, 2048 300, Tetris 400 at level 5).
Jev call latency: median about 390 ms; action lands 500–750 ms after the frame. 5 of about 1,800 calls timed out (all Snake, none fatal).

**Total Jev cost: $0.20 for 32 episodes** (2048 $0.08, Tetris $0.08, Snake $0.04, Connect Four $0.006).

## Per game, 8 seeds each

| game | Jev | CLM stand-in (offline) | random (offline) |
|---|---|---|---|
| Connect Four | **won 8 of 8** | won 5, draw 2, lost 1 | won 2, lost 6 |
| Snake | length median 8.5, max 22; dead 7, alive at cap 1 | length 3 (never ate), alive 8 | length median 3, alive 7 |
| 2048 | best tile median 128, max 256; **score median 2104** | best 128 / 256, score 1224 | best 96 / 256, score 898 |
| Tetris | lines median 46.5, max 156; over 7 of 8 | lines median 156, alive 6 | over 8, lines max 2 |

Perception graded against the game's own state on settled ticks: 0 wrong.

## Top failure causes

1. **Snake: the second of two quick turns arrives late.** All 7 deaths end the same way: the snake turns, then needs
   another turn on the next step (wall or own body ahead), and Jev's move lands 530–930 ms after the frame, after the
   700 ms step has already moved the snake. Control test: the stand-in, slowed to Jev's pace
   (`CLM_STUB_DELAY_MS`), died in 4 of 4 by tick 31, where at full speed it lived 8 of 8. Jev eats, which the stand-in
   never does, but chasing food into tight corners at this latency is what kills it.
2. **Tetris: Jev skips the compiler's best landing about 1 time in 10.** It takes landing `a` on 88–94% of pieces; the
   rest stack holes and end the game. Latency is not the cause: the stand-in slowed to Jev's pace still cleared a median
   123 lines and was alive at the cap in 2 of 3.
3. **2048: no cliff, just a ceiling.** Jev's score beats both baselines (2104 vs 1224 vs 898), but best tile stays at
   128–256 like the others.
4. **Connect Four: none.** With wins and blocks from the compiler, Jev won every game in about 32 ticks.

## Rerun
```bash
cd anygame && pip install -e ".[stream]"
OPENROUTER_API_KEY=placeholder scripts/scale_run.sh runs/jev jev 1,2,3,4,5,6,7,8
python scripts/tally_run.py runs/jev; python scripts/check_truth.py --settled runs/jev/logs/*.jsonl
```
