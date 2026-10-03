# The learn loop, widened: can it find the fixes made by hand? (2026-10-03)

`anygame learn` with three changes (branch `claude/anygame-learn-loop-v2-bvuq5h`, on top of PR #5), then run for real
with Jev deciding and Azure `gpt-5.6-luna` diagnosing and rewriting, on three games where a fix was found by hand
this week, with that fix taken out.

**Verdict: yes on two of three.** On tic-tac-toe the loop found the known fix (a turn read and gate) on its first
rewrite. On Tetris it found the known fix (lookahead on, and "take the top landing") on its second run, after it
first fixated on a smaller real bug. On Snake it diagnosed the right kind of problem (latency) but never found the
`reflex:` line; both of its timing rewrites played worse and were reverted.

| game | known fix removed | before | after | found |
|---|---|---|---|---|
| tic-tac-toe, playtictactoe.org | turn gate (none existed) | 9 won / 22 tied / 4 lost of 35 (first loop, pack unchanged) | **5 won / 7 tied / 0 lost of 12** | **the known fix**: `count` read X minus O, `act_when` turn = 0 |
| Tetris, seed 1, 400 ticks | lookahead and the "take `a`" paragraph | game over at 13–15 lines, 8 of 8 games | **156, 159, 158 lines, alive at the cap** (3 games) | **the known fix**: `lookahead: true` plus a paragraph saying take the top-ranked landing |
| Snake, seed 2, 400 ticks | the `reflex:` line | 2 of 5 games dead | no change kept | **nothing**: two timing rewrites, both reverted |

Jev cost for the whole thread: **$0.17** (tic-tac-toe $0.002, Tetris $0.12 including two aborted runs, Snake $0.05
including aborted runs). Azure: about 35 calls; 5 revision calls failed with a gateway 502 (all on Tetris before the
pack shown to the model was trimmed).

## What changed in the loop

1. **Diagnosis before rewrite** (`anygame/diagnose.py`). On a loss the chat model gets the whole episode, not the last
   ten decisions: every decision with the time its frame was taken, the decider's latency, when the action landed,
   the reads (all of them for the last eight decisions, what changed before that), the rules that fired, runs of
   waits folded into one line, and, where the compiler ranks options, how often the decider took the first one and
   examples of when it did not. It must name one cause, a category (timing, turn order, perception, instruction,
   compiler, strategy) and the evidence ticks before any change is asked for. Diagnoses go into the bank with a loss
   signature (how the game ended and its last six decisions); a repeat is flagged with what was already tried and how
   it went. If a cause was already diagnosed and its fixes failed, the model is told to name the next one.
2. **A wider rewrite.** A rewrite may add or change reads, add an `act_when` gate (now a list of conditions), change
   timing (`tick_hz`, `settle`), turn on compiler options (`lookahead`, `reflex`, playouts, `criteria_from`) and
   rewrite the paragraph. One new read kind was added by hand so a turn gate is expressible: `count` (cells holding a
   symbol, less cells holding another), in the CLI and the extension.
3. **New checks.** Before a rewrite plays:
   - it must make the kind of change the diagnosis calls for (a turn-order fault is not fixed by a strategy rule,
     which is what the first loop proposed eight times);
   - every new or changed read must parse on every recorded frame (loss windows, wins, held-out ticks);
   - at the evidence ticks it must act differently: a rule changes the move, the gate holds the agent back, a
     re-ranking changes what a label means (landing `a` is now another landing), a new read separates the tick, or,
     for a paragraph or question change, Jev re-asked under the new pack answers differently;
   - ordinary decisions stay allowed, here, in other losses and in banked wins (a tick a new gate only defers is not
     a blocked move, as long as the gate still opens on at least 20% of recorded frames);
   - held-out drift and the calibrator, as before.
   Then it plays `--trial N` games and stays only if it plays no worse: by win/loss first, then by `score_read`
   (which may now be a path such as `piece.lines_cleared`), then by game length.

## Tic-tac-toe

Started from the first trial's bank (`--revise-first` diagnoses its newest loss before playing). The diagnosis, from
the five-tick losing game: *"acted-before-computer-response [turn_order]: the agent acted on frames showing its own
previous move before the computer had completed its response, because act_when only checked mode and not whose turn
it was"*, evidence ticks 2, 3 and 5. The first rewrite added

```yaml
turn: { kind: count, in: cells, symbol: X, minus: O }
act_when: [ { read: mode, equals: "1P" }, { read: turn, equals: 0 } ]
```

and nothing else. Checked on the recorded frames, the gate held the agent back at ticks 2, 3 and 4 and opened on 32%
of all recorded decision frames (the pack had been acting out of turn about two thirds of the time). Eight trial
games: 3 won, 5 tied, 0 lost, mean outcome +0.38 against +0.14 for the old pack's 35, so it stayed. Four more games
with it: 2 won, 2 tied. Twelve games, no loss; the old pack lost about one game in nine, so twelve without a loss is
encouraging but not proof. Pack: `docs/learn-loop-v2/ttt-learned`.

## Tetris

The pack as it was before the Tetris thread (`docs/learn-loop-v2/tetris-old`): the "keep the well open" paragraph and
no lookahead, plus `score_read: piece.lines_cleared` so the loop can compare games. Seed 1 every game, so the
pieces are the same each time.

**Run 1 (8 games): stuck on the wrong cause.** Seven diagnoses of the same loss all named a real but small bug:
once in the game the pack places the J piece twice, on a frame taken before its first hard drop showed. The fixes
for it (a gate on `phase: spawned`, a shorter settle) either failed the checks or played the same (15 lines). Two
loop faults showed up here and were fixed between runs: the trial compared lost games by length, so a gate that made
the agent wait longer looked better while clearing fewer lines (now score first), and replay re-read the piece's
phase from single frames, losing the history that read needs (unchanged reads now come from the record).

**Run 2: found it.** With the instruction to move past a cause whose fixes had failed, the diagnosis of the same
loss read: *"missing-lookahead [compiler]: the landing rank uses only immediate board metrics and lacks lookahead, so
it repeatedly selected locally acceptable placements that led to the eventual high stack"*. The first rewrite (only
`lookahead: true`) failed the evidence check: the banked incident only held the last frames, where the top choice
did not change. The second added lookahead and rewrote the paragraph:

> The compiler ranks the reachable landings using the current piece, the preview piece, and the resulting future
> stack. Choose the highest-ranked landing offered by `piece`; do not override that ranking using the immediate
> height, bumpiness, holes, well, or line-clear text.

That is the hand fix in its own words. Trial: 156 and 159 lines, alive at the 400-tick cap (the hand-fixed pack got
158); kept; one more game 158. Pack: `docs/learn-loop-v2/tetris-learned`.

One honest caveat: that second rewrite also set `as: matrix` on the preview read, and the check counted the changed
presentation as "the typed frame now separates the evidence ticks". That loophole is closed (a read that differs
only in `as:` no longer counts), so today the same rewrite would have to show its change at the evidence ticks,
which needs the frames from earlier in the game; a live loss now keeps those (the newest 300 decision frames), a loss
taken from an old bank does not. The trial games are the real evidence that it works.

## Snake (reflex line removed)

The current snake pack minus `reflex:` (it keeps the turn-one-cell-early rule). Seed 1 survived without it, so the
run used seed 2. Old pack: 2 of 5 games dead (3 alive at the cap).

The diagnoses were the right kind: *"action-latency-race [timing]: the agent issued a safe turn too late, so the
snake continued moving into its body before the action landed"*, then *"turn-state-desync"*, then an instruction
fault in the paragraph. But the rewrites were `tick_hz: 1` with `settle_ticks: 2`, then `settle_ticks: 1`: slowing
down or waiting longer, the opposite of the hand fix (act on the last answer without waiting). Both played two trial
games, died in all four (after 35 and 30 ticks; 236 and 58), and were reverted. The loop never turned on `reflex`, though the
prompt lists it with what it is for. No change kept.

A last diagnosis blamed the paragraph's food-first wording; its two paragraph rewrites were rejected, one by the
held-out drift check (Jev changed 66% of answers on ordinary ticks) and one at the evidence ticks (1 of 3 changed).
On Snake the drift check mostly measures Jev's own noise, so it is a weak judge there.

Two more loop faults found here and fixed: re-asking Jev to judge a timing-only change measured only Jev's own noise
(it flips 80% of keep/turn answers on a second asking), so timing changes now go straight to the trial games; and a
version number was reused after a revert, overwriting the reverted pack on disk, and the last trial game of a
reverted pack was booked under the old version.

## What the loop still lacks

- **Timing changes are judged only by play.** Replay cannot show what a faster or slower loop would have seen. A
  timing rewrite therefore skips straight to the trial, and two-game trials are thin (the Snake rewrites were
  reverted correctly, but a lucky pair of games would have kept one).
- **Old banks lack early frames.** Evidence ticks from early in a game can only be checked when the loss was played
  live under v2.
- **The diagnosis can fixate.** Seven identical diagnoses in Tetris run 1 before the "name the next one" rule.
- **Azure gateway timeouts** on long rewrite answers (fixed by hiding fingerprints, which the model must not edit).
- **`reflex` was never chosen.** Perhaps the description in the feature list is too abstract; the loop did not
  connect "the answer lands too late" with "act on the last answer".

## Files

- Logs: `/mnt/project-files/anygame/learn-loop-v2/` (`ttt/`, `tetris/` with `run1-learn-stderr.log`, the run-2 log
  and two aborted runs, `snake/` with an aborted run). Each `bank/` holds `diagnoses.jsonl`, every pack version,
  rejected rewrites and the episode logs.
- Packs: `docs/learn-loop-v2/ttt-learned`, `tetris-old`, `tetris-learned`, `snake-noreflex`.
- Code: `anygame/diagnose.py`, `learn.py` (`verify_v2`, `improve_v2`, `trial_verdict`), `cli.py` (`--trial`,
  `--revise-first`, `--legacy` for the first loop), tests in `test/test_learn_v2.py`.

Reproduce (tic-tac-toe from the first trial's bank):
```bash
cd anygame && OPENROUTER_API_KEY=… anygame learn docs/learn-loop-trial/web-tictactoe-base \
  --device "web://https://playtictactoe.org" --sensor jev --episodes 12 --bank <copy of the trial bank> \
  --revise-first --trial 8
```
