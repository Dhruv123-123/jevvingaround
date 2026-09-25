# Sensors

A sensor answers typed questions about a state. Interlock ships three; the interface is one method.

```ts
interface Sensor {
  name: string;
  evaluate(state: unknown, questions: WireQuestions, signal?: AbortSignal): Promise<{ answers; latencyMs; inputTokens; costUsd?; model }>;
}
```

| Sensor | Select with | Needs | What you get |
|---|---|---|---|
| `jev` | `--sensor jev` or `JEV_API_KEY` set | `JEV_API_KEY`, optionally `JEV_BASE_URL` (TypeSafe direct, `https://openrouter.ai/api`), `JEV_MODEL` | Calibrated probabilities from a non-autoregressive System One model, ~70–500 ms, input-only billing |
| `llm` | `--sensor llm` | `LLM_MODEL`, `LLM_BASE_URL` (default OpenAI), `LLM_API_KEY` — any OpenAI-compatible chat endpoint incl. Ollama | The same questions answered as strict JSON by a chat model. The numbers it writes are not calibrated probabilities; the eval's calibration table shows what they are worth, and the latency column shows the gap. |
| `none` | `--sensor none` | nothing | Every noul is 0. Only L0 rules fire. For CI without a key, and as the floor. |

`interlock eval <pack> --sensor jev` and `--sensor llm` on the same pack is the comparison the project exists to
make honestly: same states, same questions, same labels.

To add a sensor: implement the interface in `src/sensors/<name>.ts`, register it in `src/sensors/index.ts`.
