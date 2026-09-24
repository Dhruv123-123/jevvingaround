import type { Answer, WireQuestion } from "../core/types.js";
import type { Sensor, SensorResult } from "./types.js";

/**
 * No model at all: every noul is 0, every choice is its first option, every score is 0.
 * Only L0 rules can fire. For CI without a key, for people without access, and as the floor in evals.
 */
export const noneSensor: Sensor = {
  name: "none",
  async evaluate(_state: unknown, questions: Record<string, WireQuestion>): Promise<SensorResult> {
    const answers: Record<string, Answer> = {};
    for (const [id, q] of Object.entries(questions)) {
      if (q.type === "noul") answers[id] = { type: "noul", noul: 0 };
      else if (q.type === "choice") {
        const opts = Object.keys(q.criteria as Record<string, unknown>);
        answers[id] = { type: "choice", choice: opts[0] ?? "", probabilities: Object.fromEntries(opts.map((o, i) => [o, i === 0 ? 1 : 0])), confidence: 0 };
      } else {
        const levels = q.criteria as string[];
        answers[id] = { type: "score", score: 0, legend: Object.fromEntries(levels.map((l, i) => [String(i), l])), probabilities: {}, confidence: 0 };
      }
    }
    return { answers, latencyMs: 0, inputTokens: 0, costUsd: 0, model: "none" };
  },
};
