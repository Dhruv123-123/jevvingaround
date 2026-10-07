# Screen-only phase 0: a cache that ignores sprites and scrolling

2026-10-07, branch `claude/anygame-screen-only-phase0-v9o8sg` (draft PR on the screen-only perception branch, #31).
Phase 0 of `roadmap-screen-only.md`. Offline over the same captures as `screen-only-perception.md`, **$0**: no
Azure, no Jev. Data: `/mnt/project-files/anygame/screen-only-perception/phase0/`.

## The answer

Whole frames answered by the cache once warm (game-minutes 6–10) went up on every game, and what a model would be
asked about fell 5–9x on the sprite and scrolling games. Two of the six games still miss the 90% bar.

| game | frames fully answered, warm: before | after | items for the model per warm min: before | after | projected $/game-hour: before | after |
|---|---|---|---|---|---|---|
| Tobu Tobu Girl | 58.0% | **77.2%** | 489 | 79 | $1.47 | $0.24 |
| PostBot | 95.7% | **98.1%** | 28 | 3 | $0.08 | $0.01 |
| Renegade Rush | 63.4% | **75.9%** | 419 | 85 | $1.26 | $0.26 |
| GBHack | 99.3% | 99.3% | 1 | 1 | $0.00 | $0.00 |
| Aevilia | 80.8% | **90.3%** | 405 | 325 | $1.22 | $0.98 |
| Pokemon Red (ck45700) | 90.3% | **96.9%** | 52 | 6 | $0.16 | $0.02 |
| Pokemon Red (power-on) | 99.2% | 99.6% | 1 | 1 | $0.00 | $0.00 |

"Before" is the first experiment's cache run offline (`offline/summary.json`; the write-up's 47–95% are from the
labelled run, where a cell waiting for its answer still counted as unknown). Projected dollars use the first
experiment's measured ~$0.05 per 1,000 labelled items, so they assume an object costs what a cell did to label.

Against the phase-0 bar (≥ 90% of frames on all six games, ≤ $0.5 per game-hour): frames pass on Pokemon, PostBot,
GBHack and Aevilia and miss on Tobu Tobu Girl and Renegade Rush; cost passes everywhere except Aevilia, whose
leftover items are new rooms (genuine novelty, not sprites).

## What changed (`anygame/perceive/cellbook.py`)

1. **Bands.** Each 8-row strip gets its own horizontal phase and strips chain top to bottom, so a playfield
   scrolling under a fixed status bar is cut on its own grid. 56% of Renegade Rush's warm frames and 80% of Tobu's
   are cut in more than one band.
2. **Sprite cut-out.** A new cell that equals a known tile on at least 16 of its 64 pixels is that tile plus
   foreground; a new cell with no background showing that touches foreground is a sprite's solid middle.
3. **Objects.** Foreground is grouped into objects keyed by their own pixels and shape. A new object is answered by
   a known one that looks alike (animation step), holds it (sprite plus unseen background), is a large part of it
   (cut by the screen edge), or continues an object from the last frame (centre within 16 px, size within 2x).
   Objects over 32 px or under 8 px are new scenery and stay plain cells. New cells are always learned as cells
   too, so a frame is answered when every new cell is a known cell or sits under a known object.

Grader-side checks (sprite boxes from OAM, never read by the cache): the cut explains 86–91% of new cells under
sprites on Tobu, PostBot, Renegade Rush and Pokemon (47% Aevilia). Tracked objects are 76–94% sprite pixels (57% on the power-on run). All
objects together are only 11–69% sprite pixels: much new text and scenery also arrives as "tile plus foreground".
That is harmless for the hit rate (those cells are learned as cells next time) but means the object book is not a
sprite list yet. Lookup costs 2–38 ms a frame (the scrollers pay for the band search and object matching).

## What is left

- **Tobu and Renegade Rush (≈ 23% of frames still need a call).** Mostly sprites overlapping each other or a
  background the book never saw behind them; 42–43 objects a warm minute stay new. Press-and-watch (phase 1) gives
  the motion needed to split overlapping sprites and to learn the background a sprite covers.
- **Objects are not labelled yet.** The labeller still sends cells; asking the model to name whole objects (one
  crop per object) is the next Azure spend, and the first real test of whether object labels beat cell labels.
- **Tracking can be wrong** when a new sprite appears next to an old one (it inherits the old one's label).
  Contradictions from press-and-watch should undo it.

## Reproduce

    python scripts/screenonly_run.py --cap CAP --out OUT --offline --cache objects      # phase 0, $0
    python scripts/screenonly_run.py --cap CAP --out BEFORE --offline                     # first experiment's cache
    python scripts/screenonly_phase0.py BEFORE/summary.json OUT/summary.json

`CAP` is `/mnt/project-files/anygame/screen-only-perception/cap/`.
