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
