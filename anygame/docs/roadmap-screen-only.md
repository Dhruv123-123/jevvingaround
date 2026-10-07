# Roadmap: a screen-only agent (pixels in, buttons out)

2026-10-06. Replaces the agent-side half of `roadmap-any-game.md` (PR #9) and builds on the measurement in
`screen-only-perception.md` (PR #31). Goal, in Dhruv's words: a model that can play anything, through vision and
inputs on a computer.

## Why change

Everything the long-horizon agent knows comes from the emulator: RAM scans for position and map, tile ids, save
states for lookahead. It got Pokemon Red to Route 22 and is level with random on the held-out suite, but none of it
works on a game that is not in an emulator, and each Pokemon fix was one more emulator-shaped patch. The experiment
shows the screen-only route is affordable: a pixel cache answers 97–100% of cells once warm, and labelling everything
new costs about $0.05 per 1,000 cells (under $0.25 per game-hour on Pokemon, $1.2–1.6 on fast scrollers). It also
shows the weak point: the vision model is a poor judge of what a single cell does, while the game itself (press and
watch) is a good one.

## The metric

One number stays: **the held-out score** (four held-out ROMs, grader reads RAM the agent never sees, random = 0,
900 s and 1,500 presses), plus Pokemon Red and Aevilia at the end of every phase. Two more are reported beside it on
every run:

- **cache hit rate**: share of cells, and of whole frames, answered without a model call (target: 99% of cells and
  90% of frames after 5 game-minutes);
- **dollars per game-hour**: all model spend divided by game time played (target: under $1, Jev included).

## Remove (from the agent's side)

| what | why | what stays |
|---|---|---|
| RAM scan for position and map (`discover.py`, `ramscan.py`) | emulator-only | kept for the grader and as a check on the pixel version |
| tile-id grid and sprite table as the agent's input | emulator-only | grader truth |
| save-state lookahead as the forward model | emulator-only; it also hides the cost of acting in a real game | kept for the Jev audit, offline, never in play |
| hand-written packs (`packs/*/pack.yaml` read sections) | per-game code | one generic screen pack |
| Pokemon-specific spec and goal lists | per-game knowledge | the grader's milestones |

## Add

1. **Pixel perception with the novelty cache** (built, `perceive/cellbook.py`). Next: cut sprites out before
   hashing (background model per scroll offset), per-region grid phase for HUD + playfield screens, objects as
   groups of moving cells with their own keys. Unknown cells never block play; labels arrive in the background.
2. **Press-and-watch on pixels.** For each button: does the picture scroll, does a group of cells move, by how much,
   does nothing change. This gives the player (the group that follows the d-pad), walkable and blocked cells
   (verified, outweighing the model), menus (a cursor that moves between rows) and dialogue (a box that advances on A).
3. **Screen graph as the world model.** Nodes are screen fingerprints at the right granularity (a room, a menu page),
   edges are presses or press sequences with what they caused. A room's map is the cells seen while scrolling within
   it. Places, doors and going back come from the graph, not from map bytes.
4. **The model as a namer, asked only on novelty or contradiction.** Whole objects, regions, words and screens, not
   8x8 letters. Text keeps tiletext's glyph book. Goals are written from what the game says (the goal layer exists).
5. **A retrainable fast path.** Every verified label and every model answer is training data for a small local
   classifier (cell or object → label, screen → kind). When it agrees with the model on held-out cells, it answers
   first and the model is only the fallback. This, not Jev, is the layer that learns.
6. **Jev as decider only where the audit says so.** Jev picks among options at decision points; the save-state audit
   (run offline) compares it with the top-pick stand-in per decision type, and Jev keeps only the types it wins.

## Phases

| phase | build | done when | Azure | Jev | wall |
|---|---|---|---|---|---|
| 0. Fix the cache (now) | sprite cut-out, per-region phase, object keys; re-run this experiment | frames fully answered ≥ 90% warm on all six games; projected ≤ $0.5 per game-hour | ~$1 | $0 | 1–2 days |
| 1. Press-and-watch | button effects, player detection, walk/blocked verification, menu and dialogue detection from pixels | player found on ≥ 5 of 6 games; walk labels ≥ 95% right against RAM truth on Pokemon and Aevilia | ~$1 | $0 | 2–3 days |
| 2. Screen graph | fingerprints, edges from presses, places and going back; the long-horizon navigator re-pointed at it | Pokemon: Pallet → Viridian and back with no RAM; Aevilia: leaves the house | ~$2 | $0 | 3–5 days |
| 3. Screen-only agent on the held-out score | the generic screen pack: options from the graph, top-pick decider; then Jev where the audit says | held-out median above random (> +0.1 on 2 of 4) with no RAM on the agent side | ~$3 (held-out re-scores) | ~$1 (one Jev re-score + audit) | 3–5 days |
| 4. Fast path | local classifier trained on verified labels and model answers; model as fallback | model calls per game-hour down 10x with no drop in the held-out score | ~$1 | $0 | 2–3 days |
| 5. Pokemon first badge, screen-only | the campaign layers (goals, upkeep, battle choice) moved onto pixel state | Brock beaten with no RAM on the agent side, under $5 all-in | ~$3 | ~$3 | 1–2 weeks |
| 6. Off the emulator | the same agent on a browser or desktop game through `screen://` | a held-out non-emulator game above random | ~$2 | ~$1 | 1 week |

Totals: about $13 of Azure and $5 of Jev across all phases, at today's prices and play rates. Jev needs OpenRouter
credit again from phase 3 (currently used up). Every phase ends on Pokemon Red and Aevilia, and phases 3–6 on the
held-out score.

## What to watch

- **Wall time, not dollars**, is the binding cost: a model call is ~10 s, so labelling must stay off the critical path.
- **Non-tile games.** The cache leans on a fixed grid. Phase 6 will need region-level keys (perceptual hashes of
  connected regions) where there is no grid; the phase-0 object keys are the first step toward that.
- **The physics vocabulary.** "Walkable" is a top-down idea; platformers need "can stand on", shooters "hurts". Press-
  and-watch should learn effects as data (what changed after which press), not a fixed list.
