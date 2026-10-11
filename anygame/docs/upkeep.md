# Keeping a number up (C9, second pass)

The Pokemon run from power-on to Route 1 lost every fight it could not win:

- At the end of part 2 it **blacked out** ("RED is out of useable POKéMON"). The game put Red back at home.
- In part 3 it fought on at 1–7 HP out of 24 for about 480 ticks, until the run stopped.

The agent never left a fight and never went back to heal. `anygame/upkeep.py` adds that. It is not an HP rule: it
works on any number shown as "value / most", and nothing in it knows a game.

## What it learns, from play

- **Is the floor fatal?** A number is assumed fatal at 0. The game shows it is fatal when the number gets near 0 and
  the player is then moved somewhere without walking (the place book's forced move): a respawn. A number that hits 0
  with nothing after it is not marked fatal.
- **Where does it refill?** When the number comes back to near full, that place is kept, in this order of choice:
  where the game moved the player, else where they were talking, else where they were.
- **When is it in danger?** At or below 35% of its most, or within one of its largest single drops of the floor.

`advice()` then returns:
- `leave: True`, which prefers a choice whose play-out comes back to the world, soonest (`rank_exits`);
- a goal in the goal writer's format: get the number back to 90%, with the refill place as the target.

## Replayed on the Route 1 run

`scripts/upkeep_replay.py` takes numbers from each read's text, places from the place book, and forced moves from
its events. Losses are found in the text for the report only, never shown to `Upkeep`.

| tick | what happened | upkeep |
|---|---|---|
| 1,064 | rival battle, HP misread as 0/20 | asks to leave (a trainer battle has no exit; harmless) |
| 1,235 | full HP on Route 1 | refill noted (place: Pallet Town) |
| 1,349 | HP falling in wild battles | **asks to leave and go back to Pallet Town** |
| 1,483 | blackout | (warned 134 ticks earlier) |
| 1,489 | moved home with nothing pressed | **learns 0 is fatal** |
| 1,912 | full again | refill noted (place: **Red's house 1F**, where the game put Red) |
| 1,999 | 6 of 22 | **asks to leave and go back to Red's house**: the game has shown 0 is fatal |
| 2,476 | run ends at 1–3 of 24 | (the 477 ticks after 1,999 are the ones this would have saved) |

The first destination is weak. Before the blackout, the only refill it had seen was on Route 1's edge, attributed
to Pallet Town. After the blackout it points at the right place, home, where the game healed Red. It will also learn
a Pokemon Center the first time HP refills there.

**Aevilia** (runs 2 and 3, and the Jev run): none of its screens shows a "value / most" number, and upkeep stays
silent over 2,500 reads. **GBHack** (held-out, 1,200 ticks): HP 9 of 20 after a drop of 11 at once makes it ask to
leave, with the place HP last refilled as the target. It goes quiet at tick 1,004, when HP is back to 20.

## Call sites (long-horizon thread)

1. The loop, every tick: `keep.see(tick, numbers.values(ram), place=<place id>, screen=<screen kind>,
   moved=<a forced door this read>)`. Numbers are `NumberBook.values`, bound to RAM, so HP is known off screen too.
   `moved` is a new `door` event with `forced: True` in `world.book.events` (needs the PR #24 patch).
2. `goals.py`: when `keep.advice()` is not None and the current goal is not already about that number, set
   `advice["goal"]`. It uses the existing `number` condition and `place` target, so no writer call is needed.
3. `perceive/menu.py`: while `advice["leave"]`, put the entries `rank_exits(outcomes)` returns first. Each entry's
   outcome is the screen kind its play-out ended on, plus its frames.
