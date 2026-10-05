# Which place the player is in (C8, second pass)

The world memory keys every tile, wall and door by place. A goal like "enter a new place" or "go back to the lab"
only works if places match the game's maps. They did not:

- On the Pokemon run from power-on to Route 1, five maps (Red's house, both floors; Pallet Town; Oak's lab;
  Route 1) were **2 places**.
- In part 3 of that run, **27% of reads** were in a place that was mostly another map.

## Why

- **Maps that join without a door.** Walking off the top of Pallet Town onto Route 1 changes nothing the map
  signature is made of. The position jumps from row 0 to row 35, and the world recorded it as a warp inside one place.
  Route 1's tiles and walls landed on top of the town's.
- **Names that change on ordinary steps.** When the signature changed on a one-tile step, the world made the new
  name a permanent alias of the old place. That is right for a byte that changes with scenery. It is wrong for
  Pokemon's stairs, which land on the next tile, and for a map byte written a few steps after a join.

## The fix: `anygame/places.py`

`PlaceBook.see(signature, x, y, moves=, walking=, cut=)` returns a place id each read. Nothing in it knows a game.

- **Join.** The player moved the wrong way along the pressed direction by more than 4 tiles, and by more than the
  presses explain. That puts them on the next map, as a neighbour place. Joins are kept both ways, and
  `neighbours(id)` lists them.
- **Door.** A new name with a jump the walk cannot explain goes to the place last left with that name, if it has
  been seen near there. Otherwise it is a new place.
- **Door on trial.** A new name on an ordinary step could be stairs or noise.
  - If the old name returns on the same tile later, it was a door and stays one.
  - If the old name returns anywhere else, it was one place under two names. The two places are merged: a `merge`
    event is logged, and `canonical(id)` maps old ids to the merged one.
- **Forced move.** The position jumps with nothing pressed, to somewhere this place has not been, and the next read
  stands there too. The game has put the player elsewhere: a respawn after losing, or a scripted walk. It is a door
  marked `forced`, which upkeep (`upkeep.py`) uses to learn that a number's floor is fatal.
- **Late name.** A new name on the read right after a walk counts as that walk's door. Games write it a little after
  the step, as with Pokemon's position.
- `cut_between(before, after)` tells a scroll from a new scene, for a call site that has the two frames. Indoors in
  Pokemon it does **not** separate stairs from walking: both score 0.60–0.67 alignment. So the trial rule, not the
  frames, handles stairs. Doors to the outside do separate (0.06–0.29).

## Measured: the logged runs replayed against the grader's map

`scripts/place_check.py` replays each run's discovered signature and position through the book. It scores the
places against the grader's map, which is read only for scoring. "Mixed" is the share of reads in a place that is
mostly another map. "Places per map" counts splits; a split costs less than a mix, because nothing wrong is
remembered.

| run | game | maps | world memory: places, mixed | place book: places, mixed |
|---|---|---|---|---|
| Jev from power-on, part 1 | Pokemon | 4 | 2, 24.2% | 7, 0.7% |
| part 2 (to Route 1) | Pokemon | 4 | 2, 5.6% | 11, 0.6% |
| part 3 (Route 1) | Pokemon | 4 | 2, 27.1% | 11, 18.7% |
| stand-in, 1,500 ticks | Pokemon | 4 | 7, 25.3% | 40, 4.5% |
| map-signature run | Pokemon | 3 | 2, 11.7% | 9, 1.0% |
| run 2 | Aevilia | 3 | 11, 4.3% | 13, 0.8% |
| run 3 | Aevilia | 4 | 22, 4.0% | 33, 2.3% |
| top pick, 1,200 ticks (held-out; map = dungeon level) | GBHack | 2 | 4, 0.7% | 28, 0.3% |

Mixing goes down on every run. What is left:

- **Part 3.** Its signature names 0 for both house floors and the town at different times. That run predates the
  emulator thread's map-signature v3 and position fixes. No rule on names can separate maps that share one name and
  one coordinate frame.
- **GBHack (held-out) never left dungeon level 1.** Mixing is lower (0.3% against 0.7%), but the book splits much more. GBHack's discovered position still jumps (row 54, then -215). A jump that holds for two reads is taken as a forced move, so the book splits level 1 into 28 places.
- **The stand-in run splits maps** (40 places for 4 maps). Its signature changes value often, and each change on a
  step starts a door on trial. A split means a goal can call a known map new, so a split map gets explored twice. That
  is cheaper than a mix, where walls of one map block paths in another.

Pallet Town and Route 1 are now two places joined north–south in every run that crosses. "Go north into a new
area" can be met, and Viridian City will be another join.

## Door memory and routes (second pass, for going back)

A map signature that reads differently on a return used to give the same map a new place id, so a goal naming the
place could never be met. Two additions make a place reachable again:

- **Door memory.** Every door taken is kept as `(place, x, y) → (place, x, y, direction pressed)`, in both
  directions (out is the reverse of in). A door taken again from the very tile it was taken from, arriving on the
  very tile it arrived on before, leads where it led before, whatever the signature reads now. The match is exact:
  one tile of slack mixed more maps together (6.6% against 5.9%). Matching a door known from another place on the
  same tiles (`door_any`) raised returns known by 3 to 4 points but mixing by 0.3 to 0.7, so it is off.
- **`route(src, dst)`.** The first move on the shortest known way between two places, over joins walked and doors
  taken: `{"kind": "join", "dir"}` (walk off that side), `{"kind": "door", "x", "y", "dir"}` (stand on that tile
  and press `dir`), `{"kind": "here"}`, or `None`. A place entered on trial borrows the way of the place it was
  entered from, since it may be that place under a second name.

On the Pokemon logs, door memory raised the returns the book named as before from 65% to 69% (112 to 119 of 172),
with mixing flat (5.8% to 5.9%). The bigger gains came from the emulator side's map byte, which the book now gets
most of the time (see `docs/full-run-gaps.md`, "Going back where the text says", for every re-measure).

## A name switch on the same tile is not a door

The long-horizon run stalled at tick 45,700 inside Blue's house. The signature read switched while the player stood
on (3, 7), and the book recorded a door from place 2 at (3, 7) to place 82 at (3, 7). Routes and the frontier then
kept sending the player "through" it, back into the room it was standing in. In that checkpoint, 19 of the 56 doors
were like this.

The rule now:

- A door whose two ends are the same `x, y` is not recorded. The place change still happens (the event is logged);
  only the way through is not kept, because there is none.
- When a merge makes both ends of a door one place, the door is dropped.
- A saved book loaded with such doors drops them (`from_dict`), so old checkpoints are clean on resume.

On four stand-in logs, the returns known again went from 92% to 90% and mixing stayed at 7.0%: the dropped doors
were not carrying real returns. One suspicious one-step door, `(79, 2, 6) → (2, 2, 7)`, is still kept, since a real
staircase looks the same.

## Where it is used

`perceive/world.py` owns a `PlaceBook` (`World.book`). Every read goes through `World._place`, which passes the
directions pressed since the last read, whether the last action was a walk, and whether nothing was pressed (for a
late name). After each read, new `merge` events move `visited`, `blocked`, `walls_at`, `warps` and what was inspected from the old place
id to the merged one. The book is saved in checkpoints (`to_dict`) and loaded on resume.

`route()` feeds two options: the goal option when no door chain in the world memory reaches the goal's place
(`_route_option`), and, after 300 steps with nothing new, the nearest other place with unexplored edges.

Tests: `test/test_places.py` (joins, stairs on trial, late names, door memory, the same-tile rule, merged doors,
routing from a place on trial). Replays: `scripts/place_check.py`, `scripts/reentry_check.py`,
`scripts/goback_check.py`. None of them reads the grader's map except to score.
