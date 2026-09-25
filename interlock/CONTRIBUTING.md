# Contributing

The most useful contribution is a **Question Pack with tests**. The second most useful is a **test case that
shows a built-in pack getting something wrong**.

## Packs

- One surface per pack. Put it in `packs/<name>.pack.yaml`; it must validate against `schema/pack.schema.json` and load with `interlock packs`.
- Write both `criteria.true` and `criteria.false`. That wording is where the accuracy lives.
- Every pack ships with tests. Rule-only cases (L0) run everywhere; model-dependent cases carry `requires_sensor: true`.
- Run `interlock eval <name> --sensor none` before opening the PR, and `--sensor jev` if you have a key. Paste the eval output in the PR; that is the review.
- A pack that adds a question to an existing built-in should `extends` it rather than copy it.

## Code

- `npm run typecheck && npm test` must pass; `npm run test:e2e` if you touched `src/ext/`.
- Compilers do all the numbers. If you find yourself asking the sensor to count or compare, move it to the compiler and state it as a fact.
- Anything sent to a sensor is redacted after features are computed. Don't add a field that leaks raw content without a redaction path.
- The CLI has no dependencies beyond `yaml` at runtime. Keep it that way.

## What gets reviewed

Packs with eval output: promptly. Compiler and sensor changes with tests: yes. New surfaces: open an issue first
with the hook point, the state you would compile, and the fail mode. Anything that adds a hosted component: no;
this project has no server.

## Reporting a miscalibration

Open an issue titled `calibration: <pack>/<question>` with the state (redacted), the probability the sensor gave,
and what you think it should have been. If you can turn it into a test case, do that instead.
