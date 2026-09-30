# Representation learning without training the decider

**Setting.** Jev is frozen; the frame (derived reads), questions, rules, actions and timing can move. Logged per tick: `screen` (the typed frame), `action_probs`, `choice`, rules fired, `support`. Per incident: the last ~10 records plus PNG frames and device state (bank keeps four). Per episode: only a summary (ticks, reason, score, won/lost, version). Per revision: shape features and kept/reverted. `learn.separators()` is already one-shot feature selection (keys whose fatal-tick value differs from every healthy tick). Whole-episode per-tick frames live only in the run log; §3–5 need the bank to retain them.

## 1. ILP and predicate invention

FOIL (Quinlan 1990) greedily grows Horn clauses; Metagol invents predicates via metarules; Popper/Poppi (Cropper & Morel 2021) generate-test-constrain with automatic invention; ILASP (Law, Russo, Broda) learns answer-set programs including weak constraints (preferences). IGGP (Cropper, Evans & Law 2019) learned game *rules* from traces of 50 games and found it hard for ILP.

Here: translate the typed frame into facts (`cell(R,C,Sym)`, `adjacent/2`, the `locate`/`around` outputs), label the fatal (frame, action) negative and ordinary ticks positive, and learn `unsafe(Action) :- …`. The body is directly an `if: {read…} exclude:` rule; an invented predicate is a candidate derived read. Popper's loop maps onto propose → replay → constrain, with replay as the test stage. Cost: seconds, no model call. Limits: one negative and ~9 positives per incident leaves the hypothesis underdetermined (replay's "ordinary decisions stay allowed" is the same guard), and invention is confined to the BK vocabulary: flood-fill "space" is not invented unless adjacency and recursion are supplied. Prior art learns shields and game rules, not features for a frozen judge. Realistic use: a second proposer beside the chat model.

## 2. DreamCoder-style library learning

DreamCoder (Ellis et al. 2021) and LILO (Stitch compression plus LLM auto-documentation) grow abstraction libraries by MDL over many solved programs; Voyager keeps a verified skill library with frozen GPT-4. anygame's `lessons:` is this in embryo: anti-unify kept rules across packs into templates ("guard `<action>` when `<locate>_<dir>_space < <length>`"). With five lessons this is templating, not learning; read *kinds* stay code.

## 3. Rule induction from logged decisions

RIPPER (Cohen 1995), CN2 (Clark & Niblett 1989) and Bayesian Rule Lists (Letham et al. 2015; Yang et al. 2017) learn ordered rule lists from flat tables. Flatten `screen`, label by a credit window (action followed by loss within k ticks), induce a list; each rule is a pack `rules:` entry, replayable in milliseconds. Needs whole-episode records and a few hundred ticks; one fatal tick per episode forces window labels or Jev's `action_probs` as soft targets. Distilling a frozen policy into rules exists (VIPER, shields); learning only a *residual guard* over a frozen judge is a narrow, cheap variant.

## 4. Feature selection by information gain / conditional MI

Brown, Pocock, Zhao & Luján (JMLR 2012) unify mRMR, JMI, CIFE as approximations to conditional likelihood. Two targets, both milliseconds: (a) Y = loss-within-k → which reads carry danger; (b) Y = Jev's `choice`/`action_probs` → which reads Jev actually responds to. A read high on (a) and low on (b) is one Jev ignores: promote it to a question or rule. (b) uses the frozen decider as an oracle for its own input relevance, which I did not find elsewhere.

## 5. Information bottleneck

Tishby, Pereira & Bialek (1999): compress X to T keeping I(T;Y). Agglomerative IB on discrete reads yields principled binnings (collapse `left_space` integers to {less than snake, enough}), apt for a model that cannot compare numbers. The *decodable* IB (Dubois et al. 2020) conditions on a fixed decoder family, the right theory for a frozen decider, though used so far with trained decoders.

## 6. Concept bottleneck models

CBMs (Koh et al. 2020) and Label-Free CBM (Oikarinen et al. 2023: GPT-3 proposes concepts, CLIP grounds them, a sparse head is trained) are the typed frame's nearest relative; noul questions are concepts. Transferable: concept pruning (unused, redundant, unpredictive) and *intervention* (flip a concept, re-ask Jev: a 200 ms counterfactual, which replay cannot do since it reuses recorded answers). The trained head does not transfer; Jev is the head.

## 7. LLM-proposed features verified by execution (2023–2026)

FunSearch (Nature 2023) and AlphaEvolve (2025): LLM mutates programs, an evaluator scores, islands keep diversity. CAAFE (2023): LLM writes feature code, kept only if cross-validation improves, single path. OCTree (NeurIPS 2024): decision-tree feedback to the LLM. LLM-FE (ICLR 2026): evolutionary with multi-population memory. Predicate invention: pix2pred (2024/25) has a VLM propose predicates from demos, then hill-climbs to the smallest subset a planner can use; IVNTR (2025) and "Unifying Deep Predicate Invention with FMs" (Dec 2025) iterate LLM hypotheses against learned feedback.

anygame is already CAAFE-shaped (propose, execute via replay, keep/revert, lessons as memory). The FunSearch gap is a dense scalar and a population: replay over *all* banked incidents (incidents guarded, overblock, support) is a free score, so a 4–8 candidate population per incident costs only chat tokens; the trial episode stays the expensive final gate.

## Novelty verdict

Optimising a frozen model's *instructions and demonstrations* against a metric is established (OPRO, MIPROv2, TextGrad, BlackVIP); the `play` paragraph and question wording fall there. Optimising the *structural* input — inventing executable derived reads and binnings for a frozen probabilistic judge, scored by episode outcome and checked offline by replaying recorded answers — has no exact precedent in what I found: pix2pred and CAAFE verify LLM-proposed features by execution but feed a planner or a retrainable classifier; ILP feeds symbolic engines. New-looking and cheap: the MI-against-Jev diagnostic (§4b) and replay as population fitness (§7). Absence across ~15 searches is not proof of absence.

## Sources
- Popper: https://link.springer.com/article/10.1007/s10994-020-05934-z ; Poppi: https://arxiv.org/pdf/2104.14426
- ILP at 30: https://link.springer.com/article/10.1007/s10994-021-06089-1
- Metagol: https://www.doc.ic.ac.uk/~atn/papers/metagol_mlj.pdf ; FOIL: https://en.wikipedia.org/wiki/First-order_inductive_learner
- ILASP: https://arxiv.org/pdf/2005.00904 ; IGGP: https://www.semanticscholar.org/paper/a3d5ae5a9a206b33c3f9d0fbdaf44a4414f6258a
- DreamCoder: https://www.cs.cornell.edu/~ellisk/documents/dreamcoder_with_supplement.pdf ; LILO: https://arxiv.org/abs/2310.19791 ; Voyager: https://arxiv.org/abs/2305.16291
- Scalable BRL: https://arxiv.org/pdf/1602.08610 ; CORELS: https://dl.acm.org/doi/10.1145/3097983.3098047
- Brown et al. 2012: https://www.jmlr.org/papers/volume13/brown12a/brown12a.pdf
- Information bottleneck: https://arxiv.org/html/arXiv:physics/0004057 ; Decodable IB: https://arxiv.org/pdf/2009.12789
- Label-Free CBM: https://arxiv.org/abs/2304.06129 ; CB-LLM: https://arxiv.org/html/2412.07992v1
- FunSearch: https://deepmind.google/blog/funsearch-making-new-discoveries-in-mathematical-sciences-using-large-language-models/ ; AlphaEvolve: https://arxiv.org/abs/2506.13131
- CAAFE: https://arxiv.org/abs/2305.03403 ; OCTree: https://arxiv.org/abs/2406.08527 ; LLM-FE: https://arxiv.org/pdf/2503.14434
- pix2pred: https://www.alphaxiv.org/es/abs/2501.00296 ; IVNTR: https://arxiv.org/abs/2502.08697 ; Deep predicate invention with FMs: https://arxiv.org/abs/2512.17992 ; Silver et al. 2022: https://arxiv.org/abs/2203.09634
- MIPROv2: https://arxiv.org/pdf/2406.11695 ; TextGrad: https://arxiv.org/abs/2406.07496 ; BlackVIP: https://arxiv.org/pdf/2303.14773
