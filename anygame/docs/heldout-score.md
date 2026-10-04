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


## Update 2026-10-04: the discovered-state agents

The same suite, seeds, budget and floor, now with the agents from the Pokemon branches. They read nothing written for
any game: the RAM scanner finds position and map while playing, a probe tells walk/choice/text/button screens apart
by branching from save states, a world memory and navigator offer paths, and (long-horizon branch, PR #14) menus are
tried from save states and offered as questions, and Azure writes goals from what the game says. Each run starts
from a fresh copy of the pack, so nothing discovered in one seed carries to the next.

**Headline: the long-horizon agent is the best agent so far and still not above random.** Median normalised score
-0.05 with its top-pick decider (above random on 1 of 4: Renegade Rush, +0.17), -0.10 with Jev (1 seed). It is the
first agent level with or above random on PostBot and Renegade Rush; it is behind random on Tobu Tobu Girl, where it plays
about 90 presses in 15 minutes against random's 1,380.

| game | kind | random (milestones, normalised) | standin (milestones, normalised) | jev (milestones, normalised) | PR #12 agent pre-fix, top (milestones, normalised) | PR #12 agent, top (milestones, normalised) | long-horizon agent, Jev (milestones, normalised) | long-horizon agent, top (milestones, normalised) |
|---|---|---|---|---|---|---|---|---|
| gbhack | roguelike | 0.33, +0.00 | 0.00, -0.50 | 0.20, -0.20 | 0.33, -0.00 | 0.33, -0.00 | 0.20, -0.20 | 0.27, -0.10 |
| postbot | puzzle | 0.40, +0.00 | 0.20, -0.33 | 0.20, -0.33 | 0.20, -0.33 | 0.20, -0.33 | 0.40, +0.00 | 0.40, +0.00 |
| renegade-rush | action | 0.20, +0.00 | 0.00, -0.25 | 0.00, -0.25 | 0.00, -0.25 | 0.00, -0.25 | 0.20, +0.00 | 0.33, +0.17 |
| tobutobugirl | platformer | 0.53, +0.00 | 0.00, -1.14 | 0.40, -0.29 | 0.60, +0.14 | 0.60, +0.14 | 0.40, -0.29 | 0.40, -0.29 |
| aevilia (development) | rpg | 0.13, +0.00 | 0.00, -0.15 | – | – | – | – | – |
| **held-out suite** | median normalised (games above 0.1) | **+0.00** (0 of 4) | **-0.42** (0 of 4) | **-0.27** (0 of 4) | **-0.13** (1 of 4) | **-0.13** (1 of 4) | **-0.10** (0 of 4) | **-0.05** (1 of 4) |

Where each run stalled (mean over seeds): the first milestone not reached, how often the screen the agent decided on was the same as the one before (a press that did nothing), and how many different screens it saw.

| game | decider | reached (per seed) | stalled before | unchanged screen | distinct screens | presses | wall s |
|---|---|---|---|---|---|---|---|
| gbhack | random | 2 / 2 / 1 of 5 | reached experience level 2; went down to dungeon level 2 | 32% | 539 | 1379 | 3.5 |
| gbhack | standin | 0 / 0 / 0 of 5 | started a game (pet chosen, in the dungeon) | 16% | 6 | 1379 | 4.2 |
| gbhack | jev | 1 of 5 | went down to dungeon level 2 | 1% | 26 | 1380 | 462.1 |
| gbhack | PR #12 agent pre-fix, top | 1 / 3 / 1 of 5 | went down to dungeon level 2; went down to dungeon level 3 | 3% | 192 | 754 | 909.3 |
| gbhack | PR #12 agent, top | 1 / 3 / 1 of 5 | went down to dungeon level 2; went down to dungeon level 3 | 8% | 143 | 786 | 746.4 |
| gbhack | long-horizon agent, Jev | 1 of 5 | went down to dungeon level 2 | 42% | 156 | 969 | 900.5 |
| gbhack | long-horizon agent, top | 1 / 1 / 2 of 5 | went down to dungeon level 2 | 8% | 444 | 620 | 903.3 |
| postbot | random | 2 / 2 / 2 of 5 | solved level 1 | 37% | 366 | 1379 | 2.1 |
| postbot | standin | 1 / 1 / 1 of 5 | ran a program | 0% | 9 | 1379 | 4.1 |
| postbot | jev | 1 of 5 | ran a program | 1% | 9 | 1380 | 475.9 |
| postbot | PR #12 agent pre-fix, top | 1 / 1 / 1 of 5 | opened the program editor | 0% | 5 | 1500 | 662.6 |
| postbot | PR #12 agent, top | 1 / 1 / 1 of 5 | opened the program editor | 0% | 5 | 1500 | 715.5 |
| postbot | long-horizon agent, Jev | 2 of 5 | solved level 1 | 2% | 56 | 1018 | 845.0 |
| postbot | long-horizon agent, top | 2 / 2 / 2 of 5 | solved level 1 | 0% | 4 | 845 | 900.8 |
| renegade-rush | random | 1 / 1 / 1 of 5 | drove 800 road lines | 34% | 654 | 1379 | 2.3 |
| renegade-rush | standin | 0 / 0 / 0 of 5 | started a run | 100% | 5 | 1379 | 3.7 |
| renegade-rush | jev | 0 of 5 | started a run | 99% | 5 | 1380 | 472.5 |
| renegade-rush | PR #12 agent pre-fix, top | 0 / 0 / 0 of 5 | started a run | 33% | 2 | 1345 | 335.0 |
| renegade-rush | PR #12 agent, top | 0 / 0 / 0 of 5 | started a run | 33% | 2 | 1345 | 326.0 |
| renegade-rush | long-horizon agent, Jev | 1 of 5 | drove 800 road lines | 0% | 73 | 243 | 917.1 |
| renegade-rush | long-horizon agent, top | 2 / 1 / 2 of 5 | drove 800 road lines; reached the second area (1600 lines) | 4% | 158 | 165 | 903.6 |
| tobutobugirl | random | 2 / 3 / 3 of 5 | cleared the first level; climbed half of a level | 11% | 706 | 1379 | 3.5 |
| tobutobugirl | standin | 0 / 0 / 0 of 5 | past the title screen, at the level select | 14% | 411 | 1379 | 5.3 |
| tobutobugirl | jev | 2 of 5 | climbed half of a level | 4% | 1205 | 1380 | 470.0 |
| tobutobugirl | PR #12 agent pre-fix, top | 3 / 3 / 3 of 5 | cleared the first level | 2% | 1036 | 1219 | 885.5 |
| tobutobugirl | PR #12 agent, top | 3 / 3 / 3 of 5 | cleared the first level | 2% | 1061 | 1244 | 823.7 |
| tobutobugirl | long-horizon agent, Jev | 2 of 5 | climbed half of a level | 5% | 107 | 279 | 910.3 |
| tobutobugirl | long-horizon agent, top | 2 / 2 / 2 of 5 | climbed half of a level | 17% | 66 | 89 | 906.2 |
| aevilia | random | 1 / 1 / 0 of 5 | finished the intro tutorial, in the player's bedroom; went downstairs | 45% | 385 | 1379 | 3.5 |
| aevilia | standin | 0 / 0 / 0 of 5 | finished the intro tutorial, in the player's bedroom | 95% | 71 | 1379 | 4.8 |

Not run: pokemon-red: no ROM at /mnt/project-files/roms/pokemon-red.gb


Rows: random, standin and jev are the button-only baseline above. "PR #12 agent" is the discovered-state pack from
claude/anygame-pokemon-red-zlo39b, before and after the 21:18Z discovery fix (identical numbers on these games).
"long-horizon agent" is claude/anygame-pokemon-longhorizon-cmt588 at 73a0805 (PR #14).

### What binds: wall time

The 900-second wall limit ended 15 of the 16 long-horizon runs, not game time: branching from save states and trying
menus costs seconds per decision. Presses in 15 minutes: Tobu Tobu Girl about 90, Renegade Rush about 170, GBHack
370 to 970, PostBot about 850 (button-only agents: 1,380, ending on game time). Branching is free in game time (the
emulator is restored), so the agent's lookahead is a capability a human player lacks; the wall limit is what keeps
it honest. A longer wall budget would change these numbers; it is a suite-wide setting in heldout/suite.yaml, kept at
900 s here so the rows compare.

### Spend (long-horizon agent with Jev, 1 seed per game)

| game | Jev calls | Jev dollars | Azure goal calls | presses | stopped by |
|---|---|---|---|---|---|
| Tobu Tobu Girl | 131 | $0.010 | 0 | 279 | wall time |
| PostBot | 1,017 | $0.049 | 10 | 1,018 | game time |
| Renegade Rush | 238 | $0.017 | 6 | 243 | wall time |
| GBHack | 656 | $0.040 | 11 | 969 | wall time |
| total | 2,042 | $0.116 | 27 | | |

The top-pick runs made 74 Azure goal calls over 12 runs and no Jev calls. Azure does not report a price per call, so
its spend is given in calls. One goal answer in 101 was rejected by its check.

### Also new

- GBHack's experience-level milestone was reached for the first time (long-horizon agent, top pick, seed 3), so its
  address is now seen in play, not only from the source layout.
- No run crashed.

### Reproduce

    cd anygame
    python -m heldout.run --pack gameboy --decider top --out runs/lh-top
    python -m heldout.run --pack gameboy --decider jev --seeds 1 --out runs/lh-jev
    python -m heldout.report runs/random runs/standin runs/jev runs/lh-top runs/lh-jev


## Throughput before gap 6 (2026-10-04)

The measurement the speed work starts from: presses per wall-minute and how often the 900-second wall limit, not the
36,000-frame game budget, ended a run. Same runs as the tables above.

| agent | runs | presses per wall-minute (median of runs) | per game: Tobu / PostBot / Renegade / GBHack | runs ended by the wall-clock limit |
|---|---|---|---|---|
| random | 12 | 29,774 | 23,657 / 39,429 / 34,500 / 24,353 | 0 of 12 (0%) |
| standin | 12 | 19,947 | 15,912 / 20,180 / 22,362 / 19,714 | 0 of 12 (0%) |
| jev | 4 | 176 | 176 / 174 / 175 / 179 | 0 of 4 (0%) |
| PR #12 agent pre-fix, top | 12 | 109 | 80 / 148 / 237 / 49 | 5 of 12 (42%) |
| PR #12 agent, top | 12 | 128 | 87 / 129 / 241 / 31 | 4 of 12 (33%) |
| long-horizon agent, top | 12 | 18 | 6 / 57 / 11 / 38 | 12 of 12 (100%) |
| long-horizon agent, Jev | 4 | 41 | 18 / 72 / 16 / 65 | 3 of 4 (75%) |

To spend the whole game budget inside the wall budget a run needs 2,400 game frames per wall-minute, which for
single presses (26 frames each) is about 92 presses per wall-minute; a walking macro covers more frames per press. The
long-horizon agent is at 18 with its top pick and 41 with Jev, so it uses a small part of its game time before the
clock stops it.

Caveat: the discovered-state and long-horizon runs ran four at a time on a 4-core container, the baseline runs one
at a time. A re-score after a throughput change runs the same way (four games in parallel, seeds 1–3 for top pick,
seed 1 for Jev) so the before and after compare.


## After gap 6 step 1: the speed-gaps agent (PR #21 @ 4cd17f3, 2026-10-04)

The long-horizon agent with the full-run-gaps work on top (exact text by tiletext, play-outs, numbers, chains, gap 6
speed step 1, the Azure usage ledger). Same four games, seeds, budget and parallelism as the long-horizon rows: top
pick seeds 1–3, Jev seed 1, four games at a time on 4 cores.

| game | random | long-horizon, top | long-horizon, Jev | speed-gaps, top | speed-gaps, Jev |
|---|---|---|---|---|---|
| GBHack | 0.33 | 0.27, −0.10 | 0.20, −0.20 | **0.53, +0.30** | 0.40, +0.10 |
| PostBot | 0.40 | 0.40, +0.00 | 0.40, +0.00 | 0.40, +0.00 | 0.40, +0.00 |
| Renegade Rush | 0.20 | 0.33, +0.17 | 0.20, +0.00 | 0.20, +0.00 | 0.20, +0.00 |
| Tobu Tobu Girl | 0.53 | 0.40, −0.29 | 0.40, −0.29 | 0.40, −0.29 | 0.40, −0.29 |
| **suite median (games above 0.1)** | 0 | −0.05 (1 of 4) | −0.10 (0 of 4) | **+0.00 (1 of 4)** | **+0.00 (0 of 4)** |

Cells are milestone fraction, normalised. The first time an agent has reached random on the suite median; GBHack is
the first game with a clear gain (3 of 5 milestones on two seeds: dungeon level 2 and experience level 2).
Renegade Rush lost the +0.17 the long-horizon top pick had.

| agent | presses per wall-minute (median) | per game: Tobu / PostBot / Renegade / GBHack | game frames per wall-minute (median) | runs ended by the wall-clock limit | Jev $ | Azure $ (calls) |
|---|---|---|---|---|---|---|
| long-horizon agent, top | 18 | 6 / 57 / 11 / 38 | 690 | 12 of 12 (100%) | 0 | not logged then |
| long-horizon agent, Jev | 41 | 18 / 72 / 16 / 65 | 1,191 | 3 of 4 (75%) | 0.116 | not logged then (101 goal calls) |
| speed-gaps agent, top | 60 | 10 / 213 / 26 / 81 | 2,459 | 6 of 12 (50%) | 0 | 0.700 (539) |
| speed-gaps agent, Jev | 76 | 109 / 81 / 16 / 71 | 3,650 | 1 of 4 (25%) | 0.104 | 0.178 (129) |

Azure dollars by game (top pick, three runs / Jev, one run): Tobu 0.226 / 0.038, PostBot 0.046 / 0.004, Renegade
0.273 / 0.097, GBHack 0.155 / 0.039. Each run's chat-model calls go to its own ledger
(`<game>-<agent>-<seed>.azure.jsonl` beside the run) and are copied into the project ledger afterwards.

**Where the wall time goes** (corrected 2026-10-04, see the next section): tiletext's Azure labelling (40 calls per run
on Tobu Tobu Girl and Renegade Rush, its per-run cap, 470–540 s of Azure time) runs in a background thread and overlaps
play. A first version of this paragraph blamed it for the wall limit; the warm-book runs and a profile below show the
wall time goes to menu explores instead.

**Glyph book: fresh every run.** The `gameboy` pack names no `book:`, so the tiletext glyph book lives in memory
for one process. The harness clears it (with the OCR pixel cache) at the start of every run and ignores
`ANYGAME_GLYPHS`, so seeds of one game do not share what an earlier seed learned. That is the strict held-out
reading (the agent meets each game cold). A book kept per game across runs would remove most of the labelling time
above after the first run; whether that counts as "never tuned on" is a choice for whoever owns the protocol. A
book carried across games would be the general version.

    python -m heldout.run --pack gameboy --decider top --out runs/gaps-top          # four games in parallel in practice
    python -m heldout.run --pack gameboy --decider jev --seeds 1 --out runs/gaps-jev


## A glyph book kept per game, and where the 900 s go (2026-10-04)

The same agent and protocol, with `--books DIR`: one glyph book file per game carried from run to run (top pick seeds
1, 2, 3, then Jev seed 1), reported as its own column. Nothing else carries over. Seed 1 of the top pick starts empty,
like the cold row. The cold-start row above stays the official one until the protocol is decided.

| game | random | cold, top | per-game book, top | cold, Jev | per-game book, Jev |
|---|---|---|---|---|---|
| GBHack | 0.33 | 0.53, +0.30 | 0.40, +0.10 | 0.40, +0.10 | 0.40, +0.10 |
| PostBot | 0.40 | 0.40, +0.00 | 0.40, +0.00 | 0.40, +0.00 | 0.40, +0.00 |
| Renegade Rush | 0.20 | 0.20, +0.00 | 0.27, +0.08 | 0.20, +0.00 | 0.40, +0.25 |
| Tobu Tobu Girl | 0.53 | 0.40, −0.29 | 0.40, −0.29 | 0.40, −0.29 | 0.60, +0.14 |
| **suite median (games above 0.1)** | 0 | +0.00 (1 of 4) | +0.04 (0 of 4) | +0.00 (0 of 4) | **+0.12 (2 of 4)** |

| agent | presses per wall-minute (median) | per game: Tobu / PostBot / Renegade / GBHack | game frames per wall-minute | runs ended by the wall limit | Jev $ | Azure $ (calls) |
|---|---|---|---|---|---|---|
| cold, top | 60 | 10 / 213 / 26 / 81 | 2,459 | 6 of 12 (50%) | 0 | 0.700 (539) |
| per-game book, top | 82 | 11 / 226 / 25 / 83 | 2,916 | 6 of 12 (50%) | 0 | 0.624 (498) |
| cold, Jev | 76 | 109 / 81 / 16 / 71 | 3,650 | 1 of 4 (25%) | 0.104 | 0.178 (129) |
| per-game book, Jev | 104 | 140 / 132 / 50 / 76 | 4,340 | 1 of 4 (25%) | 0.141 | 0.150 (126) |

**The warm book does not fix the wall limit.** Tobu Tobu Girl's top pick stays at 9–13 presses per wall-minute with
a book of 356 and then 793 glyphs, and still makes its 40 labelling calls every run: as the full-run-gaps thread
measured, nearly all of Tobu's "glyphs" are two-colour scenery tiles, so the book never covers the screen. Labelling
calls fall only where the game has real text (GBHack 26 → 7 → 2, PostBot already 1–2). The Jev score gains (+0.12
median) are one seed each and within the run-to-run spread: seed 1 of the top pick started from an empty book in both
rows and still differed (GBHack 0.6 vs 0.4), because Azure answers and four-way CPU sharing are not reproducible.
Read the score columns as "no worse", not as a gain.

**Profile of one Tobu Tobu Girl top-pick run** (seed 1, budget scaled to 310 s, run alone, cProfile of the main
thread; the labeller's thread is not in it):

| where | seconds of 310 | share |
|---|---|---|
| menu explores (`perceive/menu.py` explore, 75 of 112 steps) | 281 | 91% |
|  · play-outs of each option (`playout.play_out`, 314 calls) | 138 | 44% |
|  · RapidOCR inside menu reads (709 calls; menu.py still uses OCR, not tiletext) | 125 | 40% |
|  · emulator ticks (`pyboy._tick`) | 57 | 18% |
|  · save-state restore/snapshot | 30 | 10% |
|  · screen-difference numpy (`_small`, `_differs`, `_same`) | ~50 | ~16% |
| screen-kind probe | 12 | 4% |
| Azure or Jev waits on the main thread | ~0 | 0% |

(The indented rows overlap: OCR and ticks happen inside play-outs.) The agent explores a "menu" on two of every three
steps of a platformer, at 3.7 s each. The levers, in order: stop treating Tobu's play screen as a menu (explore
fired 75 times in 112 steps); switch menu.py's reads from RapidOCR to tiletext (~40% of the run); downscale the
screen-difference checks. All three are in the long-horizon thread's code (menu.py) and the gaps thread's play-out
code, not the harness.

    python -m heldout.run --pack gameboy --decider top --books runs/books --out runs/book-top
    python -m heldout.run --pack gameboy --decider jev --books runs/books --seeds 1 --out runs/book-jev


## After the menu speed fixes: long-horizon 78d2b73 (2026-10-04)

The long-horizon head 78d2b73 contains three changes:
- the explore gate 987d030, which skips a menu explore when the screen text has no word of two or more letters;
- PR #27, `tiletext.boxes`;
- menu-tiletext.patch, so menu reads come from screen cells and fall back to OCR only while the glyph book is small.

Same games, seeds, budget and four-way parallelism as before. Two rows: cold (no glyph book, the official protocol) and the per-game book. The harness now also counts the agent's menu explores and their wall time (`explores`, `explore_s` in each run's row). This is measurement only: the call passes through unchanged.

| game | random | cold, top | cold, Jev | per-game book, top | per-game book, Jev |
|---|---|---|---|---|---|
| GBHack | 0.33 | 0.27, −0.10 | 0.40, +0.10 | 0.27, −0.10 | 0.20, −0.20 |
| PostBot | 0.40 | 0.40, +0.00 | 0.40, +0.00 | 0.40, +0.00 | 0.40, +0.00 |
| Renegade Rush | 0.20 | 0.20, +0.00 | 0.20, +0.00 | 0.27, +0.08 | 0.40, +0.25 |
| Tobu Tobu Girl | 0.53 | 0.47, −0.14 | 0.60, +0.14 | 0.47, −0.14 | 0.40, −0.29 |
| **suite median (games above 0.1)** | 0 | −0.05 (0 of 4) | +0.05 (1 of 4) | −0.05 (0 of 4) | −0.10 (1 of 4) |

The scores do not move outside the run-to-run spread. GBHack seed 2 and Renegade Rush differ by a milestone between otherwise identical rows.

**Throughput and spend**

| agent | presses per wall-minute (median) | Tobu / PostBot / Renegade / GBHack | game frames per wall-minute | runs ended by the wall limit | Jev $ | Azure $ (calls) |
|---|---|---|---|---|---|---|
| speed-gaps 4cd17f3, cold, top | 60 | 10 / 213 / 26 / 81 | 2,459 | 6 of 12 (50%) | 0 | 0.700 (539) |
| speed-gaps 4cd17f3, cold, Jev | 76 | 109 / 81 / 16 / 71 | 3,650 | 1 of 4 (25%) | 0.104 | 0.178 (129) |
| **78d2b73, cold, top** | **148** | 128 / 292 / 23 / 225 | 3,195 | **3 of 12 (25%)** | 0 | 0.688 (376) |
| **78d2b73, cold, Jev** | **93** | 148 / 106 / 71 / 80 | 4,662 | **1 of 4 (25%)** | 0.193 | 0.162 (109) |
| 78d2b73, per-game book, top | 192 | 202 / 280 / 178 / 178 | 4,979 | **0 of 12** | 0 | 0.508 (297) |
| 78d2b73, per-game book, Jev | 113 | 136 / 116 / 105 / 111 | 3,648 | **0 of 4** | 0.277 | 0.079 (70) |

Jev spend rises because runs now reach more of their press budget.

**Explores, steps explored per 100**

| game | before (profile, 4cd17f3) | 78d2b73 cold, top (seeds 1–3) | 78d2b73 cold, Jev | wall seconds in explores, cold top |
|---|---|---|---|---|
| Tobu Tobu Girl | 67 | 9 / 8 / 8 | 1 | 214–266 of 509–594 |
| PostBot | – | 1 / 1 / 1 | 1 | 6–9 |
| GBHack | – | 1 / 22 / 1 | 3 | 28–261 |
| Renegade Rush | – | 19 / 43 / 28 | 46 | **820–892 of 900–955** |

**What this shows**

- **Tobu Tobu Girl's explores dropped from 67 to about 8 per 100 steps.** Its top pick went from 10 to 128 presses per wall-minute. It now ends on the frame budget, not the clock.
- **Renegade Rush is the one game still held back by the clock, and the cold book is why.** With no book, its explores take 820–892 of the 900 seconds. With the per-game book, explores take 224–620 s and every run ends on the press or frame budget (178 presses per wall-minute). The likely cause is that while the book is small, menu reads still fall back to OCR (the patch's "OCR only while the book is small"), and Renegade Rush's screen has letters on it, so the word gate lets explores through. The gate still lets through 19–46 explores per 100 steps there, so an explore that is cheap or skipped on an action screen is the next lever.
- **The agent now uses its whole game budget on three of four games, cold.** The 92-presses-per-wall-minute target is met: median 148 for the top pick and 93 for Jev.

### Where Renegade Rush's cold 900 s go (profile, 2026-10-04)

One cold top-pick run on long-horizon 78d2b73, profiled with cProfile on the main thread. Settings: seed 2, budget scaled to 310 s, run alone, same method as the Tobu profile.

The run made 22 presses in 310 s and explored a "menu" 8 times. **The 8 explores took 303 s (98%), 38 s each.**

| where (inside the 8 explores) | seconds of 310 | share |
|---|---|---|
| play-outs of every entry found (`playout.play_out`, 580 calls, about 72 per explore) | 150 | 48% |
| screen comparisons between entries (`menu._same` 40 s + `menu._cursor_box` 40 s), each new entry against all earlier ones | 81 | 26% |
| emulator ticks (`pyboy._tick`, partly inside play-outs) | 57 | 18% |
| RapidOCR (`ocr._text`; 28 s of it in `menu._outcome`, 9 s in `menu._read_text`) | 40 | 13% |
| save-state restore and snapshot | 30 | 10% |
| `battle.bars` (fight effect of each play-out) | 16 | 5% |
| tiletext cell boxes (`tiletext.boxes`) | 9 | 3% |

Rows overlap: ticks, OCR and restores also happen inside play-outs.

**The guess was only partly right.** The OCR fallback costs 13%. The main cost is the size of each explore.

On an action screen, every direction moves the picture, so the explore never finds an end of the list. It records an entry for each of up to 5 presses in each direction, then for every down/up entry it tries left and right as a grid. That gave about 76 entries per explore, against a maximum of 121.

Each entry is then pressed, watched, compared against every other entry, and played out for up to 1,800 frames. Play-outs and the quadratic screen comparisons alone account for 74% of the run.

The word gate lets these explores through because the text read finds at least one word on Renegade Rush's screen. Which letters those are was not checked. The fix belongs in the menu explore, owned by the long-horizon thread. Options:
- stop and drop the explore when, say, the first two presses in a direction each change the screen;
- cap the number of entries;
- play out only the entries whose short outcome differs.

Moving `_outcome`'s reads from OCR to tiletext would recover at most the 13%.
