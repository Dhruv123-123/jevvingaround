# Oracle-in-the-loop frame search

How a system whose decider cannot be trained gets better anyway. Synthesised from five research notes
(`docs/research/`: representation, evaluation, control, decision science, evolution), each of which read the
runtime first and searched its own field for what applies, what exists, and what would be new.

## The one fact everything rests on

The decider (Jev, or CLM) is frozen, fast and cheap, and it can be **asked again**. Every banked state, with any
alternative frame, question wording, option order or rule set, can be put to it offline in 200 ms for
$0.00003. That single property changes the problem class:

- Off-policy evaluation, whose hard part is estimating what the new policy would do on old states, becomes
  exact: the candidate's action distribution on every banked tick is obtained by re-query, the incumbent's is
  already logged (`action_probs`). Per-decision importance ratios need no model of the policy.
- The decider becomes an oracle for its own input relevance: which reads move its answers and which it
  ignores can be measured, not guessed.
- Choice architecture (option order, naming, question decomposition) becomes an A/B test on banked states
  against recorded outcomes and an exact oracle (flood fill, reachability), not a prompt-writing craft.

No published system optimises the structural input of a frozen probabilistic judge this way. Prompt
optimisation of frozen models exists (OPRO, MIPROv2, TextGrad, GEPA); LLM-proposed features verified by
execution exist for retrainable heads or planners (CAAFE, pix2pred); shields grown from incidents exist (AIR,
catastrophic-pairs shields); latency compensation exists for trained policies (Firoiu, LagComp). The
combination, with counterfactual replay and re-query as the verifier and a pool of games as the memory, is
the new object. See the novelty verdicts in each note.

## The method, as a loop

```
bank: every tick's frame, typed frame, action_probs, choice, rules; incidents; outcomes; trial labels
  │
  ├─ 1. audit (offline, no model)         what is in the frame that the decider ignores? which questions
  │                                        never change the action? which cue predicts loss best?
  ├─ 2. propose (chat model, k candidates) revisions of reads, rules, questions, paragraph, option order,
  │                                        seeded by the audit, the lessons, and the best reverted candidate
  ├─ 3. screen (replay, milliseconds)      recorded answers through the candidate: fatal guarded or visible,
  │                                        ordinary decisions allowed, earlier incidents intact, no cell rules
  ├─ 4. score (re-query, seconds)          the decider itself on the banked states under the candidate frame:
  │                                        fatal avoided? agreement on ordinary ticks? a held-out set of
  │                                        non-incident ticks not flipped? a counterfactual return estimate
  ├─ 5. gate (calibrator)                  the shape of the revision against the record of what survived,
  │                                        with a conformal floor once there are enough labels
  ├─ 6. race (trial episodes)              the survivors play, early-stopped against the incumbent's curve
  └─ 7. keep, learn, share                 kept revisions become lessons; lessons become templates; the
                                           calibrator and the proposer's prompt improve from the record
```

Steps 3, 6 and part of 7 existed first. The two slices below add 1, all of 4 (re-query, the held-out check, the counterfactual return), the floor in 5, the seeds for 2, and the control-theory reads.

## What changes in the pack, and why each is safe

| change | from which field | verified by |
|---|---|---|
| a derived read the decider needs (a margin after each action, a flood-fill room, a predicted position) | control theory: discrete barrier functions, dead-time compensation | replay and re-query: the fatal tick becomes visible or guarded, ordinary ticks stay |
| a rule promoted from a question the decider gets right but never acts on | fast-and-frugal trees: hard exits before soft judgment | value-of-information audit: forcing the answer through the rules changes the action |
| a question deleted because no answer ever changes the action | decision theory, batching studies | the same audit; fewer questions per call raise accuracy on small models |
| a read promoted because it predicts loss and the decider ignores it | conditional mutual information against the decider's own outputs | relevance audit on the bank |
| option order and names | position and framing bias studies on LLM selectors | A/B re-query against outcomes and an exact oracle |
| the paragraph | GEPA-style reflection over trajectories | re-query score, then trial |

## What stays fixed, on purpose

The decider's weights. The set of read kinds and rule forms (code). The trial episode as the last word: every
offline score is a prior, not a verdict, because a wrong read is invisible to replay and to re-query alike.
That is the warning the control note ends on and it stands.

## Honest limits

- One negative example per incident underdetermines any induction; the held-out check and the earlier
  incidents are what keep proposals from fitting one loss.
- Re-query agreement measures agreement with the decider, not correctness; it is a screen, not a reward.
- Racing and archives cost trials; at six to eight episodes per game the budget buys one candidate on trial
  at a time, so the screens have to do the work.
- LLM mutation collapses to cycles without novelty rejection ("Mutation Without Variation", GECCO 2026); the
  proposer is shown the best reverted candidate and refused a structural duplicate of a reverted one.

## Implemented

First slice:

- `requery`: the decider re-asked on an incident under a candidate pack; `fatal_avoided`, `agreement`.
- `audit_questions`: value of information of every noul question on the banked decisions.
- `relevance`: mutual information of each read with loss-within-k and with the decider's choice; the gap
  between them names the reads the decider ignores.
- the `predict` read: a located object shifted by its last displacement, for the decision that lands late.
- `improve(..., sensor=)`: a revision must also pass re-query when a sensor is given.

Second slice (the rest of step 4, the floor in step 5, and the control-theory reads):

- **Counterfactual return with divergence truncation** (`counterfactual`, `counterfactual_return`). The logged
  policy's probability of each logged action is the record's `action_probs` renormalised over what its rules
  allowed (every exclusion is logged); the candidate's is the re-query distribution renormalised over what its
  rules allow. The weight walks the logged path as the product of the ratios, clipped at 5; at the first tick
  where the candidate would almost surely not have taken the logged action (probability under 0.05) the logged
  trajectory stops informing it, so the walk is cut and the loss is not attributed. A guarded fatal tick has
  ratio 0 and ends the same way. Over every banked loss this gives the candidate's estimated losses against the
  incumbent's logged ones, and an effective sample size; a revision must leave more of the banked losses than
  the incumbent did. The whole estimate costs a few cents.
- **Held-out ordinary ticks** (`Bank.add_holdout`, `holdout_check`). Every episode banks a reservoir sample of
  six decisions, with frames, outside the fatal window; a revision is re-asked on the newest 24 and must keep
  the recorded choice on 60% of them. This is the check an incident alone cannot give: a fix that changes what
  the decider does everywhere is drift, not learning.
- **Option-order A/B** (`audit_order`, `anygame audit --sensor`). The same frames, the actions listed as
  authored, reversed, alphabetically and shuffled; per order, how often the first option is picked (1/k is no
  bias), how often the raw choice is one the rules exclude (the rules as the exact oracle), agreement with the
  record, and whether the fatal choice is repeated. The proposer may reorder `act`; such a revision is invisible
  to replay and is accepted only by re-query.
- **Conformal floor for the calibrator**. Every kept revision is scored by a model fitted without it; the floor
  is the ⌊α(n_kept+1)⌋-th smallest of those scores (α = 0.25, capped at 0.9), so a future revision as good as the
  kept ones is refused with probability at most α. With fewer than three kept revisions no veto is justified and
  the calibrator abstains: the trial decides.
- **Margin reads** (`margin`). The discrete control barrier function on a grid: the room reachable from where the
  mover will be when the action has landed, `lag` cells on, per direction, with `<dir>_ok` when the room after
  keeps at least `1 - alpha` of the room now; a numeric form gives a number's distance to its bounds. A rule on
  `<dir>_ok` is the k-step guard the control note asked for.
- **A per-tick budget** (`budget_ms`). When perception plus the decider's recent latency exceeds the budget, the
  tick skips the decider and the rules act on its last answers (the post-posed shield), at most
  `budget_skip_max` ticks in a row so a slow decider is never starved out.

### Measured on the real bank

`anygame audit` on the eight-episode Snake bank (four banked losses, forty decisions, real Jev):

| order the actions are listed in | picks a rule-excluded action | first option picked | agrees with the record |
|---|---|---|---|
| as authored `[up, down, left, right, keep]` | 28% | 20% | 75% |
| alphabetical `[down, keep, left, right, up]` | 52% | 0% | 75% |
| shuffled `[left, right, keep, up, down]` | 60% | 0% | 75% |
| reversed `[keep, right, left, down, up]` | 62% | 45% | 75% |

The rules hide this at play time (the final choice agrees with the record under every order), which is why
nobody would have noticed it: listed `keep` first, the decider wants `keep` 45% of the time against 20% for no
bias, and wants an excluded move twice as often. The counterfactual return of the learned pack v4 on its own
bank: it leaves three of the four banked losses (ratio 0 at the fatal tick, the rules it grew) and still owns
the fourth with weight 0.63, the pocket death at tick 408 that no single-step rule catches. The first tick of
every window re-asks at ratio 0.33 to 0.40: the re-query starts cold, with no `head_prev`, so the frame there is
not the frame the record saw. That is a known bias of the estimate, in the conservative direction.

A `margin` read with `lag: 0` (one decision per game step on this Snake, so nothing advances while the decider
thinks) added to v4 separates the fatal tick in all four banked losses by replay (`room.safe` is `[up]` and the
three other directions read 0), yet cannot guard any of them: at that frame every direction is already closed
by one rule or another, so the rules are infeasible and the choice stands (the record now says so). The trap
closed ticks earlier, which is what the barrier condition `<dir>_ok` at those earlier ticks is for, and what
the proposer is shown. With `lag: 1` the same read reports the path, not the cell, and is the right setting for
a game that keeps moving while the decider thinks.

## Read against SIMA 2, and built from it

`docs/research/sima2.md` reads DeepMind's SIMA 2 report (December 2025) against this runtime. What transfers
without training a model is now built:

- **Tasks and a task setter.** `tasks:` in the pack, each a goal with a verifier over the reads; the decider is
  told one at a time; the setter (the chat model, from the typed frame and the frame) proposes new ones, steered
  to the weakest category by the record in `tasks.jsonl`; the author writes the first from the demonstration.
- **Positive incidents.** A completed task or a win banks the last decisions as a success span; `verify_revision`
  refuses any revision that blocks a choice in one; the pack that first completes a task yields lessons. Episodes
  rank by won, then tasks done, then survival, so a trial can be won by practice, not only by not dying.
- **An evaluation suite.** `anygame suite`: per task, done within its limit and done at all, per category, against
  a reference; the pack as written is the held-out number.
- **An episode rater with calibration.** The chat model scores sampled frames and the action log 0 to 100 for
  completion and directedness; it stands in for the score where a pack has none, and `calibrate` reports its
  pairwise agreement with the trial order, with the rating left out of that order so it cannot vouch for itself.
- **Held inputs, relative mouse, chunks.** `hold_ms` on a key, `mouse_move`, and `chunk` actions mined from a
  demonstration's recurring key runs.

What does not transfer: anything that fine-tunes the decider, which in SIMA cost the base model up to 25% on
reasoning benchmarks and which this design avoids by construction.

Measured live on the bundled Snake with real Jev and the chat model setting tasks: the suite over two packs and
two seeds completed `first_food` on every run and `five_food` within its limit on the pixel pack (the state pack
reached it only past the limit, which is what the "at all" column is for); the setter's first proposals pinned
tasks to an exact cell ("navigate to the food at c10r3"), which failed six times in a row before two fixes: a
task that tests the exact cell of a located read is refused like a cell rule, and a task that has failed twice
in a run waits for the next one. After that the setter proposed relational tasks ("a position with at least
seven open cells to the right", "clear the cell beside the body"), all completed, and the rater scored the two
episodes 100 and 85 for completion with notes that matched the play. The rater's first answers were empty for
the same reason the stall labeller's once were: a reasoning model needs a token budget before it answers.
