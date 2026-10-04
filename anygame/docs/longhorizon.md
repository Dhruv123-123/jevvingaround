# Long-horizon play: Aevilia and Pokemon Red with Jev, goals from dialogue, the Jev audit

2026-10-03, branch `claude/anygame-pokemon-longhorizon-cmt588`, PR #14 (stacked on #12), with discovery v2 from #12 merged.
Pack: `packs/gameboy` (one generic Game Boy pack, nothing about either game in it). ROM: Aevilia (homebrew). Pokemon Red: not run, because there is no ROM in project files yet.

## Pokemon Red (2026-10-04): from power-on to Route 1 with a starter

Same pack (`packs/gameboy`), same code as Aevilia, nothing about Pokemon in the agent. The grader reads pret's RAM map for scoring only.

| run | decider | milestones (grader) | Jev spend |
|---|---|---|---|
| stand-in, 1,500 ticks | top pick | intro (93), left house (322) | $0 |
| **Jev, 1,500 ticks, audit on** | **Jev** | **intro (93), left house (292), starter (768), Route 1 (1207)** | **$0.033** |

The Jev run hit the target, leaving Pallet Town with a starter. In order, it:
- named both characters and went downstairs;
- walked north until Oak stopped it, then followed him to the lab;
- chose BULBASAUR;
- fought the rival's CHARMANDER and lost;
- left the lab and walked onto Route 1;
- won wild battles against Rattata and Pidgey, which took Bulbasaur to level 6 with $1,500;
- walked home to Red's house.

The run went from power-on to tick 700, then continued from its tick-700 checkpoint on a menu fix (logs in two parts). Pokemon Jev spend across every run today is about $0.15, including the runs that stalled.

The stand-in on the same code left the house too. It never walked north into the grass, which is the step that brings Oak out, so it never got a starter.

### What it took (each stall, and its fix)

| stall | side | fix |
|---|---|---|
| A tap only turns Red; the walk read as a menu | mine | held-press `walk_<dir>` options while the position is unknown |
| x bound to a wrong byte after going downstairs | emulator | discovery keeps a byte while it still passes (c66591a) |
| One map signature covered both floors, so upstairs walls hid the exit | emulator | doors are steps that rewrite rarely changed bytes (774030c) |
| Same, before that fix | mine | a refused step expires with its block |
| The town's signature changed on one-tile steps, making false doors | mine | a one-tile walking step is an alias, not a door |
| START-menu entries and the trainer card reopened 25–190 times | mine | a pick that returns to the same menu twice (directly or through one screen) is dropped |
| Goals re-set every 2 ticks because a menu redraw "left the place" | mine | place goals count only on a walk screen |
| "Don't go away yet!": Oak walked Red back 30+ times | mine | a walk that ends on its own start tile twice is dropped from that tile |
| Jev shuffled Red left and right on a "menu" where A did nothing | mine | when A does nothing for every entry, only walks and buttons are offered |

Also merged in: exact text from the screen's cells (menus read POKéMON/ITEM/RED/SAVE exactly), menu choices played on until the game asks again (FIGHT shows the move list), and numbers (goals can ask for HP or a level).

### Goals the writer set (Azure, 50 calls, 0 rejected, median 2.1 s)

The writer read the dialogue and set goals that match the game's story. Examples:
- "Go to the next-door professor and talk to him."
- "Choose one of the three Pokémon."
- "Defeat Gary's Charmander."
- "Choose FIGHT and use Tackle until the wild Rattata is defeated."
- "Go north into a new area."

The one miss was "Select NEWGAME" checked as `new_place`, which was given up. The starter goals checked `said: received` and were given up. The starter text reads "…received a BULBASAUR!", but that line was cut by the box, so the check never saw the word.

### The Jev audit (446 decisions)

| verdict | share |
|---|---|
| Jev and the top pick agreed | 49% |
| differed, same outcome 8 decisions later | 4.3% |
| differed, Jev's pick better | 2.9% |
| differed, top pick better | 1.6% |
| differed, not played out (cap of 30) | 42% |

Most decisive cases were on menus (12 Jev better, 6 top better). As on Aevilia, Jev's own judgment changed the outcome in about 5% of decisions and helped about 2:1 when it did. The run-level gap is larger: Jev got a starter and reached Route 1, and the stand-in did not.

### Next

- The rival battle was lost. Battle choices are now played out, so Jev sees "used TACKLE!" outcomes, but the goal check for "defeated" never fired. The writer should read the play-out text.
- Items and field moves (PR #19 chains) are not wired yet. Nothing before Viridian needs them.
- Next milestones: Viridian City, then Oak's Parcel.

Logs: `longhorizon/pk-jev-route1/` (part1-power-on with checkpoint-700, part2-resumed with out.json and the milestone saves, standin/). The earlier stalls are in `pk-standin5`, `pk-standin6`, `pk-standin7-lab` and `pk-jev-lostpos`.

## Aevilia (2026-10-03)

### Result

| run | decider | milestones (grader, never seen by the agent) | last milestone | Jev spend |
|---|---|---|---|---|
| stand-in, 1,200 ticks, discovery v1 | top pick | tutorial, room, downstairs, Startham (4 of 6) | Startham, tick 371 | $0 |
| stand-in, 900 ticks, discovery v2 | top pick | tutorial, room, downstairs, Startham (4 of 6) | Startham, tick 402 | $0 |
| **Jev, 900 ticks, discovery v2, audit on** | **Jev** | **tutorial, room, Startham, forest** | **Startham Forest, tick 471 (6.2 game-min)** | **$0.047** |

Jev's run reached Startham Forest, which is the grader's last milestone and the end of the demo's story. No earlier run had reached it. It also reached the player's room at tick 116, against tick 209 for the stand-in. It skipped two side milestones. The grader never logged "downstairs", probably because the run passed through that map between ticks. It also never entered "another house". So 4 of the 6 boxes are ticked, but the last one is among them, and the grader scores progress as 1.0.

## Where the earlier runs stopped, and what fixed it

1. **Discovery v1 (fixed in PR #12, not here).** In town the found x/y froze and the map signature churned, giving 21 "maps" for 4 real ones. The stand-in then pressed A on a misread screen 352 times.
2. **The pause-menu loop (run 3, fixed here).** Jev skipped the tutorial, so the position was still unknown in the player's room. The d-pad screens there read as a menu. Jev did what the dialogue said ("press START") and then looped forever: START opened the pause menu, START closed it, and so on, for 780 ticks. Two fixes went in:
   - A screen where only a button works is now a menu question too. Jev sees what A, B, START and SELECT each do, found by trying them from a save state.
   - While the position is unknown, walking is offered beside the menu entries, and walking is what discovers the position.
3. **Map-signature churn during dialogue (my side).** The world memory now treats a new signature that appears without the position jumping as another name for the current place.

## The Jev audit (run 4)

At each decision the run compared Jev's pick with the top-ranked pick. When they differed, it played both forward 8 decisions from a save state with the stand-in, then put the game back. Repeats of the same disagreement in the same place reuse the first verdict.

| verdict | decisions | share |
|---|---|---|
| Jev and the top pick agreed | 323 | 45% |
| differed, same outcome 8 decisions later | 155 | 22% |
| differed, Jev's pick better | 14 | 1.9% |
| differed, top pick better | 4 | 0.6% |
| differed, not played out (cap of 30 audits reached) | 224 | 31% |

Where it mattered:

| screen | Jev better | top better | same |
|---|---|---|---|
| menu / choice | 11 | 2 | 146 |
| walking | 3 | 2 | 7 |
| button | 0 | 0 | 2 |

What the 18 decisive cases looked like:
- Jev picked "walk" over the stand-in's "press START" on the room screen at tick 201. That is the pick that broke the run-3 loop.
- Jev chose an exploring direction that found the door out of the house (tick 351: novelty 39 vs 9).
- The stand-in won on the title screen. Jev backed out of the file select once (tick 31).
- A three-tick stretch at the house door (ticks 357–359) went both ways, one pick each way, because the same pick was replayed from slightly different states. Treat it as noise at this horizon.

Reading: on Aevilia Jev's judgment changed the outcome in about 3% of decisions, and helped roughly 3:1 when it did. The share that matters most is the run-level one. Jev reached the forest and the stand-in did not, in the same ticks on the same code. The biggest single difference was Jev choosing to walk when the screen was ambiguous.

Cost of the audit: 30 played-out audits took 566 s of wall time, and the audit uses no Jev calls. A full-coverage audit would cost about 19 s per new disagreement.

## Goals from dialogue (Azure gpt-5.6-luna)

The writer made 9 calls, with a median of 1.96 s. No answer was rejected. Goals it wrote:

1. "Leave this place." Done when the player is somewhere other than where the goal was set (reached).
2. "Go to a new area." Done on entering a place not entered before (reached).
3. "Leave this place." Same check as 1 (reached).
4. "Go to a new area." Same check as 2 (reached).
5. "Go to a new area." Same check as 2 (reached).
6. "Explore the surroundings and enter a new area." Same check as 2 (given up after 200 ticks).
7. "Talk to someone in this area." Done after one new line of dialogue (reached).
8. "Leave Startham Forest and enter a new area." Same check as 2 (open when the run ended).

Note the 8th goal. The writer named the forest from what was on screen; it never saw RAM. In the stand-in run it also wrote place- and line-targeted goals ("Go to the house and enter it", target a known place, reached; "Talk to the warrior again", target the place that line was said). Aevilia's dialogue rarely asks for anything specific, so most goals are "explore". Pokemon's dialogue gives the real test: Oak's lab, the parcel, Brock.

## What is built (PR #14)

- `memory.py`: every line the game said, with the place and tile where it was said, plus places and events.
- Checkpoints, used with `--checkpoint DIR --checkpoint-every N`, continued with `--resume DIR`. Each one saves the emulator state, world memory, dialogue, goals, the discovered RAM map and the audit. The checkpoint for this run is in `longhorizon/jev-run4/checkpoint/`.
- `goals.py`: the chat model writes the next goal as a condition the code checks. The conditions are `new_place`, `leave_place`, `place`, `said`, `talks`, `screen` and `any`. The optional targets are `toward`, `place` and `line`. Every answer is validated, and the model never presses a button.
- `perceive/menu.py`: any choice is one question. Each entry's label and outcome are found by trying it from a save state. An outcome says whether it leads back to a screen seen before, loads a new scene, or does nothing. Entries that do nothing are not offered.
- `audit.py`: `--audit N`, the comparison above.
- Tests: 9 new; the full suite passes (105 passed, 4 skipped).

## Next

- **Pokemon Red** runs the moment `/mnt/project-files/roms/pokemon-red.gb` exists, with the same pack and the same command. The target is leaving Pallet Town with a starter.
- **Text.** OCR of the 8 px font is the weakest read ("PRESS" comes back as "PREAT"). Reading the tile map and learning each glyph tile once would fix it. That belongs to the device thread.
- **Audit coverage.** It stopped at 30 played-out cases. Running it with a higher cap on the Pokemon run would cover more decisions.

Logs:
- `longhorizon/jev-run4/`: `log.jsonl`, `log.jsonl.goals.jsonl` (each writer call and its answer), `out.json`, `checkpoint/`.
- `longhorizon/standin-top3/`: the stand-in run on the same code.
- `longhorizon/jev-run3-stall/`: the pause-menu loop run.

Command:
`anygame play packs/gameboy --device pyboy://aevilia.gbc --sensor jev --audit 8 --audit-max 30 --checkpoint ck --checkpoint-every 100 --max-ticks 900` (fresh discovery).
