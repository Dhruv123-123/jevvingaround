# Decision science and the science of asking: what to test on Jev

Every experiment below has one shape: re-query Jev on banked states (episodes and incidents) under variant A/B and score against (a) the recorded outcome (death within k ticks after the chosen action) and (b) an exact oracle the runtime can compute (for Snake: BFS reachability, flood-fill space). 5,000 states x 10 variants is $1.50 and under 20 minutes parallelised. Report action accuracy, Brier score, flip rate; paired bootstrap on the same states.

## 1. Fast-and-frugal trees, take-the-best

One-reason, lexicographic decisions beat weighted integration when cues are redundant and validities vary (Gigerenzer & Goldstein 1996; Gigerenzer & Gaissmaier 2011). The Snake pack already is a fast-and-frugal tree: `exclude` rules are the exits, Jev decides among survivors. The real question is which cues are hard exits (rules) and which are soft judgments (questions). Experiment: from the bank, compute each cue's validity, P(death | cue) against baseline; turn the highest-validity judged cue (`food_reachable_safely`) into a computed BFS read with a rule. Expected effect: large wherever a judged cue can be computed, since Jev cannot do BFS (section 5); near zero for reordering rules, because `exclude` is order-invariant. Skeptical note: FFTs win in humans partly by cutting information cost; here that cost is zero, so the only gain is removing inference from Jev.

## 2. Choice architecture: position, label, default

LLM selectors show 10-15 point swings from slot order in pairwise judgments and 13-75% accuracy gaps when MCQ options are permuted (IJCNLP 2025 study; Pezeshkpour & Hruschka NAACL 2024, who find the sensitivity concentrates where the model is torn between the top 2-3 options). Framing bias in judges (2601.13537) and a "default-to-No" labelling pattern (FramingQA) are documented separately. Jev's `action` is an MCQ in fixed order `up, down, left, right, keep`; `keep` is last and reads as the default, and its description is asymmetric ("turn the snake to move up" vs "turn to move down"). Experiment: rotate the option list (5 rotations), put `keep` first, make descriptions symmetric; the fraction of states whose argmax changes under rotation bounds what order costs. Pack change: order options by the runtime's own preference (directions sorted by `_space`, largest first), which turns position bias into a helpful prior. Expected effect: 5-15% of ambiguous decisions flip; net episode gain smaller, since rules already prune the fatal ones.

## 3. Question decomposition for a small model

Decomposition helps compositional tasks (Zhou et al. 2022; Khot et al. 2022) and binary checklists agree with humans about 20 points better than ternary ratings ("Ask, Don't Judge" 2606.27226; CheckEval). But batching many questions in one call degrades accuracy, sharply for small models: stable to 4, notable drops at 6, Qwen3-4B hit hardest (EMNLP Industry 2025; BatchPrompt). `head_will_hit_something_if_straight` bundles two lookups (ahead, two ahead) in one question. Experiment: split into single-hop nouls; compare Brier against the oracle; then pad to 1/2/4/6/8 questions and watch action accuracy. Pack change: one hop per question; delete questions no rule consumes (section 6). Expected effect: moderate on noul Brier (0.02-0.05), small on the action unless a rule uses the noul.

## 4. Calibration of verbalised probabilities

RLHF models' verbalised probabilities beat their token probabilities and improve further with temperature scaling (Tian et al. EMNLP 2023), yet remain overconfident (2604.01457) and decisions are not always faithful to stated confidence (2601.07767). Experiment: reliability diagram of every banked noul against the oracle; fit a one-parameter temperature map per question and store it in the pack. Pack change: noul thresholds in rules use calibrated values. Expected effect: nil today, because no Snake rule thresholds a noul; but it is the cheapest test of whether nouls carry information at all, so run it first.

## 5. Naming, units, JSON vs text, key order

Format sensitivity is large: one delimiter character moves MMLU by up to 29% (2510.05152); template choice (JSON/Markdown/YAML/plain) shifts accuracy significantly across tasks (2411.10541); natural-language policies beat JSON by ~6 points at equal information (PolicyGuard); renaming variables swings tabular predictions by up to 82% (2508.19563); "The X is Y" templates beat elaborate serialisations (TabLLM). Textual grid reasoning collapses with grid size and relation depth (Spatial-Gym; Lost in Aggregation; KORGym's Snake). Experiment, four cells: `wall` vs `blocked` vs `edge`; `ahead_free: 1` vs `"1 cell"`; JSON frame vs the same facts as sentences; `head_around` first vs last in the frame. Pack change: output key names of the derived reads and `present`. Expected effect: naming 2-5%, JSON vs sentences 3-8%, key order below option order. Skeptical note: the 12x12 matrix is probably noise for Jev once `around` and `locate` carry the facts; test dropping it.

## 6. Value of information: which questions earn their place

A question is worth asking only if some answer changes the action (EVOI; wish-to-know query selection). Experiment: for each banked state, force each noul to 0 and 1 and recompute the action through the rules; a question whose forced values never change the action has zero VOI and only costs batch accuracy. Then estimate, with the oracle, the death-rate reduction if each candidate question were answered perfectly. Pack change: delete zero-VOI questions; add a rule consuming `food_reachable_safely` (exclude the food-seeking direction when p<0.3). Expected effect: the largest available gain, because it converts judgment into policy.

## 7. Optimising the compiler-to-decider interface

DSPy/MIPRO (Opsahl-Ong et al. 2024) treat instructions and demonstrations as parameters around a frozen model and search them by Bayesian optimisation against a metric; production exports frozen prompts. Anygame's revision loop is the same shape with an LLM proposer; what it lacks is a cheap offline metric, which the bank plus oracle supply. Expected effect: modest per iteration, but it makes sections 2-5 automatic.

## Sources

- Gigerenzer & Goldstein, Reasoning the fast and frugal way (1996): https://www.dangoldstein.com/papers/FastFrugalPsychReview.pdf
- Gigerenzer & Gaissmaier, Heuristic decision making (2011): https://economics.northwestern.edu/docs/events/nemmers/2018/gigerenzer2.pdf
- A Systematic Study of Position Bias in LLM-as-a-Judge (IJCNLP 2025): https://aclanthology.org/2025.ijcnlp-long.18.pdf
- Pezeshkpour & Hruschka, LLM sensitivity to option order (NAACL 2024): https://aclanthology.org/2024.findings-naacl.130/
- When Wording Steers the Evaluation: Framing Bias in LLM judges: https://arxiv.org/html/2601.13537
- FramingQA: https://arxiv.org/pdf/2609.07448
- Least-to-Most Prompting: https://arxiv.org/pdf/2205.10625 ; Decomposed Prompting: https://arxiv.org/pdf/2210.02406
- Ask, Don't Judge: Binary Questions: https://arxiv.org/html/2606.27226v1
- Multi-question answering accuracy (EMNLP Industry 2025): https://aclanthology.org/2025.emnlp-industry.129.pdf ; BatchPrompt: https://ar5iv.labs.arxiv.org/html/2309.00384
- Tian et al., Just Ask for Calibration (EMNLP 2023): https://aclanthology.org/2023.emnlp-main.330/
- Wired for Overconfidence: https://arxiv.org/pdf/2604.01457 ; Are LLM Decisions Faithful to Verbal Confidence: https://arxiv.org/pdf/2601.07767
- A Single Character can Make or Break Your LLM Evals: https://arxiv.org/abs/2510.05152
- Does Prompt Formatting Have Any Impact on LLM Performance: https://arxiv.org/pdf/2411.10541
- PolicyGuard (NL vs JSON policies): https://arxiv.org/pdf/2608.02687
- Robustness is Important: Limitations of LLMs for Data Fitting: https://arxiv.org/pdf/2508.19563 ; TabLLM: https://proceedings.mlr.press/v206/hegselmann23a/hegselmann23a.pdf
- Spatial-Gym: https://arxiv.org/pdf/2604.09338 ; Lost in Aggregation: https://arxiv.org/pdf/2606.22219 ; KORGym: https://arxiv.org/pdf/2505.14552
- Value of information / EVSI: https://en.wikipedia.org/wiki/Expected_value_of_sample_information ; Wish-to-know query selection: https://deepblue.lib.umich.edu/items/f13704e2-48ab-4478-ab4c-a4f1ec16ec7d
- MIPRO / DSPy: https://arxiv.org/pdf/2502.18746 ; https://tianpan.co/blog/2026/04/16/automated-prompt-optimization-dspy-mipro
