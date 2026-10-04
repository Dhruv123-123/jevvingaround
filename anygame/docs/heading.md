# Which way is on (C10, second pass)

On Route 1 the Jev run reached 13 of the route's 36 rows in 870 ticks. 88% of those ticks were battles. Of its 69
walking decisions there, it explored:

| direction | decisions |
|---|---|
| south | 24 |
| east | 19 |
| west | 15 |
| north | 11 |

The goal writer's 60 calls were spent before Route 1 (gap 7), so no goal named a direction. Every direction had an
unexplored tile a few steps away. More time walking sideways in the grass meant more battles.

## The fix: `anygame/heading.py`

`Heading(book).toward(place)` gives a direction to explore first when no goal names one. It is worked out from the
place book (`places.py`):

- **Entered by a join:** a place reached by walking off one map onto the next is crossed the same way. Entered going
  north, it keeps north until this place's own northern join is found.
- **Otherwise:** for a place entered by a door, or once its onward join is known, it is the direction that leads
  furthest from where the player came in, by the tiles seen so far. It never points back the way the place was
  entered.

In the world's options, the heading orders the explore directions the way a goal's `toward` already does, with the
hint "(the way on)". A goal's own direction still wins.

## Measured: replayed logs (`scripts/heading_check.py`)

For each new place a run found by walking, was it found in the direction the heading named just before? Random is
25%.

| crossing | heading named it | another way | share |
|---|---|---|---|
| joins (walked off one map onto the next) | 11 | 12 | **48%** |
| doors | 18 | 40 | 31% |

- **Joins** are what the heading is for, and it names them about twice as often as chance. Most of those come from
  Aevilia's Jev run (8 of 12). On Pokemon it was 0 of 3: the first join, from Pallet Town onto Route 1, comes from a
  town entered by a door, where "furthest from the door" pointed elsewhere.
- **Doors** are near chance. A door is found wherever it is, and the place book's noise doors (gap C8) are counted
  here too.

On Route 1 itself, the place is entered by the join going north, so the heading is north for the whole route. The run
took the heading's way in 123 of 440 explore picks across the Pokemon run. With the heading ordering the options,
both the top pick and Jev see north first. Whether that crosses Route 1 in fewer battles is for a live run to show.
This replay cannot.

Not built: avoiding tiles where encounters start (grass). The run met its 10 Route 1 battles on 10 different tiles,
too few to learn a patch from in one route.

## Call site (long-horizon thread)

The patch is `pokemon-red/world-heading.patch`, against the long-horizon `world.py` at 4af85f7. It:

- adds `self.heading = Heading(self.book)` in `__init__`, and again after the book is loaded;
- in `options()`, when the goal gives no `_toward`, uses `self.heading.toward(here[0])` with the hint "(the way on)".

With it applied, the suite passes (158 passed, 4 skipped).
