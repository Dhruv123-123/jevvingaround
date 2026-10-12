# Screen-only phase 1: press-and-watch, a screen agent, Azure advice

Branch `claude/anygame-screen-only-phase1-cbd753`, draft PR #33 on the #31 branch. The agent sees pixels and presses
buttons; RAM is read only by the graders. Spend so far: **$16.6 Azure logged since Oct 9 20:00Z, of the $100 budget**, $0 Jev.

## 1. Press and watch on pixels (`anygame/perceive/watch.py`)

After each press the watcher finds the background shift (phase correlation plus step-sized candidates), the sprites
that moved (changed pixels explained by a displacement whose source also changed, ghosts on tiled floors dropped),
links them into tracks and calls the player the track that follows the d-pad on both axes. A press after which
nothing at all changed, shortly after walking, is a bump. A walk book keeps walk/block votes per screen cell;
any cell ever stepped onto is ground.

Scored against OAM/position truth (`scripts/screenonly_watch.py`):

| game | player recall | precision | walk verdicts | walk book right |
|---|---|---|---|---|
| Pokemon (Blue's house save) | 0.87 | 0.80 | 336/336 | 96.6% |
| Pokemon (power-on) | 0.95 | 0.86 | | 94.4% |
| Aevilia | 0.80 | 1.00 | 223/223 | 88% |

Tobu, PostBot and Renegade have noisy sprite truth; GBHack has no sprites.

## 2. Screen agent (`anygame/screen_agent.py`)

A novelty explorer on a graph of states. A state is the player's place (room fingerprint at the last scene change
plus camera odometry, in units of the measured step) or, without a player, a tolerant screen fingerprint (8x8 grey
blocks, at most 3% different). It plans to the nearest state with an untried button, drops buttons that never change
anything in a kind of state, and lets screens settle for up to 3 frames.

Distinct RAM places reached in 1,500 presses, mean of 5 seeds:

| game | random | agent | agent + advice |
|---|---|---|---|
| Pokemon power-on | 91 | 135 | 94 |
| Pokemon, Blue's house save | 113 | 145 | 161 |
| Aevilia | 48 | 50 | 71 |

## 3. Advice from Azure

After 30 presses with no new state the agent sends the frame to gpt-5.6-luna (low reasoning), which answers 1 to 12
presses. It remembers its earlier advice and whether it found something. Capped at 150 calls a run and 2 per screen;
about $0.0004 a call.

## 4. Scores

Held-out score, screen+advice, 5 seeds, 900 s / 1,500 presses ($0.22 for all 30 runs):

| game | random | agent | normalised |
|---|---|---|---|
| Tobu Tobu Girl | 0.56 | 0.56 | 0 |
| PostBot | 0.40 | 0.40 | 0 |
| Renegade Rush | 0.24 | 0.40 | +0.21 |
| GBHack | 0.36 | 0.32 | -0.06 |
| Aevilia (dev) | 0.08 | 0.20 | +0.13 |
| Pokemon Red (dev) | 0.15 | 0.24 | +0.11 |

Held-out median 0.0 (no-advice runs gave +0.03). Pokemon Red screen-only reached Route 1 on 3 of 5 seeds; random
reaches it on none. A 7,000-press power-on run picked a starter by press 2,188-2,300 and reached Route 1 by
3,405-4,618.

## 5. Notebook and heading (commit 4a7cf78)

The advisor now keeps a notebook (a goal and a few notes, handed back on every call), may answer with repeats
("up*6", up to 30 presses), and names a heading. While the heading holds, the frontier search prefers open places
that lie that way (distance minus 2x progress), and the advisor is asked again every 200 presses.

Pokemon Red from Blue's house, 5,000 presses, 8 seeds (`scripts/screenonly_route1.py`):

| | Route 1 | Viridian City | northmost Route 1 y (median, 0 = top) |
|---|---|---|---|
| advice, no heading | 8/8 | 0/8 | 28 |
| advice + heading | 7/8 | 2/8 | 14 |

From power-on, 15,000 presses, 6 runs: starter and Route 1 on all, Viridian City on 3 (presses 4,425, 4,652,
13,859), Route 22 on 1. About $0.11 of Azure a run. Aevilia places in 1,500 presses with advice: 71 to 79.

Tried and dropped (no gain on the same measures): snapping the odometer to a screen seen before when re-entering a
room (rooms in one house look alike, and the merge hid new ground), a mode that heads straight out of battles and
menus (fewer places explored), following advised walks closed-loop around walls, and counting buttons tried on a
near-identical screen as tried. Battles still take about 30% of presses on Route 1.

## 6. Advice sooner and more often (commit d2a456d)

Asking after 10 stale presses (was 30) and refreshing the heading every 50 presses (was 200). Held-out score,
screen+advice, 5 seeds, normalised against random:

| game | before | after |
|---|---|---|
| Tobu Tobu Girl | 0 | +0.09 |
| PostBot | 0 | 0 |
| Renegade Rush | +0.21 | +0.16 |
| GBHack | +0.06 | +0.06 |
| **held-out median** | **+0.03** | **+0.08** |
| Aevilia (dev) | +0.17 | +0.39 |
| Pokemon Red (dev) | +0.125 | +0.125 |

Medium reasoning instead of low did not help (PostBot 0, Aevilia +0.30). PostBot stays at random: the advisor
cannot place the editor cursor reliably from the picture. Held-out runs are wall-time bound (900 s), so each advice
call costs presses; about 40 calls fit in a run.

## 7. Step grid (commit 26f7fb0, off by default) and 30,000-press runs

A faint grid on the advisor's picture, one player step per square, with the player's square named. Pokemon from
Blue's house, 5,000 presses, 16 seeds: Viridian 4/16 with the grid vs 2/16 without, and half the presses spent in
battles (854 vs 1,744 a run). On the held-out harness over 10 seeds it scored a little lower (Aevilia 0.24 vs 0.32,
Pokemon 0.21 vs 0.25), so it stays off until a longer measure decides.

From power-on with the grid, 30,000 presses (about 2 hours of wall time and $1 of Azure each), 4 seeds: Viridian
City on 3 (presses 5,281, 6,730, 15,799), Route 22 on 2, the parcel errand on none. The advisor's goal stays
"head north to Pewter", which the game blocks until Oak's parcel is delivered; nothing told it that, and no
game-specific hint is allowed.

Asking the advisor to name the game and set goals by its story (10,000 presses from Blue's house, 8 seeds each)
sent it to Oak's lab more often (4/8 vs 1/8) but reached Viridian no more often (2/8 vs 3/8) and the Mart on none
either way; dropped.

## 8. Story memory (tried, dropped)

A journal kept for the whole run: the advisor names the area each call and adds lasting facts (what someone said,
items, events, blocked ways), and sees up to 6 of the distinct screens since its last call, so dialogue the explorer
pressed through is read. From power-on, 15,000 presses, 4 seeds each:

| variant | Viridian | Mart | presses in Oak's lab |
|---|---|---|---|
| earlier runs without journal (8) | about 2 in 4 | 0 | |
| journal + goals set by the game's story | 1/4 | 0 | 6,458 on seed 1 |
| journal only | 0/4 | 0 | |

The model does recognise Pokemon from the title screen and knows the parcel errand, but it misreads where it is
(it set "heal at the Viridian Pokemon Center" while still in Pallet Town) and the journal fills with screen
descriptions; following that memory cost progress. The Blue's-house save hides the title screen, so game knowledge
must be measured from power-on.

## 9. Cheap reflex knobs for the action games (tried, dropped)

Held-out runs stop on the game-frame budget (36,000 frames), not wall time, so press choice matters more there than
advice. Screen agent without advice, 5 seeds, against the same agent with defaults (in brackets):

| game | long presses (4x hold) | no settle wait |
|---|---|---|
| Tobu Tobu Girl | 0.52 (0.52) | 0.60 (0.52) |
| PostBot | 0.40 (0.44) | 0.40 (0.44) |
| Renegade Rush | 0.28 (0.32) | 0.32 (0.32) |
| GBHack | 0.24 (0.36) | 0.28 (0.36) |
| Aevilia | 0.28 (0.16) | 0.20 (0.16) |
| Pokemon Red | 0.23 (0.21) | 0.19 (0.21) |

Both within noise or worse on the held-out games. Moving Tobu or PostBot past random looks like it needs a policy
that learns from play, not a setting.

## 10. Place recognition (tried, not committed)

The advisor names the area on each call; the name sticks to that screen and room, and later calls are told by
pixels which named place the screen matches (or that it is new) and which places led to which. From power-on,
15,000 presses, 4 seeds each:

| | Viridian | first Viridian press | Mart |
|---|---|---|---|
| with place recognition | 2/4 | 3,702 and 12,710 | 0 |
| without | 3/4 | 12,780 to 14,726 | 0 |

No clear gain; the patch is kept at `screen-only-phase1/place-recognition.patch`.

## 11. Walking to a square the advisor names (commit e47d8e1, `targets`, off by default)

The advisor can answer with `"target": [column, row]` on the step grid and `"then"` presses for arrival; the agent
walks there itself, step by step, going around steps it has seen blocked. Skill test (`scripts/screenonly_skill.py`)
from Viridian City saves made by `scripts/pokemon_fixture_walk.py` (a RAM walker used only to make test saves), goal
"go into the Poke Mart", graded by the map byte:

| start | targets on | targets off |
|---|---|---|
| city entrance, 600 presses | 1/4 | 0/4 |
| 5 steps from the door, 300 presses | 3/6 | 1/6 |

Each run cost about $0.01. The failures are misreading the picture, not walking: the advisor sees a barrier that is
not there, or walks into the house next door and takes it for the Mart.

Held-out check with targets on (seeds 1-3, `heldout/screen-advice-targets-runs.jsonl`): PostBot, Renegade Rush and
GBHack score the same as without (0.4 each), Tobu 0.53 against 0.6 (noise). Aevilia, a dev game, drops from 0.53 to
0.2, so targets stays off by default.

## 12. Oak's parcel, stage by stage

The skill test grades the errand by the bag (MAP `parcel`: the parcel enters at the Mart and leaves in Oak's lab).
Starts are fixture saves (`states/` in the data folder), goal text seeded into the advisor's notebook:

| stage | targets on | targets off |
|---|---|---|
| near the Mart: get the parcel, 6,000 presses | 3/6 picked up, 3 of those reached the lab, 0 handed over | 2/6 picked up |
| same, 1,000 advice calls instead of 150 | 2/6 picked up, 0 handed over | |
| lab door with the parcel: hand it over, 600 presses | 3/10 | 1/4 |

The goal survives in the notebook all the way (logged in `skill-handover/`). The failures are reading the room: the
advisor talks to an aide or Mom and takes it for Oak, reads a bookcase message as Oak's, or decides the game wants
START. Each stage alone works some of the time; chained, the odds multiply down to near zero. About $0.02 a run at
the lab, $0.15 for the 6,000-press errand.

## 13. The rest of the route to the first badge, stage by stage

The fixture walker (RAM, test setup only) hands over the parcel, walks Route 2, wins the Viridian Forest trainer
fights by mashing A, and reaches Pewter with Bulbasaur at level 11. Saves: `route2`, `forest`, `pewter`, `gym-door`.
Skill tests from those, targets on:

| stage | result | how runs ended |
|---|---|---|
| Viridian Forest to Pewter, 5,000 presses | 0/6 | 2 lost a battle and woke up at home, the rest wandered the forest |
| gym door to the Boulder Badge, 3,000 presses | 0/6 | all 6 lost a trainer battle |
| same, advice every 10 presses and on every battle screen | 0/6 | 4 lost a battle |

The fixture's own A-mashing also loses in the gym: Bulbasaur at level 11 with Tackle first is not enough for Brock's
side of the gym. So past the parcel errand, the next missing skill is battles: choosing moves (Leech Seed, Vine Whip
at level 13), healing at the Pokemon Center, and training up before the gym. Spend on sections 11-13: about $6.6.

## 14. The gym with a fights hint (commit 71d5cf0, `fights`, off by default)

`fights` adds a paragraph to the advisor prompt: read the fight, open the attack list and pick an attack that suits
the matchup, watch both health bars, heal or train on easier foes when a fight keeps being lost. With it the advisor
stops mashing A and picks moves (it chose Leech Seed against Diglett). All from the gym door, advice every 10 presses
and on every battle screen, 3,000 presses:

| start | Boulder Badge |
|---|---|
| as the fixture walker left it (Bulbasaur level 11, 21 of 34 HP) | 0/6 |
| same, full health | 0/6 |
| full health, and Vine Whip in place of Growl (learned at level 13) | **2/6** (after 657 and 2,703 presses) |

The two health and moves changes are test setup written into the save, the way a player would arrive after a
Pokemon Center and some training. So with a fair team the screen-only agent can win the first badge; what it still
lacks is getting that team itself (training to level 13 and healing first). About $0.35 a run.

Held-out check with `fights` on (seeds 1-3, `heldout/screen-advice-fights-runs.jsonl`): PostBot 0.4 = 0.4, Renegade
Rush 0.47 vs 0.4, GBHack 0.33 vs 0.4, Tobu 0.53 vs 0.6, all within noise; Aevilia 0.2 vs 0.53 (as with targets), so
`fights` stays off by default.

Training to level 13 from Pewter (the gym's real prerequisite), goal seeded, `fights` and `targets` on:

| start | presses | level 13 | how runs ended |
|---|---|---|---|
| as saved (21 of 34 HP), 150 advice calls | 5,000 | 0/6 | 4 lost a battle and woke up at home |
| full health, up to 1,500 advice calls | 5,000 | 0/6 | none lost; 4 wandered Route 2 and the Forest, 2 went into Pewter buildings |
| full health, up to 3,000 advice calls | 20,000 | **3/4** (after 11,963 to 16,022 presses) | the fourth ended at level 11 with 4 HP |

Viridian Forest again, with fights on: 15,000 presses and up to 3,000 advice calls, 0/4; advice every 10 presses,
10,000 presses, 0/4 ($1 a run). Every run turned back south through the gate within the first few thousand presses
and never found the north exit; the Forest is a maze of trees the advisor cannot read a path through.

So every stage of the first badge now works some of the time on its own except the walk through Viridian Forest:
parcel pickup 3/6, handover 3/10, Forest 0/6, training to level 13 3/4, Brock with that team 2/6. About $0.55 per
20,000-press training run.

## 15. A learned walker for Viridian Forest (`walker`, off by default)

The Forest stage failed 0/14 because the advisor cannot read a path through trees. So the agent now gets a small
learned walker, pixels in and one step out, trained on demos rather than on RAM at play time:

- `scripts/pokemon_fixture_walk.py` (the RAM test helper) walked the Forest 40 times from random starting wiggles,
  recording each screen and the step that moved the player (`FIXTURE_RECORD`); 39 walks made it, 26,931 screens.
- `scripts/pokemon_walk_labels.py` joins the squares those walks saw into one graph and relabels every screen with
  the step on a shortest path to the north exit (628 squares, longest way 154 steps), so the demos' detours drop out.
- `anygame/walk_book.py` shrinks a frame to a 36x40 grey picture and answers with a weighted vote of the 5 nearest
  demo screens, or nothing when no demo screen is close. `ScreenAgent(walker=book)` takes that step before its own
  explorer and the advisor, and backs off for 8 presses after two learned steps that go nowhere.

RAM is used only to make and label the demos, like the stage graders; the agent sees pixels only.

Viridian Forest to Pewter City, fights on, 5,000 presses, 150 advice calls:

| walker | reached Pewter | presses to Pewter | Azure per run |
|---|---|---|---|
| off (section 13/14) | 0/14 | - | about $0.10-1 |
| **on** | **5/6** | 654, 1,122, 1,193, 2,433, 3,022 | $0.015-0.10 |

The sixth run went back and forth across the north gate between the Forest and the gatehouse, then lost a fight
and woke up at home. The book is game-specific data (one dungeon's demos), not game-specific code: the same scripts
make a book for any maze given a walk helper for that game. It does nothing on the held-out games (no book is given).

## Where this leaves things

The explorer plus a cheap advisor gets through Pokemon's opening and to Viridian City from pixels alone, and lifts
the held-out median a little. What stops it now is long-horizon story knowledge (the parcel errand), and the
held-out action games (Tobu, PostBot) where a slow advisor cannot steer. Each further idea above cost about
$2 and 1-2 hours to measure on 8-16 seeds, and the last several moved nothing outside noise.

## Cost per game-hour

Advice is the only paid part: at most 150 calls ($0.06) per 1,500-press run, so under $0.25 a game-hour.

## Next

Pokemon past Route 1 (Viridian, the parcel), fewer wasted presses in menus and small rooms, object labelling on Azure.

Data: `screen-only-phase1/` (captures, watch scores, held-out runs).
