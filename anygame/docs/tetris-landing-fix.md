# Tetris: Jev now takes the compiler's best landing (2026-10-02)

Branch `claude/anygame-tetris-landing-3xsdkp` (on `claude/anygame-jev-scale-run-dubj38`), not merged, no PR.

## Why Jev skipped landing `a`
In the real-Jev run Jev picked a landing other than `a` on 188 of 1,453 pieces. In 130 of those (69%), `a` was
labelled "FILLS the well" and the pick "keeps well". The pack's paragraph told Jev to keep the well open, but the
compiler's ranking score has no well term, and that ranking is what clears 156 lines for the stand-in. Jev was
following the pack's words against the ranker. Most of the rest were look-alikes where `a` is better only on total
stack height, which the score uses but the landing text does not show (it shows max height). The paragraph never
said the landings are ranked.

## Fix
Only `packs/tetris/pack.yaml`'s paragraph changed: it now says the landings are ranked best first by a score that
already weighs their consequences, and to take `a` unless another clears more lines without more holes. No compiler,
question or rule change.

Replaying the 188 saved deviation frames through Jev with the new paragraph: 185 now take `a` (old paragraph: 2,
Jev is deterministic on these). 80 sampled frames where Jev already took `a` still do. Dropping the well label as
well did slightly worse (95%), and offering only the top 3 worse again (84%).

## Real Jev, Tetris, seeds 1–8, level 5, cap 400 ticks

| | lines median | lines max | games over | took `a` |
|---|---|---|---|---|
| before (pack as was) | 46.5 | 156 | 7 of 8 | 87% |
| **after** | **155.5** | 159 | **3 of 8** | 100% (2,765 of 2,765) |
| CLM stand-in, always `a` (offline run) | 156 | | 2 of 8 | 100% |

Per seed after (before): 123 (15), 156 (46), 118 (44), 158 (111), 158 (47), 159 (18), 155 (156), 122 (60).
The 3 games still over end with Jev taking `a` every time, so they are the compiler's ceiling, not Jev's.

Jev cost: $0.19 for the 8 games, plus $0.08 for the saved-frame replays and a cut-off first try at seed 8.

Note: Jev now plays Tetris exactly as the stand-in does. In this game the compiler does the playing; better Tetris
from here means a better ranker (for example lookahead with `next`), not a different answer from Jev.

## Rerun
```bash
cd anygame && ANYGAME_LOG_TRUTH=1 OPENROUTER_API_KEY=placeholder anygame bench tetris \
  --device "web://games/tetris.html?seed={seed}&level=5#state=window.__state()" --sensor jev \
  --seeds 1,2,3,4,5,6,7,8 --max-ticks 400 --out runs/tetris-fix/logs
python scripts/tally_run.py runs/tetris-fix
```

# Follow-up: one-piece lookahead in the ranker (2026-10-03)

`lookahead: true` on the tetris read (now on in the pack) ranks each landing by the best score after also placing the
preview's `next` piece (the mean over all seven if the preview is unreadable). About 80 ms per read. The landing text
is unchanged and still shows one-piece consequences. The extension's TypeScript compiler does not implement it and
ignores the key.

| decider, seeds 1–8, cap 400 ticks | lines median | games over |
|---|---|---|
| stand-in, no lookahead | 156.5 | 2 of 8 |
| stand-in, lookahead | 158 | **0 of 8** |
| Jev, no lookahead (above) | 155.5 | 3 of 8 |
| Jev, lookahead, previous paragraph | 158 | 2 of 8 |
| **Jev, lookahead, paragraph says the ranking looks ahead** | 158 | **0 of 8** |

At 400 ticks the line count is capped near 160, so games over is the number that moves. Longer games with the
stand-in, 1,000 ticks, seeds 1/3/5/8: without lookahead 2 of 4 over (122 lines each, median 260); with it 0 of 4 over,
lines 396–399.

With lookahead the top landing often skips a one-line clear to set up a bigger one, so the "take `a` unless another
clears more lines" paragraph made Jev leave `a` on 9% of pieces, and seeds 1 and 3 ended. The paragraph now says the
ranking looks ahead and to take `a`. Replaying those 258 saved skips: 257 now take `a`. Rerunning seeds 1 and 3: both
alive at the cap with 158 lines, `a` on 800 of 800 pieces. The last row is those 2 reruns plus the other 6 seeds from
the previous-paragraph run, which were all alive at the cap.

Jev cost this round: $0.26 ($0.19 for 8 seeds, $0.05 for the 2 reruns, $0.02 replays).
