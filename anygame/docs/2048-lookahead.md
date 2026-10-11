# 2048: swipes ranked by a lookahead compiler (2026-10-03)

Branch `claude/anygame-2048-lookahead` (on `claude/anygame-jev-scale-run-dubj38`), not merged, no PR.
Same harness, seeds 1–8 and 300-tick cap as the real-Jev scale run.

## What the old logs showed

- 6 of 8 Jev games ended with a full board before the cap (best tile 64–256), so this was strategy, not a ceiling.
- About 30% of Jev's swipes moved nothing (29–96 per game): it kept swiping right into a packed row. The loop's
  no-op filter only drops a swipe after it has been wasted once, and each wasted swipe costs a tick.
- Jev never swiped up and leaned on right (75% of moves). The pack asked it to plan merges itself; nothing ranked
  moves for it. Perception was correct (0 wrong reads), so the board it saw was right.

## The change

- New derived read `kind: slide` (`anygame/perceive/slide.py`, ported to `ext/src/core/slide.ts`): each swipe is
  simulated exactly and ranked by an expectimax search two swipes deep over the random spawn (a 2 nine times in ten,
  else a 4, on any empty cell), scored by a snake of weights anchored at the bottom-right corner plus empty cells.
  ~2 ms per decision. Value: `legal`, `best`, `ranked` (each swipe: rank, points merged, empty cells after, whether
  the largest tile stays in its corner).
- New question key `criteria_from: <read>`: the action's options become that ranked list, so a swipe that would not
  move is never offered and every option carries its consequences.
- Pack paragraph rewritten to say the options are ranked by a lookahead and to take `#1 best` (the old "never swipe
  up" and "prefer merges" lines contradicted the ranking, the Tetris lesson).

Offline check with the game's own RNG: depth 1 median 2938 (5 of 8 over), depth 2 median 4632 (0 over), depth 3
median 4778 (0 over) at 52 ms per move. Depth 2 kept. Uncapped, depth 2 reaches the 2048 tile in 4 of 8 games.

## Results, 8 seeds, 300 ticks

| | before (pack only) | after (ranked swipes) |
|---|---|---|
| Jev score median | 2104 | **4626** (3652–4788) |
| Jev games over before cap | 6 of 8 | **0 of 8** |
| Jev best tile | 128 median, max 256 | **512** in 7 of 8 |
| Swipes that moved nothing | ~30% | 0 |
| CLM stand-in score median | 1224 | 4626 (identical games) |
| random score median | 898 | 684, all 8 over |

Jev took the `#1 best` option on all 2,399 decisions, so its games are identical to the stand-in's: the score now
comes from the compiler, and Jev's job here is to follow the ranking. Cost $0.10 for 8 games, Jev median 340 ms.
Perception: 0 of 2,400 boards differed from the page's own state.

The 300-tick cap now binds: every game was alive at the cap, and 300 swipes cap the score near 4,800.

## Rerun
```bash
cd anygame && pip install -e ".[stream]"
ANYGAME_LOG_TRUTH=1 OPENROUTER_API_KEY=placeholder anygame bench 2048 --device "web://games/2048.html?seed={seed}#state=window.__state()" \
  --sensor jev --seeds 1,2,3,4,5,6,7,8 --max-ticks 300 --out runs/2048/logs --append runs/2048/summary.jsonl
```
Logs: /mnt/project-files/anygame/2048-lookahead/{jev,clm,random}/logs/.
