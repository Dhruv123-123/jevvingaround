# Question Packs

A pack is policy as data: one surface, typed plain-English questions with thresholds, a few hard rules, and the
test cases that prove the pack does what it says. The runtime never special-cases a pack. Schema:
[`schema/pack.schema.json`](../schema/pack.schema.json).

```yaml
pack: git-push          # slug
version: 1
surface: git            # which compiler produces the state this pack reads
extends: []             # other packs (by name in the same directory, or a path) whose questions are merged in

l0:                     # hard rules on compiler flags: no network, no model, never a nudge
  - { flag: secret_in_diff, level: confirm }

questions:
  - id: destructive_migration
    type: noul          # noul → P(true) in [0,1]; choice → one of ≤255 options; score → 2–10 ordered levels
    instructions: >
      The push contains a schema migration that drops or truncates data.
    criteria:           # write both sides; this is where the accuracy lives
      true: Migration files with DROP/TRUNCATE/remove_column on tables that plausibly hold data.
      false: No migrations, or only additive ones.
    thresholds: { nudge: 0.5, confirm: 0.75, block: 0.95 }   # nouls only
    reason: "A migration here destroys data ({p}%)"           # {p} = percent, {choice} for choices
    weight: 1.5         # ranks reasons when several fire

thresholds:             # overrides for questions inherited via extends
  destructive_migration: { confirm: 0.6 }

tests:                  # required; `interlock eval` runs them
  - name: dropping a column on main
    state: fixtures/drop-column-main.json     # or an inline object
    expect: { level: [confirm, block], fires: [destructive_migration] }
    requires_sensor: true                     # skipped under `--sensor none`
```

## Semantics the loader enforces

- Ids are unique across the pack and everything it extends; `extends` never changes a parent's thresholds except through the child's `thresholds:` block.
- A pack cannot run code. Enrichment that needs sibling answers uses one convention: a `choice` named `<noul_id>__which` names the picked option in that noul's reason (email uses it to say *which* recipient looks wrong).
- `l0` levels are `confirm` or `block`. A nudge never comes from a rule.
- A pack with no tests (and no parents) is refused.
- `expect.level` may list several acceptable rungs. `fires` / `not_fires` label individual nouls; those labels feed the calibration table.

## Running

```bash
interlock packs                       # what the runtime can see: INTERLOCK_PACKS, ~/.config/interlock/packs, built-ins
interlock eval git-push --sensor jev  # pass/fail per case, calibration per noul, p50/p95 latency, cost per eval
interlock eval agent --sensor none    # L0 cases only; model-dependent cases are reported as skipped
```

Put your own packs in `~/.config/interlock/packs/` or point `INTERLOCK_PACKS` at a directory in your repo so the
policy is versioned with the code and its tests run in CI.
