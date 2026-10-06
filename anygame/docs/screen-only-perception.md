# Screen-only perception: is a novelty cache in front of a vision model affordable?

2026-10-06, branch `claude/anygame-screen-only-perception-f607fw` (draft PR #31, on the long-horizon branch).
Data: `/mnt/project-files/anygame/screen-only-perception/` (`cap/` frames and grader truth, `pass/` per-game
summaries, labeller logs and cell books, `offline/` the $0 hit-rate pass).

## The answer

**Affordable: yes, by a wide margin. Accurate enough to play from: not yet, and not by asking the model about
single cells.**

- Once a game has been seen for a few minutes, the pixel cache answers **97–100% of 8x8 cells** with a lookup
  (about 1 ms a frame). Labelling every new cell of a 10-minute run cost **$0.03–$0.33 per game**; the whole
  experiment, seven runs and the trials, cost **$1.11 of Azure** (582 calls, no Jev).
- At about **$0.05 per 1,000 cells**, the projected cost once warm is **under $0.25 per game-hour** on Pokemon Red,
  PostBot and GBHack and **$1.2–1.6 per game-hour** on the scrolling games (Tobu Tobu Girl, Renegade Rush, Aevilia).
- Whole frames are a different story: only **47–95% of frames** are fully answered once warm. The leftover novelty
  has two causes, both fixable from pixels: sprites drawn over background (16–46% of new cells) and screens that
  scroll off the 8-pixel grid (20% of Tobu's frames, 43% of Renegade Rush's).
- The model's one-letter-per-cell labels are poor: entity precision and recall against the console's own sprite
  table are about 0.5 on the games where that truth applies, and the model often calls a Pokemon floor "blank" or
  even "text" (diagonal hatching read as slashes). Where it does commit to walkable or wall in Pokemon, it is right
  **88%** of the time (413 of 471), but it commits on only 17% of the cells the player actually tried to step on.
- What worked better than the model is the game itself: press-and-watch on pixels (did the picture scroll by a step
  after a direction press?) confirmed 546 walk labels and contradicted 44 on Pokemon, with no RAM.

So the architecture is affordable, but the division of labour should change: the cache plus press-and-watch should
decide physics (walkable, blocked, what moves), and the big model should name larger things (an object, a word, a
whole screen, a menu), where it is good, instead of guessing the physics of an 8x8 picture.

## What was run

The agent side sees pixels only: the 160x144 frame after each press. RAM, the tile-id grid and sprite tables are read
only by the scoring script.

1. **Play**: 1,500 random presses per game (directions weighted up), 8 frames held plus 16 after, so 36,000 frames =
   10 game-minutes, the held-out suite's budget. Games: the four held-out ROMs, Aevilia, Pokemon Red from the
   long-horizon save `ck45700` (Blue's house, Pallet Town) and Pokemon Red from power-on. Random play makes the
   frames independent of the labels, so labelling the captured frames in order is the same as labelling live.
2. **Cache** (`anygame/perceive/cellbook.py`): every frame is cut into 8x8 cells from its pixels and each cell keyed by
   a hash of its pixels. A scrolled frame is cut at the pixel phase where most cells are already known (64 phases tried
   only when the usual two answer under half the cells). Whole frames are keyed too.
3. **Labeller**: new keys are queued; every 40 (or every 6 screens) go to Azure `gpt-5.6-luna` in one call, as a sheet
   of numbered crops (the cell outlined, 8 pixels of surroundings) plus the newest screen with the new cells outlined.
   The model answers one letter per number: text, ground, door, wall, player, entity, menu/UI, blank, unsure.
   582 calls, none failed, median 10 s a call, about 36 cells a call.
4. **Verify**: a label becomes *verified* when two answers agree or the game confirms it; a direction press after which
   the picture shifted by one step (or the player's cells moved) confirms the cells ahead of the player as walkable.
   A confirmation that disagrees with the model is a contradiction and outweighs the model.
5. **Score** (grader side only): entities against the console's sprite table (OAM boxes), text against Pokemon's
   on-screen tile map decoded with pret's charmap, walkability against Pokemon's position bytes (the player moved one
   step, or pressed into a wall it already faced and nothing moved).

## Numbers

Cache, 10 game-minutes of random play per game ("warm" = minutes 6–10):

| game | unique cells | cell hit, min 1 | cell hit, warm | frames fully answered, warm | same whole screen seen before, warm | new cells per min, warm | new cells under sprites | frames off the 8-px grid |
|---|---|---|---|---|---|---|---|---|
| Tobu Tobu Girl | 6,122 | 91.0% | 98.8% | 47.7% | 26.4% | 489 | 45.9% | 19.5% |
| PostBot | 405 | 48.2% | 99.9% | 94.8% | 69.2% | 28 | 2.8% | 0.0% |
| Renegade Rush | 5,264 | 91.6% | 98.6% | 47.2% | 51.2% | 419 | 34.2% | 43.0% |
| GBHack | 1,900 | 88.4% | 99.9% | 84.7% | 57.7% | 1 | 0.0% | 0.0% |
| Aevilia | 4,506 | 90.2% | 97.4% | 66.3% | 63.2% | 405 | 16.1% | 16.2% |
| Pokemon Red (ck45700) | 595 | 97.4% | 99.7% | 72.2% | 51.0% | 52 | 32.7% | 0.1% |
| Pokemon Red (power-on) | 1,204 | 79.1% | 100.0% | 94.1% | 86.3% | 1 | 4.7% | 0.8% |

(Minute 1 in the labelled pass counts cells still waiting for their batch as misses; the $0 pass with instant labels,
in `offline/`, gives 93–99% for minute 1 and the same warm numbers.)

Cost and label accuracy:

| game | Azure calls | dollars | cells labelled | $ per 1,000 cells | projected $ per game-hour, warm | entity precision / recall (vs sprite table) | text precision / recall (Pokemon tile map) |
|---|---|---|---|---|---|---|---|
| Tobu Tobu Girl | 168 | $0.33 | 6,122 | $0.054 | $1.57 | 0.56 / 0.32 | – |
| PostBot | 13 | $0.025 | 405 | $0.063 | $0.10 | 0.03 / 0.20 * | – |
| Renegade Rush | 140 | $0.28 | 5,264 | $0.054 | $1.35 | 0.22 / 0.50 | – |
| GBHack | 51 | $0.086 | 1,900 | $0.045 | $0.003 | – * | – |
| Aevilia | 125 | $0.22 | 4,506 | $0.048 | $1.17 | 0.46 / 0.46 | – |
| Pokemon Red (ck45700) | 26 | $0.042 | 595 | $0.071 | $0.22 | 0.95 / 0.52 | 0.11 / 0.83 |
| Pokemon Red (power-on) | 33 | $0.067 | 1,204 | $0.055 | $0.004 | 0.33 / 0.72 | 0.89 / 0.71 |
| **all** | **582 (incl. 26 trial calls)** | **$1.11** | 19,996 | **$0.055** | | | |

\* GBHack draws its creatures in the background layer, not as sprites, and PostBot mostly does too, so the sprite
table is not the truth for entities there. Precision and recall count cell sightings (a cell seen in 300 frames counts
300 times). The projection is new cells per warm minute x 60 x the game's measured dollars per cell; it assumes play
like random play (an agent that goes further meets more new screens, so treat these as the order of magnitude).

Walkability on Pokemon Red, the cells the player tried to step onto (position bytes as truth):

| run | moved, model said walkable | moved, said wall | blocked, said wall | blocked, said walkable | said blank / text / player / other |
|---|---|---|---|---|---|
| ck45700 | 220 | 0 | 193 | 58 | 2,253 |
| power-on | 93 | 0 | 62 | 85 | 2,216 |

When the model commits, 413 of 471 (88%) and 155 of 240 (65%) are right; most of the time it does not commit. Press-
and-watch from pixels confirmed 546 and contradicted 44 labels on ck45700 (556 / 17 from power-on); it skips cells the
model called blank, text or player, which is most of them.

Lookup cost: 0.7–1.1 ms a frame in Python (3.4 ms on PostBot, whose screens change often); tiny next to a 10 s call.

## What this says about the plan

1. **The cache is the right foundation and it is cheap.** A one-person budget can label everything a Game Boy game
   shows. The open cost is wall time, not dollars: a call takes ~10 s, so new content must never block play (label in
   the background, act on "unknown" meanwhile), as tiletext already does.
2. **Cut sprites out before hashing.** Up to 46% of new cells are a moving thing over a known background. On a tile
   machine the background is recoverable from pixels: the median of recent frames at the same scroll offset, or the
   known cell that matches all pixels the sprite does not cover. Then the background cell hits and the sprite becomes
   its own object with its own key.
3. **Per-region grid phase.** A scrolling playfield under a fixed HUD has two phases on one screen (Renegade Rush
   43% of frames off-grid). Find the phase per band of rows, not per frame.
4. **Physics from the game, names from the model.** Walkable, blocked, pushable, hurts, moves-with-the-d-pad are
   learned by press-and-watch and kept as verified; the model labels whole objects and screens (this is a door, this
   is a menu, this word is START) and is asked again only on contradiction.
5. **Ask the model better questions.** Per-cell letters lose the context that makes a floor a floor. Asking per
   connected region of equal cells, or per object (a sprite group), cuts both calls and confusion.

## Reproduce

    cd anygame
    python scripts/screenonly_capture.py --out runs/so/cap
    python scripts/screenonly_run.py --cap runs/so/cap --out runs/so/offline --offline          # hit rates, $0
    python scripts/screenonly_run.py --cap runs/so/cap --out runs/so/pass --budget 0.38          # Azure only
    python scripts/screenonly_report.py runs/so/pass/summary.json

The labeller refuses anything but Azure (`ANYGAME_LLM_API=azure`); every call is in the usage ledger under the purpose
"screen-only perception".
