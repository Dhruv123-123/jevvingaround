# Using things: menu chains toward a named outcome (gap 4)

Late in a long game, progress needs a thing used rather than a place reached: a tree cut with a move a party member
knows, a guard who lets you pass once you hold a drink, an item taken out of a PC. Each is a chain of menu choices
(open a menu, pick an entry, pick another, confirm) whose end is an outcome the goal names. `anygame/chains.py` finds
such chains by playing them out from a save state. Nothing in it knows a game.

## How it searches

From the current moment:

1. Open something: A at what the player faces, or START.
2. At each menu, try its entries: the cursor places a direction reaches (pressed again and again until the cursor
   stops or comes round), each picked with A, plus the other buttons (B, SELECT, START), since a pause menu can list
   what each button does.
3. Play each pick out until the game asks again (`anygame/playout.py`). A pick that leads to a new menu is a node to
   go deeper from. A menu is something B backs out of; where B does nothing and the game still asks, it is the world,
   whose directions walk, and the search does not go deeper there.
4. Stop at the first chain whose result passes the test. It comes back with the exact presses and waits, so
   `replay(device, trace)` plays it for real. The game is put back as it was.

Breadth first, so the shortest chain wins, with a budget (`max_tries`, default 60 picks; `max_depth` 4).

Tests:

- `says(word, ...)`: a line tells of a gain (got, received, withdrew, learned, bought ...) and names the words. The
  gain words are English. A game in another language needs its own list.
- `moves(pos, d)`: after the chain (and B pressed to close what is still open), a step in direction `d` moves the
  player: the wall in front is gone.

## Walls tried again after a gain

The world tracker gives up on a wall after three bumps. A cut tree or a guard is such a wall until the player has
what opens it. `Gains(world).see(text)` watches the text each tick; when a line tells of a new gain, `reopen(world)`
makes every wall the tracker had given up on worth one more bump. A bump that is still refused gives up on it again.

## Results

Pokemon Red, from Red's room facing the PC (`states/reds-room.state` plus a short walk), test `says("POTION")`:
found in 19 tries, 2,338 emulator frames (39 s of game time), 23.5 s wall time including glyph labelling. The chain
was A at the PC ("turned on the PC.") > WITHDRAW ITEM > POTION > quantity, ending in "Withdrew POTION.". Replaying the
37 recorded presses and waits lands on the same screen. Along the way it also mapped the PC's DEPOSIT and TOSS, and
the START menu (POKéMON, ITEM, the player, SAVE, OPTION).

Aevilia, in the first house after the tutorial (`states/aevilia-house.state`), test: any gain. The search mapped the
pause menu, which lists buttons rather than a cursor (START: exit menu, B: save, SELECT: options), and B played out
to "DONE!" (a save). No item or gain exists this early, so nothing was found, in 6 tries and under 2 s. This is the
case that made play-outs end on "waits": a screen where neither A nor a direction does anything is a decision too,
and the search then tries the other buttons.

A Cut tree and an HM need a save from much later in Pokemon. The scripted test (`test/test_chains.py`) covers the
`moves` case: START > PARTY > CUT opens the wall, found in three picks and replayed.

## Found on the way: lookalike glyphs

The Pokemon glyph book read w as v ("Withdrev", "Hov many?") and the menu cursor as R. Both were labels trusted from a
single chat reading because the rest of the line agreed. Now, when a glyph's character is already held by another
glyph, the glyph needs two agreeing lines. Eight such one-vote labels were dropped from the shared book and relearned;
w now reads correctly and the others relearn as they come up. The cursor is still read as P in places, because that label had two votes. The rule only
stops new ones.

## Call sites (for the long-horizon thread)

- When a goal names a thing to get or use, or the agent has been blocked on the same edge for a while:
  `r = chains.search(device, read_text, chains.says(noun))`, or `chains.moves(pos, d)` facing the wall. If
  `r["found"]`, offer it to Jev as one option ("use: " + the steps' text) and play it with `chains.replay(device,
  r["trace"])`. One search costs up to `max_tries` play-outs and no model calls.
- Every tick: `gains.see(values.get("text", ""))`, with `gains = chains.Gains(world_tracker)` made once per run.

Check script: `scripts/chains_check.py <rom> <state> [--walk ...] [--then a] [--says WORD | --moves DIR]`.
