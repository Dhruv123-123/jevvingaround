# Held-out any-game score: first baseline

Run 2026-10-03 on branch claude/anygame-heldout-score-oi2xr2 (PR #11). Harness design: anygame/heldout/README.md.
Logs, per-step JSON lines and milestone screenshots: /mnt/project-files/anygame/heldout-score/.

## The answer

Today's agent, given a Game Boy game it was never tuned on, does worse than pressing buttons at random on every
held-out game. Median normalised score: random 0 (by definition), Jev -0.27, the top-pick stand-in -0.42. No decider
is above 0.1 on any game.

The cause is plain in the logs: the generic pack has no reads, because the agent has no general Game Boy perception
yet, so every decision sees the same state. The stand-in pressed A on every step; Jev pressed A on 98% of steps
(1,353 of 1,380 on Tobu Tobu Girl, 1,364 of 1,380 on PostBot). Random wanders further simply because it presses
everything. This is the floor the roadmap's next phase (discovered state from tiles and RAM, save-state lookahead)
has to lift, measured on games nobody tunes on.

## Setup

- Held out (provisional; Dhruv picks the real set in heldout/suite.yaml): Tobu Tobu Girl (platformer), PostBot
  (programming puzzle), Renegade Rush (car combat), GBHack (roguelike). Aevilia is a development game, reported but
  outside the median. Pokemon Red is wired in and skipped until its ROM is at /mnt/project-files/roms/pokemon-red.gb.
- Budget per run: 36,000 frames (10 game-minutes, binding in every run), 1,500 presses, 900 s, 1,500 calls, $0.25.
- Random and stand-in: 3 seeds per game. Jev: 1 seed per held-out game, kept small so the Pokemon thread's Jev runs
  come first.
- Normalised = (score - random) / (1 - random): random 0, every milestone 1, worse than random negative.

## Scores

| game | kind | random (milestones, normalised) | standin (milestones, normalised) | jev (milestones, normalised) |
|---|---|---|---|---|
| gbhack | roguelike | 0.33, +0.00 | 0.00, -0.50 | 0.20, -0.20 |
| postbot | puzzle | 0.40, +0.00 | 0.20, -0.33 | 0.20, -0.33 |
| renegade-rush | action | 0.20, +0.00 | 0.00, -0.25 | 0.00, -0.25 |
| tobutobugirl | platformer | 0.53, +0.00 | 0.00, -1.14 | 0.40, -0.29 |
| aevilia (development) | rpg | 0.13, +0.00 | 0.00, -0.15 | – |
| **held-out suite** | median normalised (games above 0.1) | **+0.00** (0 of 4) | **-0.42** (0 of 4) | **-0.27** (0 of 4) |

Where each run stalled (mean over seeds): the first milestone not reached, how often the screen the agent decided on was the same as the one before (a press that did nothing), and how many different screens it saw.

| game | decider | reached (per seed) | stalled before | unchanged screen | distinct screens | presses | wall s |
|---|---|---|---|---|---|---|---|
| gbhack | random | 2 / 2 / 1 of 5 | reached experience level 2; went down to dungeon level 2 | 32% | 539 | 1379 | 3.5 |
| gbhack | standin | 0 / 0 / 0 of 5 | started a game (pet chosen, in the dungeon) | 16% | 6 | 1379 | 4.2 |
| gbhack | jev | 1 of 5 | went down to dungeon level 2 | 1% | 26 | 1380 | 462.1 |
| postbot | random | 2 / 2 / 2 of 5 | solved level 1 | 37% | 366 | 1379 | 2.1 |
| postbot | standin | 1 / 1 / 1 of 5 | ran a program | 0% | 9 | 1379 | 4.1 |
| postbot | jev | 1 of 5 | ran a program | 1% | 9 | 1380 | 475.9 |
| renegade-rush | random | 1 / 1 / 1 of 5 | drove 800 road lines | 34% | 654 | 1379 | 2.3 |
| renegade-rush | standin | 0 / 0 / 0 of 5 | started a run | 100% | 5 | 1379 | 3.7 |
| renegade-rush | jev | 0 of 5 | started a run | 99% | 5 | 1380 | 472.5 |
| tobutobugirl | random | 2 / 3 / 3 of 5 | cleared the first level; climbed half of a level | 11% | 706 | 1379 | 3.5 |
| tobutobugirl | standin | 0 / 0 / 0 of 5 | past the title screen, at the level select | 14% | 411 | 1379 | 5.3 |
| tobutobugirl | jev | 2 of 5 | climbed half of a level | 4% | 1205 | 1380 | 470.0 |
| aevilia | random | 1 / 1 / 0 of 5 | finished the intro tutorial, in the player's bedroom; went downstairs | 45% | 385 | 1379 | 3.5 |
| aevilia | standin | 0 / 0 / 0 of 5 | finished the intro tutorial, in the player's bedroom | 95% | 71 | 1379 | 4.8 |

Not run: pokemon-red: no ROM at /mnt/project-files/roms/pokemon-red.gb


## Jev's spend

| game | calls | dollars | wall time |
|---|---|---|---|
| Tobu Tobu Girl | 1,380 | $0.033 | 7.8 min |
| PostBot | 1,380 | $0.033 | 7.9 min |
| Renegade Rush | 1,380 | $0.033 | 7.9 min |
| GBHack | 1,380 | $0.033 | 7.7 min |
| total | 5,520 | $0.13 | 31 min |

No call failed. Jev took about 340 ms a call; the device is step-locked, so its latency costs wall time, not game time.

## Caveats

- Jev has one seed against random's three; the gap is large enough that more seeds would not change the sign.
- Three milestone addresses are read from the source's memory layout and were not yet seen changing in play (Tobu
  Tobu Girl's levels completed, Renegade Rush's area, GBHack's experience level). Nothing reached them, so no score
  depends on them yet; they are checked the first time something does.
- The milestones were spaced after one random run so random did not sit near the top (first spacing: random reached
  4 of 5 on Tobu Tobu Girl). That uses only the random floor, never an agent result.
- Normalised scores below -1 are possible (the stand-in on Tobu Tobu Girl, -1.14) when random does well and the agent
  does nothing.

## Reproduce

    cd anygame
    python -m heldout.run --decider random --out runs/random
    python -m heldout.run --decider standin --out runs/standin
    python -m heldout.run --decider jev --games tobutobugirl,postbot,renegade-rush,gbhack --seeds 1 --out runs/jev
    python -m heldout.report runs/random runs/standin runs/jev
