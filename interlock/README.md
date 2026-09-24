# Interlock

**Policy as questions. Decisions as vectors. A 100 ms judgment before irreversible actions.**

Interlock is a reference implementation of *pre-action judgment*: before a person or an agent does something they
can't undo (run, push, send, pay), a small typed model answers a bank of plain-English questions about the
situation in one ~100 ms call, and a policy you can read turns the answers into one of five rungs.

The two things worth copying are the formats:

- **[Question Packs](docs/packs.md)** — policy as typed questions with thresholds, hard rules, and *tests*. A YAML file in your repo, validated by a [schema](schema/pack.schema.json), run in CI.
- **[Audit Vectors](docs/audit.md)** — every decision as a named probability vector plus what happened next. No content, only hashes. The only record from which precision and recall can be computed.

The runtime proves them across six surfaces. The sensor is pluggable: [TypeSafe Jev](https://typesafe.ai) today, `none` (rules only) for CI, anything else behind one interface.

```
surface adapter → state compiler → pack → sensor → policy → verdict → audit line
   (hook)        (does all the numbers)  (YAML)  (Jev|none)  (ladder)   (JSONL)
```

## Try it

```bash
npm install && npm run build && npm link
interlock packs                                   # the six built-in packs
interlock eval agent --sensor none                # rules-only cases pass without a key
export JEV_API_KEY=…                              # or: interlock config --key …
interlock eval agent shell git-push --sensor jev  # pass/fail, calibration per question, p50/p95 latency, $/eval
```

Then put a gate somewhere real:

```bash
eval "$(interlock shell-init zsh)"     # risky shell commands (rm -rf, kubectl delete, terraform apply, curl|sh …)
interlock install-hooks                # git push, via pre-push
interlock mcp --task "Refactor auth" -- npx -y @modelcontextprotocol/server-filesystem .   # any MCP server
interlock log                          # what was judged, what happened, who did it (human or agent)
interlock recall                       # regret events in your git/shell history, joined to decisions
```

For agents, drop the `mcp` line into `claude_desktop_config.json` / `.mcp.json` as the server's `command`. A
`confirm` comes back to the agent as an `isError` result naming the reasons and asking it to re-issue the call
with `"_interlock_justification": "…"`; that sentence lands in the audit log next to the noul vector.

## Surfaces

| Surface | Hook | Pack | Fail mode |
|---|---|---|---|
| AI agent tool calls | MCP stdio proxy around any server | `agent` | open (`INTERLOCK_FAIL_MODE=closed`) |
| Shell | zsh `accept-line` widget / bash `DEBUG` trap; only risky verbs reach a sensor | `shell` | open |
| git push | `pre-push` | `git-push` | open |
| Payments / AP | HTTP gate (`interlock payment-server`) | `payment` | **closed** |
| Gmail, Slack web | browser extension in `src/ext/` — a demo of the runtime, best-effort | `email`, `slack` | open |

## What the numbers mean

`interlock eval` prints, per pack: each case's rung and which questions fired; a calibration table per noul
(cases bucketed by predicted P against the share labelled true — the honest way to see whether 0.7 means 70%);
p50/p95 latency and mean cost per evaluation for the sensor used. Model-dependent cases are skipped under
`--sensor none` and reported as such. Publish the misses; that is what makes the good numbers believable.

`interlock recall` looks for regret in local history (a revert or force-push within an hour of a push, the same
risky command re-run with one token changed, an agent asked three times for the same call), writes them as
`regret` records, and reports how many of the regrets that passed through a gate were at hold or above.

## Design rules the code follows

1. **The compiler does everything quantitative.** Jev can't count or compare numbers; ratios, ages, set differences, duplicates are computed first and stated as facts.
2. **Nouls are the sensor; the pack is the policy.** Per-question `nudge/hold/confirm/block` thresholds; max rung wins; 0.05 hysteresis; a daily interrupt budget per surface degrades unaffordable confirms to holds, never blocks.
3. **L0 never waits on the network.** Credential patterns, `rm -rf /`, force-push to `main`, changed bank details: rules, instant.
4. **Redact after computing, before sending.** Emails, phones, card/account numbers become placeholders; policy metadata never leaves the machine.
5. **Every decision is a label.** The audit vector plus the outcome is a training example nobody else is collecting at this granularity.
6. **Fail mode is chosen per surface, in writing.** Chat and shell fail open; money fails closed.

## Layout

```
packs/            the six built-in Question Packs (YAML, with tests)
schema/           JSON Schema for packs and audit vectors
src/core/         engine: policy ladder, speculation cache, hashing, email compiler
src/pack/         pack loader (extends, validation, the __which convention), settings overlay
src/sensors/      Sensor interface; jev and none implementations
src/node/         config, JSONL audit, per-surface budget, runGate
src/surfaces/     agent (compiler + MCP proxy), shell, git, slack, payment compilers
src/cli/          interlock: config, packs, eval, recall, mcp, shell, git-push, install-hooks, payment-server, log
src/ext/          the Gmail/Slack extension (imports the generated packs)
test/             61 unit tests + 11 Chromium e2e scenarios; mock sensor in scripts/mock-jev.mjs
```

## Caveats, on purpose

- Calibration is published as measured. Some nuanced questions (`contradicts_thread`, `wrong_context_for_intent`) may not be well calibrated; the eval exists to find out.
- Gmail/Slack DOMs are obfuscated and move; the extension is a demo of the runtime, not a deliverable.
- Email and Slack recall detectors need an export and are not implemented yet.
- Draft text goes to a hosted sensor. Redaction reduces what leaves; it does not make it zero.
- Passing the gate ≠ safe. It catches regret-shaped mistakes.
- Not built: clinical order entry. It needs a partner and a regulatory path.

MIT.
