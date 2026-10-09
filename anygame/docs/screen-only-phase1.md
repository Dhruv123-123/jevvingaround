# Screen-only phase 1: press-and-watch, a screen agent, Azure advice

Branch `claude/anygame-screen-only-phase1-cbd753`, draft PR #33 on the #31 branch. The agent sees pixels and presses
buttons; RAM is read only by the graders. Spend so far: **$0.57 Azure of the $100 budget**, $0 Jev.

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

## Cost per game-hour

Advice is the only paid part: at most 150 calls ($0.06) per 1,500-press run, so under $0.25 a game-hour.

## Next

Pokemon past Route 1 (Viridian, the parcel), fewer wasted presses in menus and small rooms, object labelling on Azure.

Data: `screen-only-phase1/` (captures, watch scores, held-out runs).
