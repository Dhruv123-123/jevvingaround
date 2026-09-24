import { hashState } from "../core/hash.js";
import { toWire } from "../core/jev.js";
import { decide } from "../core/policy.js";
import type { Answer, AuditRecord, Evaluation, QuestionDef, Settings, Surface, UserAction, Verdict, VerdictLevel } from "../core/types.js";
import type { Sensor } from "../sensors/types.js";
import { appendAudit, budget, spendBudget } from "./audit.js";

/** The slice of a loaded pack the gate needs; LoadedPack and the generated PackJson both satisfy it. */
export interface GatePack { name: string; version: number; questions: QuestionDef[]; l0: Record<string, VerdictLevel> }

export interface GateInput<S> {
  surface: Surface;
  state: S;
  pack: GatePack;
  sensor: Sensor;
  l0Flags: string[];
  settings: Settings;
  previous?: Verdict;
}

export interface GateOutput<S> {
  evaluation: Evaluation<S>;
  /** true when the sensor failed and the verdict came from fail-mode + L0 only */
  degraded: boolean;
  error?: string;
  sensor: string;
  pack: string;
  costUsd: number;
}

/**
 * One call: bank → Jev → policy. Used by every Node surface (agent, shell, git, payment).
 * On a Jev failure the L0 flags still run; the verdict is then `proceed` (fail open) or `block` (fail closed).
 */
export async function runGate<S>(input: GateInput<S>): Promise<GateOutput<S>> {
  const { surface, state, pack, sensor, l0Flags, settings } = input;
  const hash = hashState(state);
  const b = budget(surface);
  const ctx = { interruptsUsed: b.used, interruptBudget: settings.interruptBudgetPerDay, previous: input.previous, l0Flags, l0Rules: pack.l0 };
  let answers: Record<string, Answer> = {};
  let latencyMs = 0, inputTokens = 0, costUsd = 0, degraded = false, error: string | undefined, sensorName = sensor.name;
  try {
    const r = await sensor.evaluate(state, toWire(pack.questions));
    answers = r.answers; latencyMs = r.latencyMs; inputTokens = r.inputTokens; costUsd = r.costUsd ?? 0; sensorName = r.model ? `${sensor.name}` : sensor.name;
  } catch (e) { degraded = true; error = (e as Error).message; }
  let verdict = decide(pack.questions, answers, state, ctx);
  if (degraded && settings.failMode === "closed" && verdict.level !== "block") {
    verdict = { ...verdict, level: "block", reasons: [{ id: "offline", p: 1, text: `Interlock can't reach Jev (${error}) and is set to fail closed`, level: "block" }, ...verdict.reasons], notes: [...verdict.notes, "fail closed"] };
  } else if (degraded) {
    verdict = { ...verdict, notes: [...verdict.notes, `degraded: ${error}`] };
  }
  if (verdict.level === "confirm" || verdict.level === "block") spendBudget(surface);
  return { evaluation: { hash, state, answers, verdict, latencyMs, inputTokens, at: Date.now() }, degraded, error, sensor: sensorName, pack: `${pack.name}@${pack.version}`, costUsd };
}

export interface RecordMeta { pack: string; sensor: string; actor: "human" | "agent"; costUsd?: number; cacheHit?: boolean; cap?: number }

/** Write one Audit Vector line. `fired` is the reason ids; `l0` the compiler flags that were in play. */
export function record<S>(surface: Surface, ev: Evaluation<S>, outcome: UserAction, meta: RecordMeta, note?: string): AuditRecord {
  const nouls: Record<string, number> = {};
  for (const [k, a] of Object.entries(ev.answers)) if (a.type === "noul") nouls[k] = Math.round(a.noul * 1000) / 1000;
  const b = budget(surface);
  const rec: AuditRecord = {
    v: 1, kind: "decision", at: new Date().toISOString(), surface, pack: meta.pack, sensor: meta.sensor, hash: ev.hash,
    level: ev.verdict.level, regret: ev.verdict.regret, nouls,
    fired: ev.verdict.reasons.filter((r) => !r.id.startsWith("l0:")).map((r) => r.id),
    l0: ev.verdict.reasons.filter((r) => r.id.startsWith("l0:")).map((r) => r.id.slice(3)),
    outcome, latency_ms: ev.latencyMs, input_tokens: ev.inputTokens, cost_usd: Math.round((meta.costUsd ?? 0) * 1e8) / 1e8, cache_hit: meta.cacheHit ?? false,
    actor: meta.actor, budget: { used: b.used, cap: meta.cap ?? 0 },
  };
  if (note) rec.note = note;
  appendAudit(rec);
  return rec;
}
