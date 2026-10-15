# Typed decider in the screen-only agent

Dhruv, Oct 15: put Jev or the OpenAI typed decider back in for the decisions, with the hashed caches, so the agent is
not just a vision model playing the game.

## What changed

Before, the screen-only agent (`anygame/screen_agent.py`) explored on its own and, whenever exploring went stale
(10 presses with nothing new, or every 50 presses in a place), sent the last three screens to the Azure vision model
(gpt-5.6-luna) and played the presses it wrote back. The vision model chose every move that mattered.

Now (`anygame/typed_screen.py`, PR #61) the two jobs are split:

- **The vision model only names screens, once each.** When the agent is about to decide and the current screen has
  no label, the vision model writes one: kind (title, menu, dialogue, battle, map, other), where it is, the words on
  screen, what is where, and 2 to 6 things a player could do there, each with its presses. It is not told the goal.
- **Labels are cached by the screen's hash** (8x8 block codes, the same codes the screen graph uses). A screen
  matches a labelled one exactly, within 8% of blocks, or (map screens) after the view scrolled up to two blocks.
  Menus, fights and text need a 3% match, because a moved cursor changes the right presses.
- **The typed decider makes every choice.** At the same moments the advisor used to be asked, OpenAI Decisions
  (gpt-6-luna, default) or Jev (`"decider": "jev"`) gets a typed state: the goal, this screen's cached label, the
  last few screens' labels, what each d-pad button has done from here in the screen graph (blocked, reached new
  places, untried), and how its last choices turned out. It answers two typed questions: which option to take (the
  label's actions, a 4-step walk each way, A, B, or "let the explorer run") and which way the goal lies (the
  explorer leans that way, as with the advisor's heading).

Everything else is as in round 7: the press-and-watch explorer, the k-NN walk books, the stage list from power-on
to the Boulder Badge (with its RAM done-checks on the grader side). No RAM on the agent side.

## Power-on to Boulder Badge (same 12 stages and seeds 241-250 as round 7)

Data: `typed-decider/chain-openai-v1/` (s*.json per seed).

| seed | typed decider (OpenAI) | $ | round 7 (vision model decides) | $ |
|---|---|---|---|---|
| 241 | lost to Brock (L14) | 0.41 | badge | 0.62 |
| 242 | badge | 0.38 | blacked out after training | 0.82 |
| 243 | badge | 0.33 | badge | 0.54 |
| 244 | badge | 0.34 | badge | 0.79 |
| 245 | badge | 0.31 | badge | 0.47 |
| 246 | badge | 0.28 | badge | 0.44 |
| 247 | badge | 0.35 | badge | 0.55 |
| 248 | badge | 0.23 | badge | 0.58 |
| 249 | badge | 0.31 | badge | 0.64 |
| 250 | training stopped at L12 (40k-press cap) | 0.33 | badge | 0.88 |
| **total** | **8/10** | **0.33 avg** | **9/10** | **0.63 avg** |

Per run: the vision model labelled 284-455 new screens ($0.18-0.31 of Azure), the cache answered
59-70% of lookups, and OpenAI Decisions made 740-1,393 choices for $0.05-0.11. The vision model is called more often
than the old advisor (284-455 calls a run vs 51-290) but each call is about 8x cheaper (one high-detail picture, short JSON, no
plan to write). Presses to the badge: 31k-68k, against 21k-48k in round 7; most of either is the training stage.

Misses. Seed 250 trained in Viridian Forest for the full 40,000 presses and reached only L12 (round 7
reached L13 in 34k on the same seed). Seed 241 healed at Pewter at L14, then went in and out of the gym (16 picks of "enter the Gym", walks
inside it) without reaching Brock before the 8,000-press stage limit.

## Held-out score (5 seeds, 900 s, 1,500 presses)

Data: `typed-decider/heldout-openai/`, `typed-decider/heldout-jev/`; baselines in `screen-only-phase1/heldout/`.
Normalised = (score - random) / (1 - random).

| game | random | screen only | vision model decides | typed, OpenAI | typed, Jev |
|---|---|---|---|---|---|
| Tobu Tobu Girl | 0.56 | -0.09 | +0.09 | 0.00 | 0.00 |
| PostBot | 0.40 | +0.07 | 0.00 | 0.00 | 0.00 |
| Renegade Rush | 0.24 | +0.11 | +0.16 | +0.21 | +0.16 |
| GBHack | 0.36 | 0.00 | +0.06 | +0.06 | -0.06 |
| **held-out median** | 0 | +0.03 | **+0.08** | **+0.03** | **0.00** |
| Aevilia (dev) | 0.08 | +0.09 | +0.39 | +0.22 | +0.09 |
| Pokemon Red (dev) | 0.15 | +0.08 | +0.13 | +0.14 | +0.11 |
| $ per run (avg) | 0 | 0 | 0.036 | 0.023 | 0.019 |

On the held-out games the typed decider is within noise of the vision model deciding, a little under it on Tobu
Tobu Girl and Aevilia, at about 60% of the cost. OpenAI beats Jev on 4 of 6 games and ties the other 2; Jev cost
$0.07 for all 30 runs.

## Verdict

The typed decider can replace the vision model as the thing that chooses: on the Pokemon chain it reaches the
Boulder Badge about as often as round 7 (8/10 vs 9/10, within noise on 10 seeds) at about half the money
($0.33 vs $0.63 a run). On the held-out
games it is at the vision-only level, not above it. Default stays the vision model (no flag) until a second round;
`{"decider": "openai"}` in `screenonly_chain.py` settings and `--agent screen+typed` in `heldout/run.py` turn the
typed agent on, `ANYGAME_SCREEN_DECIDER=jev` or `{"decider": "jev"}` picks Jev.

Next: keep the label cache across runs (it is perception, so a second run of the same game should need far fewer
labels), and cell-level object keys from `perceive/cellbook.py` in the typed state instead of whole-screen labels.

Spend for this work: Azure about $3.55 (the shared counter is at $147.7 of the $250 cap since Oct 9), OpenAI
Decisions about $0.94, Jev $0.07.
