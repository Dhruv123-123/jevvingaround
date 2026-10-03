# The learn loop, widened: can it find the fixes made by hand? (2026-10-03)

`anygame learn` with three changes (branch `claude/anygame-learn-loop-v2-bvuq5h`, on top of PR #5), then run for real
with Jev deciding and Azure `gpt-5.6-luna` diagnosing and rewriting, on three games where a fix was found by hand
this week, with that fix taken out.

**Verdict: yes on all three. On Go, once the re-rank option existed, the loop chose it on its first diagnosis, and
with Jev deciding the result won 14 of 16 against the strong white, against 9 of 16** (see the Go section). On tic-tac-toe the loop found the known fix (a turn read and gate) on its first
rewrite. On Tetris it found the known fix (lookahead on, and "take the top landing") on its second run, after it
first fixated on a smaller real bug. On Snake it first diagnosed the right kind of problem (latency) but never reached
for `reflex:`; after a catalog that maps each kind of fault to the feature that fixes it was added, it found a reflex
and kept it: 5 of 5 trial games alive at the cap (median score 190) against 1 of 4 for the pack without it (median 140).
See "Snake, second attempt" below.

| game | known fix removed | before | after | found |
|---|---|---|---|---|
| tic-tac-toe, playtictactoe.org | turn gate (none existed) | 9 won / 22 tied / 4 lost of 35 (first loop, pack unchanged) | **5 won / 7 tied / 0 lost of 12** | **the known fix**: `count` read X minus O, `act_when` turn = 0 |
| Tetris, seed 1, 400 ticks | lookahead and the "take `a`" paragraph | game over at 13–15 lines, 8 of 8 games | **156, 159, 158 lines, alive at the cap** (3 games) | **the known fix**: `lookahead: true` plus a paragraph saying take the top-ranked landing |
| Snake, seed 2, 400 ticks (first attempt) | the `reflex:` line | 2 of 5 games dead | no change kept | **nothing**: two timing rewrites, both reverted |
| Snake, seed 2, 400 ticks (with the fault catalog) | the `reflex:` line | 3 of 4 dead, median score 140 | **0 of 5 dead, median score 190** | **a reflex**: `ahead in [s, wall]`, one step later than the hand fix's `ahead_free ≤ 1` |

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

## Snake, second attempt: a catalog of faults and the features that fix them

The first attempt showed the loop knew the features existed but not which fault each one answers: it diagnosed slow
reactions and then slowed the loop down. Three changes, then the same test again (seed 2, reflex removed, fresh bank):

1. **A fault catalog** (`FAULTS` in `diagnose.py`): eight fault kinds, each with what it looks like in the record and
   the feature that fixes it. `late_move` (the right move was known but the decider's answer landed after the game
   moved on) → `reflex` plus `unless`, "never slow the loop for this"; `out_of_turn` → a count read and an `act_when`
   gate; `stale_frame` → settle or a gate; `short_sighted` → lookahead; `unsure_ranking` → playouts;
   `contradicting_text` → the paragraph; `misread` → the read; `bad_choice` → a rule. The diagnosis must name one,
   and a rewrite must make a change of the matching kind (a late move is refused anything but a reflex).
   The recorded-frame check now covers a reflex too: it must fire at the evidence ticks, and on no more than half
   of all recorded frames.
2. **Longer trials for anything only play can judge.** A rewrite that touches timing or the reflex plays at least 5
   trial games and is judged on the game's own median score first.
3. **The game's own score.** The snake score is read by OCR, which doubles digits (160 read as 1660, and stuck there
   on the final frame), so the first try at this run judged misreads and was stopped. Where the page reports its own
   state (`ANYGAME_LOG_TRUTH`), the score now comes from it.

**Run A** (stopped): the first diagnosis was `late_move`, and the first rewrite added exactly the hand fix,
`reflex: { read: head_around.ahead_free, lte: 1 }`, plus a near-duplicate rule. Because it also changed a rule it got
the old 2-game trial and was reverted on 170 vs 180, which is noise. After this, any change that touches the reflex
gets the long trial, and the run was restarted.

**Run B** (14 games, kept): the base pack died in 3 of 4 games (scores 190 alive, 110, 140, 120).
- Diagnosis 1, `late_move`: a reflex keyed to a question's answer was refused (it does not fire at the evidence
  ticks); the repair round was refused by the held-out drift check.
- Diagnosis 2, `stale_frame`: `settle_ticks` played 5 trial games, 3 dead, median 110 against 140; reverted.
- Diagnosis 3, `late_move` (*"the only safe escape, right, was chosen correctly at tick 246 but landed after the
  snake advanced into its body"*): `reflex: { read: head_around.ahead, in: [s, wall] }`. It fires at tick 246 on the
  recorded frames. Trial: 5 of 5 alive at the 400-tick cap, scores 200, 180, 160, 190, 190; kept.

The kept reflex fires one step later than the hand fix (when the cell ahead is already fatal, not when one free cell
is left). It held on seed 2 here; the hand-fix thread found that trigger too late at a slower decider, so the hand
fix stays the better line. Pack: `docs/learn-loop-v2/snake-learned`. Jev for the second attempt: $0.14 (run B $0.09,
run A $0.02, the stopped OCR run $0.03). Azure: 6 diagnoses and about 8 rewrite calls.

## Go: a discovery test (no known fix to find)

Go against the fixed strong white (`games/go.html?ai=mc&playouts=400`), starting from the final Go pack (ladder
reading, 32 playouts per candidate and 160 for the top 3, "play the playout leader past a 0.06 gap"). Nobody knows
the next fix here. The loop played 20 learning games on seeds 101 to 120 (a device URL with `{seed}` now gives
each episode its own seed, apart from the 16 test seeds), with 4-game trials.

**Same-day baseline, unchanged pack, seeds 1 to 16:** 9 won, 7 lost, mean final lead +18.6, median +13.5 (the
earlier run: 9 of 16, +17.0, +10.5).

**What the diagnoses said** (7 losses diagnosed):

| Loss | Fault kind | Diagnosis | Rewrite | Outcome |
|---|---|---|---|---|
| seed 102 | contradicting_text | Jev ignored the "follow the leader past 0.06" paragraph at ticks 45 and 47 | paragraph, then paragraph and question | refused twice: re-asked, Jev made the same moves |
| seed 103 | unsure_ranking | at tick 55 Jev played c8r9 (win 0.03) over c7r4 (win 0.22 on 160 playouts) | more playouts plus paragraph, twice | refused twice: Jev made the same moves |
| seed 105 | none parsed | | no change; then a rule plus paragraph | refused: no change; the rule blocked moves in won games |
| seed 107 | bad_choice | c4r1 at tick 55 where c9r5 was clearly better | paragraph; then an invalid rule | refused: re-asked, Jev changed 1 of 4 evidence moves; did not load |
| seed 111 | stale_frame | "acted on a frame that did not show its previous move" | `settle: screen_change` | **kept**: 3 won, 2 lost on trial vs 6 and 5 before |
| seed 116 | bad_choice | c8r1 over a better tactical move | a rule; an invalid rule | refused: same moves; did not load |
| seed 117 | bad_choice | c7r1 although c8r6 had a much better playout result | a rule "never play a point in `go.doomed`" plus the same line in the paragraph | **on trial** when the 20 games ran out: 2 won, 1 lost |

Four of the seven diagnoses name the same thing: Jev passes up a move whose playout win rate is far higher (0.19 at
seed 103) and takes the `worth` leader, against the paragraph. That matches what the hand work found (Jev keeps its
own pick about 40% of the time past the gap). The loop cannot fix it with what it is allowed to change: rewording
the paragraph did not move Jev on the recorded positions, more playouts do not help when Jev ignores them, and the
rules can only compare a read with a constant, so "exclude any move more than 0.06 below the playout leader" cannot be
written. The fix it points at is a compiler option that re-ranks `best` by playout win rate past a gap (or drops such
moves), which would have to be added by hand, as `reflex` and `lookahead` were. The `stale_frame` diagnosis looks
wrong for Go (the pack only acts while `status` is `our_turn`); its `settle` change kept on a 5-game trial within noise.

**The learned pack on the test seeds** (v3: settle plus the doomed-point rule): the run stopped after 10 of 16 seeds
because the OpenRouter account ran out of credit (402 "Insufficient credits", $5.20 used of $5). On seeds 1 to 10:
5 won, mean lead +20.4, median +7.0; the unchanged pack on the same 10 seeds: 5 won, +18.2, +10.0. No difference so
far. Seeds 11 to 16 need credit on the OpenRouter account.

**Since then: the missing option exists.** PR #8 adds `rerank: playouts` to the go read (the playout leader goes
first in `best` past a 0.06 margin); with it the top-pick stand-in wins 14 of 16 against the same white, against 3 of
16 without. This branch carries that commit and a new fault kind, `ignores_measure` (the compiler measured a clearly
better option and the paragraph says to take it, but the decider keeps taking the first-ranked one), whose fix is
`rerank: playouts`; a rewrite that turns it on counts as the compiler change the fault needs, and the recorded-frame
check re-asks Jev when a compiler option changes what it is shown. The start pack for a rerun, without the re-rank,
is `docs/learn-loop-v2/go-start`.

**The rerun (2026-10-03 evening, after credit was added): the loop found it.** Same start pack, same 20 learning seeds
(101 to 120), same 4-game trials. The first loss it diagnosed (seed 102, the same game as the first run's first
loss) read: *"playout-leader-ignored [compiler/ignores_measure]: the decider repeatedly chose the first-ranked move
even when the measured playout leader was at least 0.06 better"*, fix `rerank: playouts` with `rerank_margin: 0.06`.
The first rewrite added exactly those two lines to the go read and nothing else. Re-asked on the evidence positions,
Jev now played the playout leader (c2r6, win 0.10 to 0.14, where it had played moves at 0.0). Trial: 2 won, 2 lost,
against 1 and 1 before; kept. Four later diagnoses (a bad-choice rule, a "deeper lookahead" option that does not
exist for Go, a paragraph change, a settle change) were refused or still on trial when the 20 games ended.

Tested on the 16 seeds:

| Pack | Seeds | Won | Mean lead | Median |
|---|---|---|---|---|
| unchanged (first day) | 1–16 | 9 | +18.6 | +13.5 |
| unchanged (second day) | 11–16 | 2 of 6 | +1.2 | −7.5 |
| first run's learned pack (settle, no doomed points) | 1–16 | 8 | +20.3 | +5.5 |
| **rerun's learned pack (rerank on)** | **1–16** | **14** | **+35.4** | **+23.5** |
| rerun's learned pack, same day as the second baseline | 11–16 | 6 of 6 | | |

The rerank pack wins 14 of 16 with Jev deciding, against 9 of 16 for the unchanged pack; on seeds 11 to 16, run the
same day, 6 of 6 against 2 of 6. Seeds 1 to 10 of the baseline were run the day before; white plays a fixed number of
playouts, so the comparison holds across days better than a time-bounded white would, but it is not same-day for
those ten. PR #8's hand-made pack (rerank plus a paragraph saying "play the first `best` move") got 14 of 16 with the
top-pick stand-in; the loop's pack keeps the old paragraph and gets 14 of 16 with Jev. Pack:
`docs/learn-loop-v2/go-learned-rerank`. Logs: `/mnt/project-files/anygame/learn-loop-v2/go/rerun/` and `seeds11-16/`.

Jev for the second Go day: $0.24 by the game logs (learning $0.10, the rerank test $0.08, seeds 11 to 16 twice
$0.06); the OpenRouter account's usage rose by $0.50 over the same hours, the rest being the checks' re-asks of Jev
(not booked in the game logs) and any other thread's use.

Jev for the Go test: $0.23 (baseline $0.08, learning $0.10, test of v3 $0.06). Azure: 7 diagnoses, 12 rewrite calls.
Pack: `docs/learn-loop-v2/go-learned`. Logs: `/mnt/project-files/anygame/learn-loop-v2/go/` (`baseline/`,
`learned-v3/`, `bank/`, `learn-stderr.log`).

## What the loop still lacks

- **Timing changes are judged only by play.** Replay cannot show what a faster or slower loop would have seen. A
  timing rewrite therefore skips straight to the trial, and two-game trials are thin (the Snake rewrites were
  reverted correctly, but a lucky pair of games would have kept one).
- **Old banks lack early frames.** Evidence ticks from early in a game can only be checked when the loss was played
  live under v2.
- **The diagnosis can fixate.** Seven identical diagnoses in Tetris run 1 before the "name the next one" rule.
- **Azure gateway timeouts** on long rewrite answers (fixed by hiding fingerprints, which the model must not edit).
- **`reflex` was never chosen on the first attempt.** The fault catalog fixed that; two of three `late_move`
  diagnoses produced a reflex that passed the checks.
- **The held-out drift check measures Jev's noise.** It refused a reflex-plus-read rewrite because Jev changed 81% of
  answers on ordinary ticks under it; Jev flips most snake answers when asked twice under the same pack. It should
  compare against Jev re-asked under the incumbent.
- **It cannot add a feature.** On Go every useful diagnosis pointed at a compiler option that does not exist
  (re-rank by playout win rate past a gap); rules compare reads with constants, not with each other.
- **Five-game trials on one seed** are still small; the long trial reverted a stale-frame rewrite and kept the reflex
  by clear margins, but a closer call would need more games.

## Files

- Logs: `/mnt/project-files/anygame/learn-loop-v2/` (`ttt/`, `tetris/` with `run1-learn-stderr.log`, the run-2 log
  and two aborted runs, `snake/` with an aborted run, `snake-run2/` for the second attempt with `run-a-two-game-trial/`
  and `aborted-ocr-score/`). Each `bank/` holds `diagnoses.jsonl`, every pack version,
  rejected rewrites and the episode logs.
- Packs: `docs/learn-loop-v2/ttt-learned`, `tetris-old`, `tetris-learned`, `snake-noreflex`, `snake-learned`.
- Code: `anygame/diagnose.py`, `learn.py` (`verify_v2`, `improve_v2`, `trial_verdict`), `cli.py` (`--trial`,
  `--revise-first`, `--legacy` for the first loop), tests in `test/test_learn_v2.py`.

Reproduce (tic-tac-toe from the first trial's bank):
```bash
cd anygame && OPENROUTER_API_KEY=… anygame learn docs/learn-loop-trial/web-tictactoe-base \
  --device "web://https://playtictactoe.org" --sensor jev --episodes 12 --bank <copy of the trial bank> \
  --revise-first --trial 8
```
