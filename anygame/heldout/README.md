# The held-out any-game score

One number per game and one for the suite, measuring how far today's agent gets on Game Boy games nobody tuned it
for. Roadmap gap G0: until this exists, per-game tuning looks like progress.

```
python -m heldout.run --decider random      # the floor, 3 seeds per game
python -m heldout.run --decider standin     # the top-pick stand-in (test/clm_stub.py), same protocol as Jev
python -m heldout.run --decider jev         # checks credit with one call first
python -m heldout.report runs/random runs/standin runs/jev
```

## What a run is

- **The agent** is `packs/gameboy`: the eight buttons and a paragraph that names no game. No reads, no rules, no
  per-game code; the decider is told the game is `gameboy`, never its title. The device is `pyboy://…?lock=1`:
  step-locked, so no game time passes while the decider thinks and a seed replays exactly.
- **The grader** (`grader.py`) reads emulator memory after every agent step and latches milestones. It is the only
  code that touches memory. The agent gets frames only.
- **The budget** (`suite.yaml`, a game file may override): 36,000 frames (10 game-minutes), 1,500 presses, 900 wall
  seconds, 1,500 decider calls, $0.25. A run ends at the first limit reached.
- **Seeds** move power-on by 17 frames each, so the game's random numbers differ, and seed the random decider.
- **Output** per run: one JSON line per step (`<game>-<decider>-<seed>.jsonl`), a summary line in `runs.jsonl`
  (milestones and the frame/press/second each was reached, where it stalled, presses that changed nothing, distinct
  screens, decider calls and dollars), and a screenshot at each milestone and at the end.

## The score

Per game: the fraction of its milestones reached, mean over seeds. Normalised: `(score - random) / (1 - random)`,
so the random decider is 0 and every milestone is 1; worse than random is negative. The suite number is the
median normalised score over the held-out games, with the count of games above 0.1 (the roadmap's two numbers).
Development games are reported beside it and never enter the median.

## A game

One file in `games/`: where the ROM comes from and 3 to 5 milestones, each a condition on memory.

```yaml
id: renegade-rush
kind: action
rom: { url: https://hh3.gbdev.io/static/database-gb/entries/renegade-rush/RenegadeRush.gb, sha256: 0511…, license: MIT }
milestones:
  - { id: driving, desc: "started a run",                when: { bcd: 0xC5F1, bytes: 3, ge: 1 } }
  - { id: area1,   desc: "reached the second area",      when: { u8: 0xC5F7, ge: 1 } }
```

Conditions: `u8`, `u16`, `u16be`, `bcd` (little endian unless `order: be`), `bit` (with `n`), compared with `eq ne
gt ge lt le in`, combined with `all` / `any`. `after: <id>` makes a milestone count only once an earlier one is
reached (a map id of 0 that is also the power-on value). A game that needs more can name
`grader: python:<module>:<function>`, called with a memory reader and returning `{milestone id: reached now}`.

Free games are fetched once from Homebrew Hub, checked against the sha256 and cached (`ANYGAME_HELDOUT_ROMS`, else
`/mnt/project-files/roms/heldout/`, else `~/.cache/anygame/heldout/`). Each run copies the ROM to a fresh folder so no
save file carries over. No ROM is in the repository. A commercial game names a local path and is never fetched; a
run without it skips the game and says so.

**Changing the games is one edit to `suite.yaml`**: move ids between `held_out` and `development`, or add one. A game
with no file yet needs one file in `games/` (its milestone addresses are found by whoever writes the grader, from the
source or by RAM search; the agent never sees them).

## Keeping it held out

- `heldout/` sits beside the agent package, not in it. `test/test_heldout.py` fails if any module under
  `anygame/anygame/` imports `heldout` or names it in a string, or if `packs/gameboy` names any suite game.
- Nobody tunes on the held-out games: a change made because of a held-out result must also be justified on the
  development games (Pokemon Red, Aevilia), which are worked on openly.
- The held-out set below is **provisional**. Dhruv picks the real one.

## The provisional set

| game | kind | licence | milestones |
|---|---|---|---|
| Tobu Tobu Girl | platformer | MIT code, CC BY 4.0 assets | level select, playing, half a level, clear level 1, clear level 2 |
| PostBot | puzzle (programming) | MIT | open the editor, run a program, solve levels 1, 2, 3 |
| Renegade Rush | action (car combat) | MIT | start, 800 road lines, areas 2, 3, 4 |
| GBHack | roguelike, menus and messages | MIT code, CC0 art | start, dungeon level 2, experience level 2, dungeon levels 3, 5 |
| Aevilia | RPG (development) | Apache-2.0 | tutorial done, downstairs, outside, forest, another house |
| Pokemon Red | RPG (development) | owner's own ROM | the spec's milestone table, 15 of 22 (the rest wait on verified event flags) |

Each game file says how its addresses were found and checked. Observed in play: Tobu Tobu Girl's game state and
climb, PostBot's screen and level (a program that solves level 1 moved it 0 → 1), Renegade Rush's distance,
GBHack's dungeon level, Aevilia's map id (5 → 4 → 0 walking out of the house). From the source's memory layout
only, not yet observed changing: Tobu Tobu Girl's levels completed, Renegade Rush's area, GBHack's experience level.

## Jev and Pokemon

Jev runs with `--decider jev` under the same budget; each run's `decider_calls` and `cost_usd` are its spend.
Pokemon Red is `games/pokemon-red.yaml`: it runs as soon as the ROM is at `/mnt/project-files/roms/pokemon-red.gb`
(or `ANYGAME_POKEMON_ROM`). Its milestones are the spec's RAM conditions; the Pokemon thread adds the event-flag
ones as `bit:` conditions once checked against the ROM, or swaps in a Python grader.
