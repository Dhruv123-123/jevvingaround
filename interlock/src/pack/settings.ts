import type { QuestionDef, Settings } from "../core/types.js";
import type { GatePack } from "../node/gate.js";

/** Overlay a user's settings on a pack: disable ids, override thresholds, append their own questions. */
export function applySettings(pack: GatePack, settings: Pick<Settings, "thresholdOverrides" | "extraQuestions" | "disabledQuestions">, extra: QuestionDef[] = []): GatePack {
  const disabled = new Set(settings.disabledQuestions);
  const questions = [...pack.questions, ...extra, ...settings.extraQuestions.filter((q) => q.origin !== "builtin")]
    .filter((q) => !disabled.has(q.id))
    .map((q) => (settings.thresholdOverrides[q.id] ? { ...q, thresholds: { ...q.thresholds, ...settings.thresholdOverrides[q.id] } } : q));
  return { ...pack, questions };
}
