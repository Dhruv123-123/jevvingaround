# Battle choice by the other side's bar (second-pass gap C11)

`anygame/battle.py` ranks a menu's entries by what each one's play-out did to the other side. It knows no game, no
move and no side. Pokemon shows the enemy's health only as a bar, so the "number" is read from the screen.

## How it decides

The menu reader already plays every entry out until the game asks again (`playout.py`, gap 2). The play-out now
also keeps the screen it ended on. For one menu:

1. **Bars.** On each end screen, a bar is a run of one colour, one to four pixels tall, with one other colour all
   along it above and below, not touching the left edge. Its full length is the longest it has been seen. Text
   rows and box interiors fail the "one colour all along" test.
2. **Same screen.** Only play-outs that ended on the same screen, apart from the bars' own rows, are compared. Two
   entries that ended on different screens give no ranking.
3. **Against the siblings.** For each bar, the entry that left it longest is the baseline. An entry scores how much
   shorter it left the bars. What every entry does alike cancels: the other side's move, the redrawn menu.
4. **Whose bar.** A bar is the player's own when it alone matches the share of one of the player's shown numbers
   ("16/ 19") after every play-out of a menu, in two menus. Lowering the player's own bar counts against an entry.
   A bar that once did not match is never the player's.
5. **Ending.** A play-out that leaves the scene, with the player's numbers above zero, from a screen showing a bar
   some entry has lowered before, ended the fight and ranks first. Leaving any other screen is closing a menu and
   scores nothing.

Labels are not remembered across turns. Pokemon's move-list cursor box reads the PP ("35/35"), and the cursor stays
where it was last.

## Measured

`scripts/battle_replay.py` plays whole fights from save states: 20 seeds, each waiting a different number of frames
first, so hits, misses and the other side's moves differ. RAM drives the menus the same way for every policy and
grades the result; the chooser sees screens and text only (`tiletext` with the finished Pokemon glyph book, no
labeller).

| fight | by the bar (battle.py) | always the cursor's move | random move |
|---|---|---|---|
| Rival (Squirtle vs Bulbasaur, TACKLE / TAIL WHIP) | **18 / 20** won, HP left 166 | 15 / 20, HP left 131 | 13 / 20, HP left 76 |
| Route 1 wild (Bulbasaur, TACKLE / GROWL) | **19 / 20**, 3.7 turns | 19 / 20, 3.7 turns | 14 / 20, 6.0 turns |

- **The rival.** The bar ranked 158 of 176 turns. It chose TACKLE on 153 turns and TAIL WHIP on 23: those were
  turns where TACKLE missed in its play-out, or where both entries left the enemy bar alike. Always-TACKLE is what
  the cursor gives here, because the cursor starts on TACKLE and stays there. The live Jev run did not: it picked
  GROWL on roughly 1 turn in 8 (part 2's battle text; OCR, approximate) and lost the rival.
- **Route 1.** The cursor's move is already TACKLE, so the bar can only match it. Against random choice it saves
  2.3 turns a fight. On Route 1, 88% of ticks were battles.
- **Silent where nothing is a fight** (`scripts/battle_silence.py`: each state's first entries, single directions,
  six moments each). Aevilia choice, object and overworld states: 0 of 18 ranked. Renegade Rush, Tobu Tobu Girl:
  0 of 12. GBHack in play (a roguelike with a heart counter, no bars): 0 of 6.

## Call site (for long-horizon)

`/mnt/project-files/anygame/pokemon-red/menu-battle.patch` applies to long-horizon `dcd313a`. With this branch
merged, the full suite passes (164 passed, 4 skipped). It does three things:

- `MenuTracker.__init__`: `self.fight = Fight()`.
- `explore`, in the play-out loop: `effects[i] = self.fight.effect(str(i), r)`. After the loop, `self.fight.rank(effects)`.
  The top entry's play-out text gets `fight.say(...)` ("a bar 100% → 83% (lower than after the other choices)") and
  `hurts_most`.
- `read`: that pick's landing gets " [lowers the other side's bar most]" and sorts first after upkeep's exits.

On the rival's move menu the landing reads: `pick_1 entry 1 of 2 → played on: '... used TACKLE' ...; then asks
again (10.3 s); a bar 100% → 83% (lower than after the other choices) [lowers the other side's bar most]`.

## Limits

- **One sample per entry per menu.** A miss in the one play-out reads as "does nothing" for that turn. Several
  samples (`play_outs` with delays) would average it, at 2–3x the play-out time.
- **Brock is not replayed.** No save state reaches him yet. His Onix takes little from TACKLE. The rule picks
  whichever move lowers the bar more once Bulbasaur has VINE WHIP, but that is inferred.
- **Numbers without a slash** ("19 19" from a weak read) do not identify the player's own bar. In that case the
  player's bar is treated as the other side's. Siblings still cancel most of it, because the other side's move
  usually lands the same way.
