# Control theory, robotics and safe RL: what they say about anygame's tick

anygame's tick is a sampled-data control loop with dead time: frame at t, action lands at t+270 ms (p95 370 ms), on a plant that steps every 170–700 ms. The rules are a runtime enforcer around a frozen policy.

## 1. Shields and runtime enforcement

Alshiekh et al. (AAAI 2018) synthesise a shield from a safety automaton plus an environment abstraction; *preemptive* shields hand the learner the safe action set, *post-posed* shields override an unsafe choice. anygame's `exclude`/`only` rules are preemptive; "rules on last answers" after a Jev timeout is post-posed. What anygame lacks: (a) the shield reasons about the *next k steps* (Könighofer et al., online shielding: block an action if the k-step violation probability exceeds a threshold). A Snake wall rule is k=1; the "self-trapping late in a long snake" deaths are k≥3 failures no single-tick read catches, which is where a flood-fill margin read (section 2) belongs. (b) Conformal shielding for imperfect perception (Scarbro et al. 2025) allows an action only if it is safe for *every* state estimate in a conformal set; anygame's read confidences are the raw material, but rules fire on point values. Cheap version: a rule that excludes anything not safe under both the current and `_prev` value when confidence is low.

Closest prior art to "shield grown from losses": "Learning a Shield from Catastrophic Action Effects" (2022) stores catastrophic (state, action) pairs and forbids them, with no generalisation; anygame's rules over reads *are* the generalisation, and replay is the check exact-pair methods skip. AIR (2026) has an LLM synthesise guardrail rules from agent incidents; its abstract does not mention replaying past incidents, so "checked against earlier incidents too" is a real addition.

## 2. Control barrier functions, discrete analogue

Discrete-time CBFs (Agrawal & Sreenath 2017) require h(x_{k+1}) ≥ (1-α) h(x_k) for a scalar safety margin h. The grid analogue is a *margin read*: Snake, free cells reachable from the head after the move (flood fill); Tetris, holes plus height; the shooter, distance to the nearest projectile. `exclude any action whose margin_after < margin_now - k` is a DCBF constraint. It needs a one-step simulator per candidate action, the machinery `tetris` already has (`after[...]` per landing); cost is microseconds on a 12×12 grid. Skeptical note: CBF invariance holds only if the model is right and a feasible action always exists. The rules already fall back to `wait`, which on Snake is not safe, so infeasibility must become an incident, not be swallowed.

## 3. Dead-time compensation

The Smith predictor acts on a model-predicted output so the controller never sees the delay; it goes unstable when the delay or model is wrong. The RL versions: Walsh et al. 2009 (Model Based Simulation: roll the last state forward through the pending actions; tractable only in the deterministic case), Firoiu et al. 2018 (a learned forward model "undoes" the delay; Melee against pros at human reaction time), Ramstedt & Pal 2019 (RTMDP: the state changes while you decide, so condition on the previous action), and LagComp (2026: forecast features by the *measured* latency, 26→88% success at 320 ms). Two versions that compile into the typed frame so Jev stays frozen:

- **`predict` read**: `{kind: predict, of: enemy, by: latency}` shifts a located object by its per-tick displacement times `latency_ms / tick_ms`. Needs: velocity magnitude in the history layer (only `_moving` direction exists) and the latency EWMA the loop already measures. Cost nil. Pays on the shooter and Flappy, not on turn-based games or Snake, where the mover is the player.
- **Per-pack one-step transition table** from the bank: key = (values of named reads, action) → next values. `Decision` already holds values and answers per tick, so this is a dict built at load. It only works where the local state is small and deterministic (grid games); on a shooter the key never repeats. Log prediction error per key as the read's confidence.

The `reachable` filter in `tetris.py` is already a pending-action-aware compensator (drop landings the piece can no longer reach), and "enumerate at frame time, prune at landing time" generalises better than shifting observations.

## 4. MPC with a learned discrete model

Latent world-model MPC (TD-MPC-style) is the wrong shape: anygame's model is per-read, symbolic and exact where it exists. The realistic form is receding-horizon enumeration over derived reads: depth-1 for 2048 (four swipes), depth-1 with consequences for Tetris (done), depth-2 flood-fill for Snake. Beyond depth 2 the bank cannot supply transitions and compounding error kills it. Use the bank to *replay* rules, as now, not to plan.

## 5. Anytime decisions and cascades

Zilberstein's contract algorithms fit: Jev is a 200 ms contract, rules-on-last-answers the interruptible fallback. Missing is a per-tick *budget*: if `latency_ewma + act_time > time_to_next_step`, skip Jev and let the rules act on the last answers; the loop already does this on error, so it is a scheduling change. Cascades (Jitkrittum 2023; Gatekeeper 2025; Mozannar & Sontag 2020) show confidence deferral works only when the small model is calibrated; CLM's similarity scores are not probabilities, so CLM→Jev needs a threshold tuned on the bank with Jev's recorded probabilities as labels. Order rules → CLM → Jev → VLM by cost, defer on a small top-two margin, and record the margin so the Calibrator can learn the threshold.

## Has the combination been done?

Not as one system. Frozen policy + latency compensation: Firoiu, LagComp. Policy + shield: Alshiekh, Könighofer. Shield grown from incidents: catastrophic-pairs shield, AIR. Latency compensation *compiled into the shield's own inputs* and verified by replay against banked incidents appears in none; the nearest, conformal shielding, is offline. The gap control theory warns about remains: predictors and shields both assume the model, anygame's model is a set of reads, and a wrong read is invisible to replay.

## Sources

- Alshiekh et al., Safe RL via Shielding, AAAI 2018: https://ojs.aaai.org/index.php/AAAI/article/view/11797
- Könighofer et al., Online Shielding for RL, ISSE 2022: https://arxiv.org/abs/2212.01861
- Könighofer et al., Safe RL via Probabilistic Shields: https://arxiv.org/pdf/1807.06096
- Scarbro et al., Conformal Safety Shielding for Imperfect-Perception Agents, 2025: https://arxiv.org/abs/2506.17275
- Learning a Shield from Catastrophic Action Effects, 2022: https://arxiv.org/abs/2202.09516
- AIR: Improving Agent Safety through Incident Response, 2026: https://arxiv.org/html/2602.11749
- Agrawal & Sreenath, Discrete Control Barrier Functions, RSS 2017: https://www.semanticscholar.org/paper/fd8900782d2535fe5d3c9dd6cbd63da3a4da16a3
- Walsh, Nouri, Li, Littman, Planning and Learning in Environments with Delayed Feedback, 2007/2009: https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/Published-12.pdf
- Firoiu et al., At Human Speed: Deep RL with Action Delay, 2018: https://arxiv.org/abs/1810.07286
- Ramstedt & Pal, Real-Time RL, NeurIPS 2019: https://proceedings.neurips.cc/paper/2019/hash/54e36c5ff5f6a1802925ca009f3ebb68-Abstract.html
- LagComp: Compensating Observation-to-Action Latency, 2026: https://www.researchgate.net/publication/408480948
- Handling Delay in Real-Time RL, 2025: https://arxiv.org/html/2503.23478v1
- Zilberstein, Real-Time Problem-Solving with Contract Algorithms, IJCAI 1999: https://www.ijcai.org/Proceedings/99-2/Papers/049.pdf
- Jitkrittum et al., When Does Confidence-Based Cascade Deferral Suffice?, 2023: https://arxiv.org/abs/2307.02764
- Gatekeeper: Improving Model Cascades Through Confidence Tuning, 2025: https://arxiv.org/abs/2502.19335
- Mozannar & Sontag, Consistent Estimators for Learning to Defer, ICML 2020: https://proceedings.mlr.press/v119/mozannar20b.html
