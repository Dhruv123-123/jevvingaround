# Snake: turning at Jev's pace (2026-10-02)

Branch `claude/anygame-snake-double-turn-avcj32` (built on `claude/anygame-jev-scale-run-dubj38`), not merged, no PR.
Same harness, seeds 1–8, 400-tick cap and 700 ms game step as [scale-run-jev.md](scale-run-jev.md).

## The problem

In the baseline, 7 of 8 Jev games ended the same way: the snake turned beside a wall or its body and needed another
turn on the very next step. The loop asks Jev and waits for the answer, and sees no frame while it waits. With one
free cell ahead, the answer (median 400 ms, landing 500–900 ms after the frame) arrives after the next 700 ms step,
and the step after that kills the snake.

## The fix: `reflex`

A pack can now name a condition under which the loop does not wait on the decider:

```yaml
reflex: { read: head_around.ahead_free, lte: 1 }
```

When it holds on a fresh frame, the pack's rules act on Jev's last answers at once (its ranking of up, down, left,
right and keep). The rules already exclude the deadly moves, so the best remaining move by Jev's own probabilities
goes out about 125 ms after the frame (max 220 ms) instead of about 460 ms. Jev is asked again on the next frame that
has room. The record says `skipped: reflex`. It is the same replay the `budget_ms` skip and the sensor-error fallback
already use, triggered by the game state instead of a timer. Code: `Agent.step` in `anygame/loop.py`; validated in
`anygame/pack.py`; test `test_reflex_acts_on_the_last_answers_when_a_fresh_answer_would_land_too_late`.

A first try with the reflex only when the cell ahead was already fatal (`ahead` in s, wall) did not help: the loop
was still blocked on the previous call when that frame arrived.

## Results, 8 seeds each

| | dead | length median (max) | score median | Jev cost |
|---|---|---|---|---|
| Stand-in at Jev's pace (700 ms), no reflex | **8 of 8**, by tick 8–63 | 3 | 0 | – |
| Stand-in at Jev's pace, reflex | **0 of 8**, all alive at the cap | 3 | 0 | – |
| Jev, baseline (scale-run-jev.md) | **7 of 8** | 8.5 (22) | 55 | $0.034 |
| Jev, reflex | **1 of 8** | 16 (19) | 130 | $0.051 |

The stand-in never eats (it is a fixed heuristic), so it only shows that the deaths were latency. Jev with the
reflex ate on every seed and 7 of 8 games reached the 400-tick cap. Cost went up only because games ran longer
(about $0.0065 per 400-tick game); the reflex itself makes no call. The reflex acted 20–39 times per game.
Perception: 0 wrong reads on settled ticks.

## What is left

1. **Seed 8 died on a slow call.** One Jev call took 1.1 s, so two game steps passed while the loop waited; the reflex
   fired 100 ms after the next frame but the snake was already a step from the wall. A per-call timeout under one
   step, or a loop that keeps reading frames while the call is in flight, would cover this.
2. **Food in a corner is never eaten.** The pack's "turn a cell early" rule excludes going straight when one cell is
   left, even when that cell is the food in the corner. Seed 8 circled such food for most of its 331 ticks (length 4).
   A rule change in the pack, not the loop.
3. Scores are bounded by the 400-tick cap, not by deaths, so a longer cap is the next comparison.

## Rerun
```bash
cd anygame && pip install -e ".[stream]"
ANYGAME_LOG_TRUTH=1 OPENROUTER_API_KEY=placeholder anygame bench snake \
  --device "web://games/snake.html?seed={seed}&tick=700#state=window.__state()" --sensor jev \
  --seeds 1,2,3,4,5,6,7,8 --max-ticks 400 --out runs/snake-reflex/logs
# stand-in at Jev's pace: CLM_STUB_DELAY_MS=700 python3 test/clm_stub.py 8711 & then --sensor clm:http://127.0.0.1:8711
```
