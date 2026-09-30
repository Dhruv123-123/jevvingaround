# Evolutionary computation, quality-diversity and LLM program search: what maps onto packs

**The frame.** anygame's loop is already a (1+1) evolution strategy with an LLM mutation operator: one incumbent pack, one candidate per loss, a cheap deterministic filter (replay), an expensive fitness evaluation (a trial), a learned acceptance prior (`Calibrator`, eight features in `learn.py`) and horizontal transfer through `lessons` (`pool_lessons`). Costs: replay ~ms, a Jev re-query on a banked state ~200 ms, a trial 1–2 min.

## 1. LLM-proposed programs scored by an evaluator: FunSearch, AlphaEvolve, ELM, ShinkaEvolve

FunSearch pairs an LLM with an evaluator and an island population, culling and reseeding islands from the best. AlphaEvolve's database is "inspired by a combination of MAP-Elites and island models". ELM (Lehman 2022) is the origin: LLM diffs as the mutation operator inside MAP-Elites. ShinkaEvolve cuts the thousands of evaluations these need with adaptive parent sampling and novelty rejection of proposals.

*Mapping.* The pack is the program, `replay(pack, incident)` the cheap evaluator, the trial the expensive one. Two things carry over without extra trials: (a) **novelty rejection before trial**: hash the candidate's rule/read diff and refuse proposals that duplicate a reverted one (the calibrator does this statistically, not structurally); (b) **several parents in the prompt** (FunSearch samples k programs ranked by score): show the proposer the incumbent *and* the best reverted candidate with its trial number.

*Skeptical.* FunSearch spent millions of samples and AlphaEvolve's evaluators are exact; a pack's fitness is one noisy episode against a stochastic game. "Mutation Without Variation" (GECCO '26) shows LLM mutation chains collapse to short cycles and structural homogeneity, and "Evolution or Illusion?" (2026) that claimed gains often vanish under proper evaluation. At 6–8 trials per game, islands preserve diversity the budget cannot explore.

## 2. Prompt evolution: EvoPrompt, Promptbreeder

EvoPrompt runs GA/DE over prompts scored on a dev set; Promptbreeder also evolves the *mutation prompts*. *Mapping.* The `play` paragraph is a Jev prompt and is already mutated. The cheap Promptbreeder move is meta-level: evolve the **revision prompt** (the `hints_text` framing, which incidents are shown), scored by keep rate. But the dev set EvoPrompt relies on is what anygame lacks: scoring a paragraph needs a trial, unless banked states are re-queried (200 ms × N), which measures agreement with recorded Jev answers, not outcome.

## 3. MAP-Elites, QD archives, QDAIF, novelty search

MAP-Elites keeps one elite per behaviour cell; QDAIF lets an LLM assign the descriptor. *Mapping.* Descriptors for a per-game pack archive: rule count, derived-read count, fraction of ticks a rule fired (`overblocked` already exists), mean support, tick latency. *Skeptical.* Each cell costs a trial; a 4×4 archive is 16+ episodes before it holds anything the loop does not. Novelty search is the wrong tool: survival is not a deceptive objective in Snake or 2048, and Tic-tac-toe's deadlock is a missing read, not a local optimum. The one QD idea worth taking is descriptor-conditioned *acceptance*: keep a reverted candidate if it is best in an empty cell, so later crossover has material.

## 4. Racing and PBT

F-Race/irace drop candidates as soon as a Friedman test separates them; PBT copies and perturbs within a training population. *Mapping.* This is where the trial budget can be cut: stop a trial early once the candidate is behind the incumbent's per-tick score curve by a margin, and race two candidates for half an episode each before committing. PBT over a population of packs is again more trials than the loop has.

## 5. Genetic improvement of software

GI evolves patches against a test suite; the Petke survey stresses overfitting to that suite. *Mapping.* Replay is a regression suite of incidents; checking earlier incidents too is GI's anti-overfit measure, and the from-scratch kept/reverted counts (Snake 3/1, Tic-tac-toe 3/2) show overfit still passes it. GI's remedy is held-out tests: re-query Jev on banked *non-incident* states (50 states, ~10 s) and require the candidate's rules not to flip the chosen action on ticks that went well. That is counterfactual, where plain replay only re-filters recorded answers.

## 6. Library learning: DreamCoder, LILO, Voyager

DreamCoder compresses solved programs into a library; LILO adds LLM auto-documentation so abstractions get reused; Voyager's skill library is verified executable code. *Mapping.* `lessons` is a library with neither compression nor documentation: raw YAML filtered by read kind. The cheap LILO move: after N kept revisions across the pool, have the chat model cluster lessons into named, parameterised templates with a one-line docstring ("guard moves into cells holding X via `around`"). The LEGO-Prover case study warns that undocumented libraries go unused, which matches Tic-tac-toe never finding the one-line `locate` move generator.

## 7. Transfer across games

Taylor & Stone's metrics (jumpstart, asymptotic performance, time-to-threshold, area ratio) are directly measurable: run `from_scratch.sh` with the pool held out (done) versus with lessons on, and report first-episode ticks and episodes-to-cap per game. What transfers is predictable by structure: `locate/runs/around` rules move between grid games, shooter and Flappy lessons will not; `hints_text` filtering by read kind is the right minimal gate.

## What is new

Published LLM-evolution systems evolve the *program that acts*. Here the decider is frozen and only its **input representation** (derived reads) and **guards** (rules) evolve, checked by **counterfactual replay** of recorded decisions through the candidate representation, then by re-querying the frozen decider on banked states, and shared across games as verified snippets. Nearest neighbours are GI's test-based patching and Voyager's verified skills; neither evolves the observation channel of a fixed policy or pools across tasks with a learned acceptance prior. Honest framing: a low-budget (1+1)-ES with a static verifier and a transfer library. QD and island machinery would be a paper claim untestable at eight trials per game.

## Sources
- Romera-Paredes et al., FunSearch, Nature 2023: https://www.nature.com/articles/s41586-023-06924-6
- Novikov et al., AlphaEvolve, 2025: https://arxiv.org/abs/2506.13131
- Lehman et al., Evolution through Large Models, 2022: https://arxiv.org/abs/2206.08896
- Lange et al., ShinkaEvolve, 2025: https://arxiv.org/abs/2509.19349
- Gurkan et al., Mutation Without Variation, GECCO '26: https://arxiv.org/abs/2606.05408
- Evolution or Illusion? Rethinking Evaluation in LLM Evolutionary Search, 2026: https://arxiv.org/abs/2609.19799
- Guo et al., EvoPrompt, ICLR 2024: https://arxiv.org/abs/2309.08532
- Fernando et al., Promptbreeder, 2023: https://arxiv.org/abs/2309.16797
- Mouret & Clune, MAP-Elites, 2015: https://arxiv.org/abs/1504.04909
- Bradley et al., QDAIF, ICLR 2024: https://arxiv.org/abs/2310.13032
- Lehman & Stanley, Abandoning Objectives, ECJ 2011: https://www.cs.swarthmore.edu/~meeden/DevelopmentalRobotics/lehman_ecj11.pdf
- Birattari et al., F-Race, GECCO 2002: https://iridia.ulb.ac.be/~stuetzle/publications/GECCO02.pdf
- López-Ibáñez et al., irace: https://sciencedirect.com/science/article/pii/S2214716015300270
- Jaderberg et al., Population Based Training, 2017: https://arxiv.org/abs/1711.09846
- Petke et al., Genetic Improvement of Software: A Comprehensive Survey, IEEE TEVC 2018: https://www.researchgate.net/publication/316469216
- Ellis et al., DreamCoder, PLDI 2021: https://dspace.mit.edu/bitstream/handle/1721.1/145949/3453483.3454080.pdf
- Grand et al., LILO, ICLR 2024: https://arxiv.org/abs/2310.19791
- LLM Library Learning Fails: A LEGO-Prover Case Study, 2025: https://arxiv.org/abs/2504.03048
- Wang et al., Voyager, 2023: https://arxiv.org/abs/2305.16291
- Taylor & Stone, Transfer Learning for RL Domains, JMLR 2009: https://www.jmlr.org/papers/volume10/taylor09a/taylor09a.pdf
