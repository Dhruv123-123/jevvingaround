/** `interlock eval <pack…> [--sensor jev|none] [--json]`: run a pack's tests, print calibration, latency, cost. */
import { decide } from "../core/policy.js";
import { toWire } from "../core/jev.js";
import type { Answer, VerdictLevel } from "../core/types.js";
import type { LoadedPack } from "../pack/loader.js";
import type { Sensor } from "../sensors/types.js";

export interface CaseResult {
  name: string;
  skipped: boolean;
  pass: boolean;
  level: VerdictLevel;
  expected: VerdictLevel[];
  fired: string[];
  missingFires: string[];
  wrongFires: string[];
  nouls: Record<string, number>;
  latencyMs: number;
  costUsd: number;
}

export interface CalibrationRow { id: string; buckets: Array<{ lo: number; hi: number; n: number; positives: number }>; labelled: number }

export interface EvalReport {
  pack: string;
  sensor: string;
  cases: CaseResult[];
  passed: number;
  failed: number;
  skipped: number;
  latency: { p50: number; p95: number; max: number };
  meanCostUsd: number;
  calibration: CalibrationRow[];
}

const BUCKETS = [[0, 0.2], [0.2, 0.4], [0.4, 0.6], [0.6, 0.8], [0.8, 1.0001]] as const;

export async function evalPack(pack: LoadedPack, sensor: Sensor): Promise<EvalReport> {
  const wire = toWire(pack.questions);
  const cases: CaseResult[] = [];
  const labels = new Map<string, Array<{ p: number; y: boolean }>>();
  for (const t of pack.tests) {
    const expected = Array.isArray(t.expect.level) ? t.expect.level : [t.expect.level];
    if (t.requires_sensor && sensor.name === "none") {
      cases.push({ name: t.name, skipped: true, pass: true, level: "proceed", expected, fired: [], missingFires: [], wrongFires: [], nouls: {}, latencyMs: 0, costUsd: 0 });
      continue;
    }
    const state = t.state as { l0_flags?: string[] };
    const r = await sensor.evaluate(state, wire);
    const v = decide(pack.questions, r.answers, state, { interruptsUsed: 0, interruptBudget: 1e9, l0Flags: state.l0_flags ?? [], l0Rules: pack.l0 });
    const fired = v.reasons.map((x) => x.id);
    const missing = (t.expect.fires ?? []).filter((id) => !fired.includes(id));
    const wrong = (t.expect.not_fires ?? []).filter((id) => fired.includes(id));
    const nouls: Record<string, number> = {};
    for (const [id, a] of Object.entries(r.answers)) if ((a as Answer).type === "noul") nouls[id] = Math.round((a as { noul: number }).noul * 1000) / 1000;
    for (const id of t.expect.fires ?? []) if (id in nouls) push(labels, id, nouls[id]!, true);
    for (const id of t.expect.not_fires ?? []) if (id in nouls) push(labels, id, nouls[id]!, false);
    cases.push({ name: t.name, skipped: false, pass: expected.includes(v.level) && !missing.length && !wrong.length, level: v.level, expected, fired, missingFires: missing, wrongFires: wrong, nouls, latencyMs: r.latencyMs, costUsd: r.costUsd ?? 0 });
  }
  const ran = cases.filter((c) => !c.skipped);
  const lat = ran.map((c) => c.latencyMs).sort((a, b) => a - b);
  const q = (x: number) => (lat.length ? lat[Math.min(lat.length - 1, Math.floor(x * lat.length))]! : 0);
  const calibration: CalibrationRow[] = [...labels.entries()].map(([id, pts]) => ({
    id,
    labelled: pts.length,
    buckets: BUCKETS.map(([lo, hi]) => { const inb = pts.filter((p) => p.p >= lo && p.p < hi); return { lo, hi: Math.min(hi, 1), n: inb.length, positives: inb.filter((p) => p.y).length }; }),
  })).sort((a, b) => a.id.localeCompare(b.id));
  return {
    pack: `${pack.name}@${pack.version}`, sensor: sensor.name, cases,
    passed: ran.filter((c) => c.pass).length, failed: ran.filter((c) => !c.pass).length, skipped: cases.length - ran.length,
    latency: { p50: q(0.5), p95: q(0.95), max: lat[lat.length - 1] ?? 0 },
    meanCostUsd: ran.length ? ran.reduce((s, c) => s + c.costUsd, 0) / ran.length : 0,
    calibration,
  };
}

function push(m: Map<string, Array<{ p: number; y: boolean }>>, id: string, p: number, y: boolean): void {
  if (!m.has(id)) m.set(id, []);
  m.get(id)!.push({ p, y });
}

export function formatReport(r: EvalReport, opts: { color?: boolean } = {}): string {
  const c = (code: string, s: string) => (opts.color ? `\x1b[${code}m${s}\x1b[0m` : s);
  const lines: string[] = [];
  lines.push(`${c("1", r.pack)}  sensor=${r.sensor}  ${c("32", `${r.passed} passed`)}${r.failed ? "  " + c("31", `${r.failed} failed`) : ""}${r.skipped ? `  ${r.skipped} skipped (need a sensor)` : ""}`);
  for (const k of r.cases) {
    const mark = k.skipped ? c("2", "  -") : k.pass ? c("32", "  ✓") : c("31", "  ✗");
    const detail = k.skipped ? "" : ` → ${k.level}${k.fired.length ? ` [${k.fired.join(", ")}]` : ""}${k.missingFires.length ? c("31", `  missing: ${k.missingFires.join(", ")}`) : ""}${k.wrongFires.length ? c("31", `  wrongly fired: ${k.wrongFires.join(", ")}`) : ""}`;
    lines.push(`${mark} ${k.name}${detail}`);
    if (!k.pass && !k.skipped) lines.push(c("2", `      expected ${k.expected.join("|")}; nouls ${Object.entries(k.nouls).filter(([, v]) => v >= 0.2).map(([id, v]) => `${id}=${v}`).join(" ") || "all < 0.2"}`));
  }
  if (r.sensor !== "none") {
    lines.push(`  latency p50 ${r.latency.p50} ms  p95 ${r.latency.p95} ms  max ${r.latency.max} ms   mean cost $${r.meanCostUsd.toFixed(6)}/eval`);
    if (r.calibration.length) {
      lines.push(`  calibration (labelled cases only; bucket = predicted P, cell = true/n)`);
      lines.push(`  ${"noul".padEnd(30)} 0–.2   .2–.4  .4–.6  .6–.8  .8–1`);
      for (const row of r.calibration) lines.push(`  ${row.id.padEnd(30)} ${row.buckets.map((b) => (b.n ? `${b.positives}/${b.n}`.padEnd(6) : "·".padEnd(6))).join(" ")}`);
    }
  }
  return lines.join("\n");
}
