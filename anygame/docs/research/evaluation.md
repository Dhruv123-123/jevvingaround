# Evaluating and selecting pack revisions without live trials

Context: anygame's decider (Jev/CLM) is frozen, cheap (200 ms, ~$0.00003) and re-queryable on any banked
state with any frame or question wording; its per-action probabilities are logged every tick
(`action_probs` in `learn.py`). Today a revision is judged by deterministic replay of *recorded* answers
through the candidate's reads and rules, then one live trial episode against the incumbent's median. The
gap: replay never asks Jev what it would say under the *new* frame, and one episode is a noisy label.

## 1. Off-policy / counterfactual evaluation (exists; apply, with a twist)

Standard OPE: inverse-propensity / Horvitz–Thompson and the replay estimator for bandits (Li et al.
2011), per-decision IS (Precup 2000), doubly robust (Jiang & Li 2016), MAGIC (Thomas & Brunskill 2016),
and embedding variants for large action spaces (Cief et al. 2024; Saito 2025 for prompts).

What changes here: the usual pain of OPE, estimating π_target(a|s), disappears. Because the decider is
frozen and re-queryable, π_candidate(a|s_t) on every banked tick is obtained *exactly* by re-querying with
the candidate's typed frame and applying its rules; π_incumbent(a|s_t) is already logged. Per-decision
importance ratios are therefore exact, and the only remaining uncertainty is trajectory drift (after the
first tick where actions differ, later states are off-distribution). Concretely: build a "counterfactual
replay" that (a) re-queries every incident and a sample of ordinary ticks under the candidate frame,
(b) computes per-decision IS / WDR estimates of episode return (won > not lost > longer > higher score)
and a divergence score, and (c) uses the divergence as a truncation horizon (weights beyond a few
diverged steps are meaningless; MAGIC's horizon blending is the right tool). Data: episodes with frames,
`action_probs`, outcomes, all banked. Cost: ~$0.003 for a hundred re-queries per candidate.
For bundled games with a seed (`snake.html?seed=4`) the environment is a simulator, so true
counterfactual rollouts from banked states are possible; for arbitrary sites only OPE is.
New versus published: OPE with an exactly re-queryable target policy over a *representation* change
(frame, not weights) is not in the literature I found; the closest is prompt OPE on logged bandit data
(Saito et al. 2025) and Bhargava et al. 2024 (OPE from logged human feedback).

## 2. Accept/reject with few labels (exists; combine)

The `Calibrator` is a logistic model on eight shape features, activated after six labels. Two upgrades:
- **Prediction-powered inference** (Angelopoulos et al.): use the cheap counterfactual-replay estimate
  from §1 as the "prediction" and trial outcomes as the few gold labels; PPI gives valid intervals for
  "candidate beats incumbent" with far fewer trials than trials alone. Recent LLM-judge work (evalstats; best-arm identification with LLM judges, 2026) has this shape.
- **Split conformal / selective prediction** on the calibrator's score: set the floor (now a fixed 0.35)
  by conformal calibration so the rate of wrongly kept revisions among non-abstained decisions is bounded
  (SCOPE 2026, conformal risk control for LLM outputs). With <30 labels the bound is loose but honest,
  and abstention ("go to trial") is the natural fallback, which is the current behaviour.
Data: existing trial record. Cost: none beyond §1. New: the PPI pairing of re-query estimates with trial
labels; the conformal floor is straightforward application.

## 3. Allocating trial episodes among candidates (exists; apply)

Today one candidate gets one episode. With several proposals per incident (cheap to generate and to
pre-screen by §1), racing is the right allocator: Hoeffding races (Maron & Moore 1993), successive
halving / Hyperband (Li et al. 2018) on partial episodes (ticks survived is a monotone fidelity), and
anytime-valid confidence sequences / e-values (Howard, Ramdas et al. 2021) so the keep/revert test can be
peeked at every tick without inflating false keeps. Concretely: start N candidates on short episodes,
halve on survival ticks, run the survivor until its confidence sequence separates it from the incumbent's
median. Cost: fewer wasted full episodes on obviously bad revisions. New: only the combination with a
§1 prior for the first bracket.

## 4. Which states and episodes to collect next (exists; apply)

Prioritised Level Replay (Jiang et al. 2021) ranks environments by learning potential (value loss); the
analogue here is ranking banked states by *decider disagreement* between incumbent and candidate frames
(cheap to compute by re-query) and by low-margin `action_probs`. Those ticks become the replay set and the
seeds for trial episodes; "overblocked" checks move to high-entropy ticks rather than the last ten. Data: banked frames and probabilities. Cost: re-queries.
New: using a frozen decider's own entropy as the acquisition signal for what to bank.

## 5. Bayesian optimisation over pack hyperparameters (exists; apply)

`support` threshold (0.7), `tick_hz`, `settle`, `sensor_timeout_s`, the calibrator floor and the incident
window are continuous knobs with noisy, expensive objectives; SMAC3 / BoTorch with noisy EI (Ament et al.
2023) handle tens of evaluations. Use §1 counterfactual estimates as a cheap low-fidelity objective and
episodes as high fidelity (multi-fidelity BO). Cost: a few dozen episodes per pack. Nothing new.

## 6. Frozen-LLM prompt/representation optimisation on logged data (exists; new target object)

OPRO, ProTeGi/TextGrad, EvoPrompt, DSPy MIPROv2 and GEPA (ICLR 2026) all optimise text for a black-box
LLM against a scored dataset; GEPA's reflection over trajectories plus Pareto selection is closest to
anygame's chat-model proposer plus lessons. The missing piece in anygame is the *dataset*: with §1, every
banked tick is a scored example (did the re-queried decider avoid the fatal action, keep ordinary
actions, with what margin), so the paragraph, question wording and derived reads can be optimised
offline GEPA-style at $0.00003 per example before any trial. New: the object optimised is a typed frame
and rule set, not a prompt string, and the metric is a counterfactual return estimate, not accuracy.

## Sources
- Li, Chu, Langford, Wang 2011, replay estimator: https://dl.acm.org/citation.cfm?id=1935878 ; GLM extension http://proceedings.mlr.press/v26/li12a/li12a.pdf
- Jiang & Li 2016, doubly robust OPE for RL: http://proceedings.mlr.press/v48/jiang16.pdf
- Thomas & Brunskill 2016, MAGIC: https://arxiv.org/pdf/1604.00923
- Cief et al. 2024/2025, action embeddings for OPE: https://arxiv.org/pdf/2509.00648 ; kernel-weighted IS https://arxiv.org/pdf/2607.15067
- Saito et al. 2025, Prompt optimisation with logged bandit data: https://arxiv.org/html/2504.02646v1
- Bhargava et al. 2024, OPE from logged human feedback: https://arxiv.org/pdf/2406.10030
- Causal Judge Evaluation 2025: https://arxiv.org/html/2512.11150
- Angelopoulos et al., PPI for LLM judges / evalstats: https://arxiv.org/html/2609.35815 ; Regression for the Mean https://arxiv.org/pdf/2411.12665 ; Best-arm identification with LLM judges https://arxiv.org/pdf/2601.21471
- SCOPE selective conformal judging: https://arxiv.org/html/2602.13110v2 ; conformal risk control for LLM outputs https://arxiv.org/pdf/2606.29054
- Maron & Moore 1993, Hoeffding Races: https://proceedings.neurips.cc/paper/1993/file/02a32ad2669e6fe298e607fe7cc0e1a0-Paper.pdf
- Li et al. 2018, Hyperband: https://www.jmlr.org/papers/volume18/16-558/16-558.pdf
- Howard, Ramdas et al. 2021, time-uniform confidence sequences: https://par.nsf.gov/servlets/purl/10251927 ; enterprise A/B use https://arxiv.org/pdf/2302.10108 ; e-values https://arxiv.org/pdf/2410.23614
- Jiang, Grefenstette, Rocktäschel 2021, Prioritized Level Replay: https://proceedings.mlr.press/v139/jiang21b/jiang21b.pdf
- SMAC3: https://jmlr.org/papers/volume23/21-0888/21-0888.pdf ; Ament et al. 2023 noisy EI: https://papers.neurips.cc/paper_files/paper/2023/file/419f72cbd568ad62183f8132a3605a2a-Paper-Conference.pdf
- Yang et al. 2023, OPRO: https://arxiv.org/pdf/2309.03409
- GEPA (ICLR 2026): https://arxiv.org/abs/2507.19457
- CAPO cost-aware prompt optimisation: https://arxiv.org/pdf/2504.16005
- Prompt-format sensitivity (ICLR 2024): https://proceedings.iclr.cc/paper_files/paper/2024/file/6c0e99d736da621403018ca7b32b1a4d-Paper-Conference.pdf ; "Flaw or artifact?" https://arxiv.org/html/2509.01790v1
