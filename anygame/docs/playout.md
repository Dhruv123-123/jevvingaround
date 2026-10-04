# A choice judged by where it leads: play it out to the next decision

2026-10-04, branch `claude/anygame-pokemon-full-run-gaps-85kn4w` (PR #16). Full-run gap 2 (`full-run-gaps.md`).
Before this, the menu reader judged a choice by the screen 90 frames after pressing A. A battle move needs several
seconds of text before the game shows what it did, so every move read as "the screen changes, no new text".

## How it works

`anygame/playout.py`, `play_out(device, keys, read_text)`:
1. From a save state, it presses the choice's keys and lets the game run.
2. Whenever the screen stands still, it checks whether the game is asking for a choice: a direction changes the
   screen differently from waiting (`asks`, two branches through `device.branch`). If so, the play-out ends there.
3. Otherwise it presses A to page on.
4. It records every new text in order (read with `kind: tiletext`), plus the numbers on screen before and after.
5. It puts the game back exactly as it was.

`describe()` turns the result into one line for Jev. `play_outs()` plays the same choice after a few different wait
lengths, which samples the game's randomness. Nothing in it names a game. It uses only the device's public calls
(`snapshot`, `restore`, `press`, `wait`, `screen`, `branch`), so no device, probe or runner code changed.

## Measured (`scripts/playout_check.py`)

Pokemon Red, the rival battle in Oak's lab (`pokemon-red/states/rival-battle-menu.state`, made with a test-only
script that walks with the grader's RAM map). Text was read with the glyph book from the tiletext run.

| choice | what the play-out reports | game time | wall time |
|---|---|---|---|
| FIGHT | the move list opens (TACKLE, TAIL WHIP; TYPE/ NORMAL), then asks again | 0.9 s | 0.2 s once glyphs are known |
| FIGHT → TACKLE | "SQUIRTLE used TACKLE!" "Enemy BULBASAUR used TACKLE!", then back at FIGHT/ITEM/RUN | 7.9 s | 0.55–6 s |
| FIGHT → TAIL WHIP | "Enemy BULBASAUR's DEFENSE fell!" "SQUIRTLE's ATTACK fell!", then back at the menu | 11.9 s | 0.55 s |
| RUN | "No! There's no running from a trainer battle!", then back at the menu | | 8.7 s with labelling, then fast |
| ITEM | the empty bag (CANCEL only, not a choice), then back at the menu | 2.4 s | 0.2 s |

Glyphs not yet labelled still read as `?`: in the runs the last word of "fell!" read as "?e???". The wall times
that are seconds long include the first labeller calls for new glyphs.

Aevilia, the character select (`pokemon-red/states/aevilia-choice.state`): either character plays out through
"OKAY!" "I'LL LEAVE YOU WITH THE NARRATOR." "SEE YOU AND HAVE FUN!" "Ah." "Someone has arrived." "Then hello."
"Use the d-pad to move around." and ends when the player can walk (11.8 s of game time, about 1.1 s wall). B
does nothing.

## Where it plugs in

`perceive/menu.py` belongs to the long-horizon thread. Its `_outcome(device, keys, ...)` is the one call site:
`play_out(device, keys + [], read_text)` in place of `_play(..., total + settle)`, and `describe(result)` in place of
`_said`. The menu cache should key on the menu's text rather than its pixels, so a battle menu with new HP bars is
still the same menu.

## Limits

- One entry is one sample. `play_outs` with 3 delays costs about 3x the time.
- A screen with a single entry (an empty bag's CANCEL) is paged through, the same as a text box. That is
  deliberate, because one entry is not a choice.
- The enemy's HP is a bar, not a number, so in Pokemon it shows up only through the text ("fainted").
