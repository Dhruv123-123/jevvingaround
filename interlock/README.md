# Interlock for Gmail

A 100 ms judgment on every Send. The sensor is [TypeSafe Jev](https://typesafe.ai); the policy is yours.

Every interlock that exists today is either too slow (people turn it off) or too dumb (people click through it).
Jev evaluates ~15 independent questions about a draft in one ~100 ms call, for about $0.00005.
That is cheap and fast enough to score the draft **while you type**, so when you reach for Send the verdict for
that exact draft is already cached — effective latency at the click is zero.

```
keystroke ─▶ pause 400 ms ─▶ state compiler ─▶ Jev (15 questions, 1 call) ─▶ policy ─▶ meter
Send click ─▶ hash hit? ─▶ proceed | nudge | hold 20 s | confirm | block
```

## What's in the box

| Path | What |
|---|---|
| `src/core/` | Surface-agnostic engine. `compile.ts` (state compiler + redaction), `bank.ts` (question bank), `policy.ts` (thresholds → verdict ladder, hysteresis, interrupt budget), `speculate.ts` (typing-pause evaluation + click cache), `jev.ts` (client). No browser APIs; the same code will drive the git/shell hooks later. |
| `src/ext/` | The Gmail extension. `gmail.ts` (all selectors in one place), `content.ts` (one interlock per compose window), `ui.ts` (shadow-DOM pill/hold/confirm), `background.ts` (Jev calls, history, budget, audit log), `options.ts` (settings, thresholds, policy-as-questions, log). |
| `test/` | 25 unit tests (vitest) and a 9-scenario end-to-end that loads the real extension into Chromium against a Gmail-lookalike page and a mock Jev. |
| `scripts/bench.ts` | Hits real Jev with the full bank and prints p50/p95 and cost per evaluation. |

## Design rules the code follows

1. **The compiler does everything quantitative.** Jev can't count, compare numbers or read dates as values, so `first_time_ever`, `participants_not_in_recipients`, `sends_in_last_5_min`, `deletions_ratio` are all computed before the call. Jev only gets facts and short text.
2. **Nouls are the sensor; code is the policy.** Each question has `nudge/hold/confirm/block` thresholds on P(true). The verdict is the max rung across questions, with 0.05 hysteresis so a wobble doesn't flip a verdict between ticks, and a daily **interrupt budget** that degrades unaffordable confirms to holds.
3. **Redact after computing, before sending.** Phones, card-shaped numbers and emails in free text become `<PHONE>`, `<CARD_NUMBER>`, `<EMAIL>`. `strict` mode also replaces recipient addresses with `<R1@domain>` placeholders. Policy metadata (thresholds, weights) never leaves the browser.
4. **The state hash must be stable across the seconds before a click.** Time is `Fri 17h`, draft age is a bucket, keystroke counters don't enter the state. Otherwise the cache never hits.
5. **L0 rules never wait on the network.** A credential pattern in the body blocks by itself.
6. **Policy-as-questions.** Add a noul in plain English on the options page; it runs in the same call, and since Jev scores questions independently it doesn't perturb the built-ins.
7. **Every user action is a label.** The audit log stores the noul vector + what the user did (`sent`, `overrode_confirm`, `cancelled`, …). The options page shows a precision proxy (interrupts acted on ÷ interrupts shown), cache hit rate and miss latency p50/p95.

## Run it

```bash
npm install
npm run build          # → dist/ ; load it unpacked at chrome://extensions
npm test               # unit
npm run test:e2e       # real extension in Chromium against the mock (needs a Chromium; see test/e2e.mjs)
JEV_API_KEY=… npm run bench
```

Then open the extension's options page, paste a TypeSafe key (or an OpenRouter key with the OpenRouter base URL), click **Test connection**, and open a Gmail compose window. The pill next to Send is the meter.

## Caveats, on purpose

- Gmail's DOM is obfuscated and moves. Every selector is in `src/ext/gmail.ts` with fallbacks; the fixture in `test/fixtures/gmail.html` mirrors the first form of each so the e2e stays honest, but a Gmail redesign will need a selector refresh.
- Draft text goes to a hosted API. Redaction reduces what leaves the browser; it does not make it zero.
- Passing the gate ≠ safe. It catches regret-shaped mistakes, not every mistake.
- Fail mode is a setting: `open` (send goes through, pill shows offline) or `closed` (requires a written override).
