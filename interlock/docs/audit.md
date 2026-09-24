# Audit Vector v1

One JSON line per decision, written before the surface acts on the verdict, whoever made the call. It carries no
content: hashes and probabilities only, so a line is safe to ship to a SIEM or paste into an issue. Schema:
[`schema/audit.schema.json`](../schema/audit.schema.json). Location: `~/.config/interlock/audit.jsonl`
(`INTERLOCK_HOME` overrides); the browser extension keeps the same records in `chrome.storage.local`.

```json
{"v":1,"kind":"decision","at":"2026-09-24T14:02:11.000Z","surface":"agent","pack":"agent@1","sensor":"jev:jev-latest",
 "hash":"3f9a…","level":"confirm","regret":0.75,
 "nouls":{"outside_task_scope":0.12,"irreversible":0.91,"spends_money":0.03},
 "fired":["irreversible"],"l0":[],
 "outcome":"overridden","note":"user asked for this email explicitly",
 "latency_ms":94,"input_tokens":812,"cost_usd":0.000034,"cache_hit":false,
 "actor":"agent","budget":{"used":1,"cap":3}}
```

- `outcome` is a closed set: `allowed`, `held`, `sent_after_hold`, `sent_now_from_hold`, `overrode_confirm`,
  `overrode_block`, `overridden`, `cancelled`, `blocked`, `asked`. `asked` is a confirmation returned to an agent;
  a later `overridden` line with the same hash resolves it.
- `actor` is `human` or `agent`. It is the field that answers "what share of gated actions came from agents".
- `note` is the only field that can carry content: what the person or agent typed to override.
- A second record kind, `regret`, is written by `interlock recall`:
  `{"v":1,"kind":"regret","at":…,"surface":"git","detector":"revert_commit","ref":"a1b2c3d4"}`.
  Joining decisions to regrets (by hash, else by surface and time) is the whole recall computation.

`interlock log` prints decisions; `interlock recall` finds regrets and reports how many of the ones that went
through a gate were at hold or above.
