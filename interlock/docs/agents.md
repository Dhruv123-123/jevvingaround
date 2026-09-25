# Gating agent tool calls

`interlock mcp` is a stdio proxy: put it in front of any MCP server and every `tools/call` goes through the
`agent` pack before it reaches the server. Everything else is forwarded byte for byte.

## Claude Code (`.mcp.json`) / Claude Desktop / Cursor

```jsonc
{
  "mcpServers": {
    "fs": {
      "command": "npx",
      "args": ["-y", "interlock-gate", "mcp", "--task", "Refactor the auth module", "--",
               "npx", "-y", "@modelcontextprotocol/server-filesystem", "."],
      "env": { "JEV_API_KEY": "…" }
    }
  }
}
```

`--task` is the one thing the proxy cannot see on its own; it is what `outside_task_scope` and
`touches_unmentioned_data` are judged against. Set it per session, or export `INTERLOCK_TASK`.

## What the agent sees

| Verdict | What happens |
|---|---|
| proceed, nudge | forwarded (nudge is logged) |
| hold | forwarded and logged as `held` — a countdown means nothing to an agent |
| confirm | an `isError` result naming the reasons and asking the agent to re-issue the same call with `"_interlock_justification": "<one sentence>"`. The sentence is logged next to the noul vector, then the call is forwarded. |
| block | an `isError` result; no override unless `--allow-override` (or `INTERLOCK_ALLOW_OVERRIDE=1`) |

A well-behaved agent reads the reasons and either justifies or picks a different step. A badly-behaved one
re-issues with a boilerplate justification — which is exactly what the audit log will show, with `actor: agent`.

## Flags

- `--pack <name>` — a different pack (yours, via `INTERLOCK_PACKS`) instead of the built-in `agent`.
- `--sensor jev|llm|none` — `none` means only the L0 rules (`rm -rf /` in a shell tool, secrets in args) fire.
- `INTERLOCK_FAIL_MODE=closed` — if the sensor is unreachable, calls are refused instead of forwarded.
