# What each button does to the player (gap 5)

A world tracker that moves one tile per d-pad press cannot play a platformer, a racer, or Pokemon on a bike. There, A
is a jump, B held with a direction is a run, a held direction keeps going, and a ledge carries the player two tiles.
On the held-out action games the agent got about 90 presses in and still could not tell a jump from a step.
`anygame/motion.py` learns this by trying each input from a save state. Nothing in it knows a game.

## How it works

`learn(device)`, about 0.5 s of wall time:

1. From a snapshot, hold each input for 8 and for 32 frames, and record memory every 2 frames. The inputs are each
   direction, A, B, and a direction with A or B. The memory is work RAM, the sprite table and high RAM.
2. Find the player's axes. x is memory that answers right by moving one way in small steps and left the other way,
   compared with just waiting. One side may be blocked (a wall), which counts only for memory that holds still while
   the player waits. y is found the same way from up and down.
   - The Game Boy's sprite table says which bytes are a sprite's x and y, and that a sprite's x grows to the right.
     A sprite byte (where the player is drawn) is preferred, and a copy of a sprite byte elsewhere takes its role.
   - In a side view, up and down move nothing. y is then the sprite y paired with the x, or memory that A or B moves
     up and brings back.
3. Describe each input relative to waiting: how far, how fast while held, how far a short tap goes, whether it was
   pushed back, and whether y went up and came back (a jump), with its height and time in the air.
4. Put the game back exactly as it was.

`describe(m)` gives one line per input. `scripts/motion_check.py <rom> <state>` prints them.

## Results

All four were read from save states with no game named. Units are the game's own: pixels in all four.

| game (state) | what it learned |
|---|---|
| Pokemon Red (Red's room) | a tap walks 16 (one whole tile, finished after release); held, it keeps walking at 0.94 a frame; up stopped after 16 (the table); down blocked (the wall); A and B move nothing; B with a direction does not run |
| Aevilia (first house) | a tap moves 8, held 0.97 a frame: no tile snapping, so a tile of 16 takes a 16-frame hold |
| Tobu Tobu Girl (plains, held-out) | left and right steer about 1.9 a frame in the air; B is a jump (45 up, 24 frames in the air); A with a direction dashes (42 in an 8-frame tap); up and down do nothing |
| Renegade Rush (road, held-out) | left steers 0.81 a frame; right steers 0.38 and is pushed back from +19 to +4 (another car or the road's edge); up and down move a value by 24 each way that is not the car's sprite (the road's speed or scroll, inferred); A and B do nothing here |

Axes found, as memory addresses: Pokemon 0xFFAE/0xFFAF (the screen scroll, which follows the player), Aevilia and both
held-out games the player's sprite in the sprite table (0xFE11/0xFE10, 0xFE01/0xFE00). The grader's own Pokemon
position (0xD362/0xD361) moved the same two tiles; it is used only for checking.

Scripted tests (`test/test_motion.py`) cover a platformer (walk 1 a frame, run 2 with B, jump 24) and a tile walker
(a tap is a whole tile).

## Limits

- One save state says what inputs do there. Pokemon's Surf, bike and ledges need states from later in the game; a
  ledge shows as a step that goes 32 instead of 16.
- The only memory layout it knows is the Game Boy's sprite table, which is hardware, not a game.
- Several buttons at once go through the emulator's own buttons, because the device has no several-buttons call
  yet (`device.hold_keys(keys, frames)` / `release_keys(keys)` are used when a device has them).
- A racer's speed is a value, not a position. It shows as the y axis moving, which is labelled north and south.

## Call sites (for the long-horizon thread)

- Once per new kind of screen where the player moves (the world tracker's screen kind is walk, or the position is not
  known yet), call `m = motion.learn(device)`. Put `motion.describe(m)` in the decider's context, and offer the inputs
  that do something other than a step (a jump, a dash, a run) as options alongside the walks.
- The world tracker's `step_hold` can come from the tap distance: Aevilia moves 8 per 8-frame tap, so one 16-pixel
  tile needs a 16-frame hold.
