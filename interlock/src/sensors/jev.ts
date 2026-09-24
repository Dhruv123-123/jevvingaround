import { JevClient } from "../core/jev.js";
import type { WireQuestion } from "../core/types.js";
import type { Sensor, SensorResult } from "./types.js";

const USD_PER_INPUT_TOKEN = 0.042 / 1e6;

export interface JevSensorOptions { apiKey: string; baseUrl: string; model: string; timeoutMs?: number }

/** TypeSafe Jev: direct, OpenRouter (`baseUrl: https://openrouter.ai/api`), or Cloudflare via a compatible gateway. */
export function jevSensor(opts: JevSensorOptions): Sensor {
  const client = new JevClient({ apiKey: opts.apiKey, baseUrl: opts.baseUrl, model: opts.model, timeoutMs: opts.timeoutMs });
  return {
    name: `jev:${opts.model}`,
    async evaluate(state: unknown, questions: Record<string, WireQuestion>, signal?: AbortSignal): Promise<SensorResult> {
      const r = await client.evaluate(state, questions, signal);
      return { answers: r.answers, latencyMs: r.latencyMs, inputTokens: r.inputTokens, costUsd: r.inputTokens * USD_PER_INPUT_TOKEN, model: r.model };
    },
  };
}
