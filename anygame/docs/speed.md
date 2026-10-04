# Wall time per decision (gap 6)

The held-out score and the Pokemon run are both limited by wall time, not game time. On the held-out games, the
long-horizon agent made about 18 presses per wall minute with the top pick, and the 15-minute limit ended every
top-pick run. Using its full 10 game-minutes would take about 92 presses per minute.

## Where the time went

The long-horizon agent with the top pick, on Tobu Tobu Girl, profiled over 91 ticks (`python -m cProfile -m anygame.cli
play packs/gameboy --device pyboy://.../tobutobugirl.gb --sensor none --no-writer --max-ticks 91`). The menu reader's
trials of each entry (`menu.explore`, with play-outs) took 90% of the time:

| part | before | after step 1 |
|---|---|---|
| whole run, 91 ticks | 184 s | 69 s |
| OCR (RapidOCR) | about half | 22 s (214 reads of screens not seen before) |
| grey screen for comparisons | 3.6 ms a call | 0.5 ms a call |
| emulator snapshot + restore | | 16 s |
| emulation | | 10 s |

Same day, same seed, same machine. All 91 screens were identical between the two runs, so the agent made the same
decisions and only the wall time changed.

## Step 1 (done)

- `playout._small` samples the upscaled screen before averaging it. The values are identical; the call is 7x faster,
  and a play-out compares screens every 20 frames.
- `ocr._text` answers a repeat of the same pixels from a 512-entry cache. Menu trials read the same screens many times.
- `play_out(restless=N)` can end a play-out as "busy" when the screen never stands still for N frames (real-time
  play). It is off by default: on Tobu Tobu Girl the animated title moves for 30 s and then waits, and turning it on
  changed the agent's decisions there.

## What is left (in the menu reader, the long-horizon thread's code)

- Fewer trials: the menu reader explores every new screen, and on an action game nearly every screen is new. A
  coarser key for its cache would cut most of the 69 s.
- `menu._small` is the old 3.6 ms version; importing `playout._small` saves about 4 s per 91 ticks.
- `restless=600` for play-outs where the screen has no text.
- OCR shrinks as `tiletext` learns a game's font, if a glyph book is kept per game across runs.
