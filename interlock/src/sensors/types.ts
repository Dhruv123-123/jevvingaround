import type { Answer, WireQuestion } from "../core/types.js";

/** The one seam that keeps Interlock model-neutral. A sensor answers typed questions about a state. */
export interface Sensor {
  name: string;
  evaluate(state: unknown, questions: Record<string, WireQuestion>, signal?: AbortSignal): Promise<SensorResult>;
}

export interface SensorResult {
  answers: Record<string, Answer>;
  latencyMs: number;
  inputTokens: number;
  /** USD, when the sensor knows; Jev bills input only at $0.042/M */
  costUsd?: number;
  model: string;
}
