# Interlock

A 100 ms judgment before irreversible actions. The sensor is [TypeSafe Jev](https://typesafe.ai); the policy is yours.

Every interlock that exists today is either too slow (people turn it off) or too dumb (people click through it).
Jev answers ~10–15 independent typed questions about a state in one ~100 ms call for ~$0.00005. That is cheap
and fast enough to put LLM-grade judgment *inside* the moment — under a click, inside an agent's tool loop,
before a shell command runs — without anyone noticing it's there until it has something to say.

```
state compiler (per surface, does all the numbers)
      → Jev (one call, many questions, calibrated probabilities)
      → policy (thresholds → proceed | nudge | hold | confirm | block, hysteresis, daily interrupt budget)
      → surface UI (pill / countdown / one-line confirm / block with a written override)
      → audit log (the noul vector + what the human or agent did = a label)
```

## Surfaces

| Surface | Hook point | Entry | Fail mode |
|---|---|---|---|
| **Gmail** | compose window, Send click / ⌘⏎ | browser extension (`dist/`) | open |
| **Slack** (web) | composer, Enter / Send | same extension | open |
| **AI agent tool calls** | MCP stdio proxy around any server | `interlock mcp -- <server…>` | open (`INTERLOCK_FAIL_MODE=closed`) |
| **Shell** | zsh accept-line widget / bash DEBUG trap | `eval "$(interlock shell-init zsh)"` | open |
| **git push** | `pre-push` hook | `interlock install-hooks` | open |
| **Payments / AP** | HTTP gate in the approval path | `interlock payment-server` | **closed** |

One engine (`src/core`), one runtime for Node surfaces (`src/node`), one state compiler + question bank per surface (`src/surfaces/*`).

### What each surface asks

- **Email**: wrong / missing recipient, external leak, reply-all, secret, missing attachment, commits to terms, contradicts the thread, unfinished, hostile tone, rushed sender, forward-bait; `regret_risk`; a dynamic `choice` over recipients.
- **Slack**: wrong channel, names a person negatively, screenshot bait, @channel unneeded, hostile, secret, commits to terms, contradicts the recent messages, unfinished.
- **Agent**: outside task scope, irreversible, touches unmentioned data, escalates permissions, spends money, fabricated argument, stuck in a loop, exfiltration shape; `blast_radius`.
- **Shell**: destructive on a shared resource, wrong context (kube/AWS/branch vs intent), skipped an available dry run, affects many resources, irreversible, looks like a slip; `blast_radius`. Only risky verbs reach the network; `ls` costs 0 ms.
- **git push**: destructive migration, disables tests/checks, commit message contradicts diff, unrelated changes bundled, infra/CI change unmentioned, not ready to share, off-hours to protected; `blast_radius`. L0: secrets in diff, force-push to a protected branch.
- **Payment**: unexplained anomaly, BEC pattern, invoice inconsistent, no business purpose, threshold-shaped amount; `fraud_likelihood`. L0 computes every ratio (amount vs median/max, days since bank details changed, duplicates, self-approval, lookalike payee).

## Speculation: the click costs 0 ms

On the compose surfaces the draft is scored on every typing pause (≈400 ms debounce), hashed, and cached.
When Send is pressed the verdict for *that exact draft* is usually already there. The e2e proves the click
makes zero new requests on a hit. The state is built so this works: time is `Fri 17h`, draft age is a bucket,
keystroke counters never enter the state.

## For agents

```jsonc
// claude_desktop_config.json / .mcp.json / cursor — wrap any server:
{ "mcpServers": { "fs": { "command": "interlock", "args": ["mcp", "--task", "Refactor the auth module", "--", "npx", "-y", "@modelcontextprotocol/server-filesystem", "."] } } }
```

`tools/call` goes through the gate; everything else is forwarded byte-for-byte. A `confirm` comes back to the
agent as an `isError` result that names the reasons and asks it to re-issue the call with
`"_interlock_justification": "…"`. That sentence is logged next to the noul vector. A `block` has no override
unless `--allow-override`. The tool schema already *is* the typed action set — no compiler to write.

## Run it

```bash
npm install && npm run build
npm link                       # puts `interlock` on PATH (dist/cli.js)
interlock config --key sk-…    # or JEV_API_KEY / JEV_BASE_URL env
eval "$(interlock shell-init zsh)"
interlock install-hooks        # in a repo
interlock payment-server --port 8790
interlock log --surface shell
```

Browser: load `dist/` unpacked at `chrome://extensions`, open its options page, paste the key, click **Test connection**.

```bash
npm test          # 51 unit tests: compilers, policy, speculator, client, MCP proxy, CLI, payment server
npm run test:e2e  # 11 scenarios: the real extension in Chromium against Gmail + Slack lookalikes and a mock Jev
JEV_API_KEY=… npm run bench
```

## Design rules the code follows

1. **The compiler does everything quantitative.** Jev can't count or compare numbers, so ratios, ages, set differences, and duplicates are computed first and stated as facts.
2. **Nouls are the sensor; code is the policy.** Per-question `nudge/hold/confirm/block` thresholds; max rung wins; 0.05 hysteresis; a daily interrupt budget per surface degrades unaffordable confirms to holds (never blocks).
3. **L0 never waits on the network.** Credential patterns, `rm -rf /`, force-push to `main`, changed bank details, duplicate invoices, self-approval: hard rules, instant.
4. **Redact after computing, before sending.** Emails, phones, card/account numbers become typed placeholders; policy metadata never leaves the machine.
5. **Policy-as-questions.** An org adds a plain-English noul; Jev scores questions independently so it doesn't perturb the built-ins.
6. **Every decision is a label.** The audit log stores the noul vector + the outcome (`sent`, `overrode_confirm`, `cancelled`, `blocked`, an agent's justification, an approver's note).
7. **Fail mode is chosen per surface, in writing.** Chat and shell fail open; money fails closed.

## Honest caveats

- Gmail and Slack DOMs are obfuscated and move. Every selector lives in `src/ext/gmail.ts` / `src/ext/slack.ts` with fallbacks; the fixtures mirror the first form of each. A redesign needs a selector refresh.
- Slack native apps have no pre-send hook; this covers the web client only.
- The bash integration uses the `DEBUG` trap with `extdebug`, which fires per simple command; the prefilter keeps it cheap but zsh's widget is the better experience.
- Draft text goes to a hosted API. Redaction reduces what leaves; it does not make it zero.
- The extension can be uninstalled; the MCP proxy and payment gate are the enforcement-shaped ones.
- Passing the gate ≠ safe. It catches regret-shaped mistakes.
- Not built: clinical order entry. It needs a hospital partner and a regulatory path, and the interrupt-budget idea is where it would matter most.
