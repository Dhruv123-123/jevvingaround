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

Steps 3, 6 and part of 7 exist today. This document adds 1, 4, the held-out check in 4, and the seeds for 2.

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

## Implemented in this commit

- `requery`: the decider re-asked on an incident under a candidate pack; `fatal_avoided`, `agreement`.
- `audit_questions`: value of information of every noul question on the banked decisions.
- `relevance`: mutual information of each read with loss-within-k and with the decider's choice; the gap
  between them names the reads the decider ignores.
- the `predict` read: a located object shifted by its last displacement, for the decision that lands late.
- `improve(..., sensor=)`: a revision must also pass re-query when a sensor is given.
