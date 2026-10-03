# Does the learn loop learn? (2026-10-03)

`anygame learn` run for real for the first time: Jev (`typesafe/jev` on OpenRouter) deciding, Azure `gpt-5.6-luna`
proposing pack rewrites, on tic-tac-toe at playtictactoe.org, starting from the Azure-authored pack
(`docs/real-web-trial-packs/web-tictactoe-authored`).

**Verdict: no, not here.** Over 35 games the loop saw 4 losses, asked Azure for 8 rewrites (two per loss), and
rejected all 8. The pack never changed, so nothing improved. The rejections were correct: every rewrite would have
made the pack worse.

## Records

All runs reload the page before each game, so the page's scoreboard starts at 0-0-0 and says how the game ended.

| run | pack | games | won | tied | lost |
|---|---|---|---|---|---|
| baseline (same day) | authored pack + scoreboard reads | 20 | 6 | 11 | 3 |
| `anygame learn` | the same pack throughout (no rewrite kept) | 35 | 9 | 22 | 4 |
| hand change, after the loop | the same pack at `tick_hz: 1` instead of 4 | 20 | 4 | 15 | 1 |

The October 1 record for this pack was 5 won, 6 tied, 9 lost, in one long session without reloads. Today's
baseline is better because each game starts from a fresh page. There was no separate "final pack" measurement:
no rewrite was accepted, so the 35 learn-loop games are the after-record of the same pack.

Cost: Jev about $0.022 in all (baseline $0.006, learn loop $0.010, hand run $0.006). Azure: 8 calls.

## The fix the loop needed before it could run

The authored pack ends a game on `stop_when: { read: result, in: [over] }`. The loop reads an episode's outcome
from the stop reason, and its loss pattern matches `over`. So every game, wins and ties included, counted as a
loss, and every game would have triggered a rewrite. The pack cannot tell a win from a loss: the page has no
banner, only a scoreboard.

Two changes (branch `claude/anygame-learn-loop-trial`):

1. `stop_when` may be a list. The first condition that holds ends the run and names it, so a pack can stop on
   `won is 1`, `lost is 1` or `tied is 1`. This is in both the Python loop and the extension.
2. The trial pack (`docs/learn-loop-trial/web-tictactoe-base`) adds three reads on the scoreboard digits. They
   tell a `0` from a `1` by shape, since a `0` is a ring, and stop on whichever one turns to 1. Two new test frames
   cover a tie and a loss. Strategy (play paragraph, questions, rules) is untouched; that part is left for the loop
   to change.

`scripts/web_trial.py` gains `--pack` and `--reload` for the baseline and hand runs.

## Every rewrite the loop proposed

All four losses were the same game, move for move (the baseline's and the hand run's losses too). Jev takes the centre and then c1r1. At the fourth move the board read `X.X / .X. / O.O`. Jev tapped c2r1,
the winning cell (can_win 0.98), but the page ignored the tap and the computer completed the bottom row.

The page's own state shows why. At that tick X had three marks and O two, so the page held the computer's turn
when Jev tapped. The pack and the page had fallen out of step earlier in the game: a decision was made on a frame
taken before the computer's reply. The first trial reported the same thing ("the page has no turn indicator").
**The loss is a timing and turn-order fault. No tic-tac-toe strategy rewrite can fix it.**

What Azure proposed (rejected YAMLs in `docs/learn-loop-trial/rejected/`):

| loss | round | what it changed | verdict |
|---|---|---|---|
| 1 (game 8) | 1 | "block O before taking your own win"; a `set` rule for blocking; `history` on reads; a `margin` read on `legal`; `gravity: down` on the `runs` reads | rejected on replay: the fatal decision is neither excluded by a rule nor visible in the typed frame |
| 1 | 2 | block before win; `gravity: down`; a rule excluding `$x_wins_at` whenever O threatens | rejected on replay, same reason |
| 2 (game 19) | 1 | block before win; the two `set` rules swapped in order; `gravity: down` | rejected on replay |
| 2 | 2 | the same, plus "exclude your win and only allow the block when O threatens" | rejected on replay |
| 3 (game 31) | 1 | block before win; new reads `x_at`/`o_at` (locate with history) and `x_threats`/`o_threats` (2-in-a-row runs, `gravity: down`) | **passed replay** (the new reads set the fatal tick apart), then rejected when Jev was re-asked on the fatal frame: it still chose `place` |
| 3 | 2 | block before win; an `only: o_wins_at` rule when O threatens | rejected on replay |
| 4 (game 35) | 1 | block before win; `history`; `margin` on `legal`; `gravity: down`; a `set` rule for blocking | rejected on replay |
| 4 | 2 | block before win; the two `set` rules swapped; `gravity: down` | rejected on replay |

All 8 made the same wrong diagnosis: that Jev should block the computer's threat before taking its own win. That
is bad tic-tac-toe, since when you can win you win, and it was not the cause. `gravity: down` is a Connect Four
idea that the revision prompt's syntax hint offers, and it is wrong for this game. Had any of these been accepted,
the pack would have played worse.

**Did any accepted rewrite improve the record?** None was accepted, so no.

## What the loop is missing, compared with the hand-made gains

1. **It can only see a fault in the last decision before the loss.** Here the fault happened two moves earlier: a
   tap on a stale frame put the page out of step. The final decision (take the win) was correct. The verifier
   demands that this final decision become impossible or visible, so even a correct timing fix would fail it.
2. **Replay cannot judge timing.** The verifier replays the recorded frames through the candidate pack. A change
   to `tick_hz`, `settle` or a turn guard changes which frames exist, which replay cannot show. The fixes that
   mattered most today (snake reflex, dino frame-timed jumps, non-blocking Jev calls) were all timing fixes.
3. **It compares action ids, not cells.** In a tap-a-cell game every move is the action `place`. A rule that
   excludes the fatal cell, as in loss 1 round 2, does not change the action, so it never counts as "guarding"
   the fatal tick. The usage audit has the same blind spot: it told Azure that `can_win` and `must_block` "never
   change the action", though they decide the cell. That likely pushed Azure toward rule shuffling.
4. **It edits only the pack.** Every hand-made gain today was a compiler or loop feature: Tetris and 2048
   lookahead, Go playouts, the snake `reflex:` line, the dino jump timing. The pack language here cannot even
   express "act only when X and O have the same number of marks", because no rule can count a list. The loop
   cannot add that read kind.
5. **It sees one game's window, not the pattern.** The same loss happened four times in a row with identical
   moves. Each time the loop asked afresh, and got the same wrong answer. It has no "this is the same loss again,
   try a different kind of change" step beyond the calibrator, which needs kept or reverted trials to learn from.
   This run produced none.
6. **One game is its trial.** A kept rewrite plays one episode and stays unless it is worse than the incumbent's
   median. With tied games as the median, one game cannot tell a 5% loss rate from a 15% one.

What did work: the safety checks. Replay, re-asking Jev on the fatal frame, and the overblock check rejected eight
wrong rewrites. A loop without them would have locked in "block before win".

## The hand change tried afterwards

Slowing the pack from 4 to 1 tick per second (`docs/learn-loop-trial/web-tictactoe-hand-tick1`) gave 4 won,
15 tied, 1 lost. The one loss was the same game as before. One loss in 20 against 3 in 20 is within noise, so
slowing down is not the fix either. The real fix is a turn read: count X and O, and act only when the counts
match. That needs a counting read kind in the compiler, which neither the loop nor the pack can add today.

## Files

- Report copy: `/mnt/project-files/anygame/learn-loop-trial.md`
- Logs: `/mnt/project-files/anygame/learn-loop-trial/` (`baseline/`, `learn/` with the bank, incidents and
  rejected rewrites, `hand-tick1/`)
- Packs: `docs/learn-loop-trial/web-tictactoe-base`, `docs/learn-loop-trial/web-tictactoe-hand-tick1`
