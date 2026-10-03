# Long-horizon play: Aevilia with Jev, goals from dialogue, the Jev audit

2026-10-03, branch `claude/anygame-pokemon-longhorizon-cmt588`, PR #14 (stacked on #12), with discovery v2 from #12 merged.
Pack: `packs/gameboy` (one generic Game Boy pack, nothing about either game in it). ROM: Aevilia (homebrew). Pokemon Red: not run, because there is no ROM in project files yet.

## Result

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
