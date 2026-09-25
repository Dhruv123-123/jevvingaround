# Changelog

## 0.2.0 — 2026-09-25

- Question Pack format (`packs/*.pack.yaml`, `schema/pack.schema.json`): policy as typed questions with thresholds, L0 rules, `extends`, and required tests.
- Audit Vector v1 (`schema/audit.schema.json`): one JSON line per decision with pack, sensor, actor, outcome, cost, budget; `regret` records.
- Sensor interface with `jev`, `llm` (any OpenAI-compatible chat endpoint with JSON output) and `none` implementations.
- `interlock eval`: pass/fail per case, calibration buckets per noul, p50/p95 latency and cost per evaluation.
- `interlock recall`: regret detectors for git, shell, agent audit, Gmail mbox exports and Slack exports; joins to decisions.
- `interlock packs`, `--sensor`, `--pack`; pack lookup in `INTERLOCK_PACKS`, `~/.config/interlock/packs`, built-ins.
- GitHub Action (`action/`) and a tag-triggered publish workflow.
- Package renamed to `interlock-gate` (the `interlock` name is taken); the binary is still `interlock`.

## 0.1.0 — 2026-09-23

- Gmail and Slack web extension with speculative evaluation.
- MCP stdio proxy for agent tool calls; shell (zsh/bash) and `pre-push` gates; payment HTTP gate.
