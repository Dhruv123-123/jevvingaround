# Real web game trial (2026-10-01)

The first time anygame played games it did not write. Three public sites were played in headless Chromium, each with
a pack written by hand. Authoring was paused because no chat model was allowed (OpenRouter is for Jev only, and
Azure was not in this environment). Jev (`typesafe/jev-1.13` via OpenRouter) made every decision.
`scripts/web_trial.py` reads the page's own state (DOM or the game's JS object) right after each screenshot and
compares every read against it.

Run it with `python scripts/web_trial.py tictactoe|snake|dino --episodes N`. Logs go to `trial/<game>/`, which is
gitignored.

| game | site | kind | games | reads wrong* | result |
|---|---|---|---|---|---|
| tic-tac-toe | playtictactoe.org | turn-based | 8 | 3 of 41 ticks, all on animation frames | 0 won, 5 tied, 3 lost |
| snake | playsnake.org, level Slug | slow real-time (~5 cells/s) | 5 | 22 of 629 ticks, all one-step timing | 15–360 ticks, scores 0–105 |
| dino | chromedino.com | fast (~360 px/s) | 5 | 25 of 431 ticks, all at zone edges | scores 58–124, dies at the 2nd–6th cactus |

\* "Wrong" means the read disagreed with the page's state, which was taken a few ms after the frame. Every
disagreement checked was a frame caught mid-change: an X fading in, the snake one cell further on, a cactus a few
pixels into a zone. None was a misread of a still screen.

Jev's latency was 336 ms at the median, 403 ms at p90, 541 ms at p99 and 1377 ms at worst, over 834 calls. The
whole trial cost $0.033 in Jev calls.

## Tic-tac-toe

- **Perception works.** The page is monochrome (X and O are both white), so colour reads cannot tell them apart.
  The board is read by shape: the `templates` read now takes `inset` and `otherwise: "."`. A finished game is read
  by colour, because the loser's marks fade to grey.
- **Jev plays sensibly.** `can_win_now` and `must_block` came back at 0.99 whenever they were true, and the win and
  block cells were right.
- **What broke:**
  1. The page has no turn indicator. At 2 Hz the pack tapped while the computer was still thinking, the page
     ignored the tap, and the computer won while the "block" was being dropped. Slowing to 0.8 Hz fixed this.
     A real fix needs a turn read, from X/O counts plus who started.
  2. All three losses were forks. The paragraph has no fork rule, so this is a strategy gap in the pack, not a
     Jev or perception problem.

## Snake

- **Perception works.** Head, body and food are all drawn dark. Food separates from the body by a lighter mean
  colour. The head is not drawn differently, so a new derived read, `kind: head`, finds it: it is the cell that
  newly appeared at an end of the body. It also gets `head_moving`. Before the snake first moves, the head is
  unknown for 1–2 ticks.
- **Jev plays sensibly.** It heads for the food and respects the rules. In one game it survived 360 ticks.
- **What broke:**
  1. Slug is not slow. The snake moves about 2 cells per decision, while the bundled snake pack assumes 1. Every
     death had the same shape: Jev turned toward the food into a corridor 2–3 cells from a wall, and the next turn
     came too late.
  2. Rules that look 2 cells ahead lengthened the games (the best went from 86 ticks to 360) but did not end the
     deaths. The fix is planning for 2 or more cells of travel per decision: `margin` and `predict` exist for this
     and are not used yet.
  3. The countdown digit on the board reads as snake cells. The harness waits for the countdown to finish; a pack
     needs a `countdown` screen.

## Dino

- **Perception works.** Three colour zones in front of the dino (`near`, `mid`, `far`) and the GAME OVER banner
  are all read correctly away from zone edges.
- **Jev is close to irrelevant here.** A cactus crosses about 120 px during one 336 ms Jev call. The pack therefore
  jumps by rule (`near` = cactus excludes `keep`), with `budget_ms` asking Jev only every 7th tick.
- **What broke:**
  1. A rule-only action failed. When the stale answer under `budget_ms` did not offer `jump`, the loop kept `keep`
     even though `keep` was excluded ("every action excluded; keep stands"). It now takes the one action the rules
     leave (`loop.py`).
  2. Jump timing depends on where `near` starts. Jumping with the cactus 200 px out lands on it, so the zone was
     narrowed to 100–165 px.
  3. Calls to Jev block the loop. One Jev call took 1377 ms, during which the game ran unattended, and a cactus
     killed the dino (episode 3). Fast games need the decider called asynchronously, so the rules keep acting
     while it is out.
  4. Birds (later in a run) are not read. No run got far enough to meet one.

## Other findings

- **Authoring bug.** Before it was stopped, `anygame go` on playsnake.org probed four frames, and all four were the
  start menu. The pack passed its own tests without ever seeing gameplay, and read the menu as `status: won`. The
  author's probe needs to get past a start menu, or the pack should fail when every fixture is the same screen.
- **Chromium setup.** Headless Chromium in the cloud did not trust the agent proxy until its CA was added to
  `~/.pki/nssdb` with `certutil`.

## Authored with Azure (2026-10-01, later the same day)

The same three sites, with packs written by `anygame author` on Azure (`gpt-5.6-luna`) and played by Jev. About 22
authoring calls in all, because the key is rate-limited. The packs are in `packs/web-*-authored/`, each with its
probe frames and `fixtures/probe.json` (what led to each frame, and whether the game was in motion).

| game | authoring | sees gameplay | Jev play |
|---|---|---|---|
| tic-tac-toe | passed in round 1; one revision from a play log fixed its move rules | yes: every board read right | 20 games: 5 won, 6 tied, 9 lost (the page's own scoreboard) |
| snake | passed after 6 rounds (the flipping OCR test below cost 3); two revisions from play logs | its tests do, but it has no head or food read | starts the Slug level, never steers |
| dino | passed after 4 rounds; one revision | yes: the obstacle grid in front of the dino | restarts each run, dies at the first or second cactus (scores 17–44) |

What had to change for authoring to work at all:

1. **The probe never reached gameplay.** It tapped a fixed 3x3 grid and pressed keys, kept the first four frames
   that differed, and on playsnake.org all four were the level menu. It now presses keys first, then taps the
   labels and buttons a person would (word-sized shapes, top to bottom, following a new screen's labels), watches a
   screen that moves on its own and keeps pressing keys, and picks the start frame, then gameplay frames, then the
   most different rest. On chromedino.com its taps hit ads and the author was handed four frames of other sites; a
   navigation now sends it back and the frames are dropped.
2. **X and O are the same white.** A colour read saw both as X. `hollow: O` on a `stat: accent` read returns O when
   the glyph's middle is background. Grid accent reads also found the background wrongly when a large glyph
   touched the inset edge.
3. **Tests flipped between rounds.** The pack check, and `anygame eval`, shared a background OCR worker, so a read
   with `every: 4` came back null on some frames. The author bent its expectations to the nulls each round. Both now
   run every read on every frame (this also makes the bundled 2048 and 2048gb packs pass `eval`).
4. **A pack crashed the loop.** The dino pack wrote `only: [start]`; it loaded and passed its tests, then crashed on
   the first tick. Malformed `only`, `avoid`, `set` and `exclude` are now refused at load, so the author fixes them.
5. **The best pack was picked wrongly.** Two plays that both ended without a win or loss tied, and the tune step
   kept the one that had stalled on its first move. Ties now go to the pack that made more decisions.
   `author --resume` revises the pack already in `--out` without probing or writing anew.

What is still wrong:

- **Passing its own tests says little about play.** The snake pack passes all five tests and keys its whole state
  off OCR of the overlay text (`GAME OUER!`, `000`), acts only while the overlay reads `Go!`, and has a 15x10 grid
  on a board of about 21x15 cells. Two play-log revisions got it to start the level but not to steer.
- **Tic-tac-toe loses to timing**, as the hand-written pack did: the page has no turn indicator, so taps during
  the computer's move are ignored. The revision did not slow the pack down.
- **Dino is too fast for a 350 ms decision**, as before, and the authored pack presses Space whenever an obstacle
  is anywhere in its grid rather than at a distance.
- **The sites change.** chromedino.com served three different layouts in one hour, one with an ad banner that kept
  the game from starting during a revision's play run.
