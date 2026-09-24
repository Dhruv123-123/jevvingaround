import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { parse } from "yaml";
import type { Answer, QuestionDef, VerdictLevel } from "../core/types.js";
import type { PackFile, PackQuestion, PackTest } from "./types.js";

export interface LoadedPack {
  name: string;
  version: number;
  surface: string;
  description?: string;
  path: string;
  /** every question, parents first, with thresholds overrides applied */
  questions: QuestionDef[];
  /** compiler flag → forced level; only confirm|block are allowed by the format */
  l0: Record<string, VerdictLevel>;
  tests: Array<PackTest & { statePath?: string }>;
}

const ID_RE = /^[a-z][a-z0-9_]{0,60}$/;
const LEVELS = ["nudge", "hold", "confirm", "block"] as const;

export class PackError extends Error {
  constructor(message: string, public path: string) { super(`${path}: ${message}`); }
}

/** Resolve `extends` by name against the same directory (`<name>.pack.yaml`) or by relative path. */
function resolveExtend(from: string, ref: string): string {
  const dir = dirname(from);
  const cands = [resolve(dir, ref), resolve(dir, `${ref}.pack.yaml`), resolve(dir, `${ref}.yaml`)];
  const hit = cands.find((c) => existsSync(c));
  if (!hit) throw new PackError(`extends "${ref}" not found (tried ${cands.join(", ")})`, from);
  return hit;
}

function validateQuestion(q: PackQuestion, path: string): void {
  if (!ID_RE.test(q.id)) throw new PackError(`question id "${q.id}" must match ${ID_RE}`, path);
  if (!["noul", "choice", "score"].includes(q.type)) throw new PackError(`question "${q.id}": type must be noul|choice|score`, path);
  if (!q.instructions?.trim()) throw new PackError(`question "${q.id}": instructions required`, path);
  if (q.type === "noul") {
    if (Array.isArray(q.criteria) || typeof q.criteria !== "object") throw new PackError(`noul "${q.id}": criteria must be {true, false}`, path);
  } else if (q.type === "choice") {
    if (Array.isArray(q.criteria) || typeof q.criteria !== "object") throw new PackError(`choice "${q.id}": criteria must be a map of option → description|null`, path);
    const n = Object.keys(q.criteria).length;
    if (n < 2 || n > 255) throw new PackError(`choice "${q.id}": 2–255 options (got ${n})`, path);
    if (q.thresholds) throw new PackError(`choice "${q.id}": thresholds apply to nouls only`, path);
  } else {
    if (!Array.isArray(q.criteria) || q.criteria.length < 2 || q.criteria.length > 10) throw new PackError(`score "${q.id}": criteria must list 2–10 levels`, path);
    if (q.thresholds) throw new PackError(`score "${q.id}": thresholds apply to nouls only`, path);
  }
  for (const [k, v] of Object.entries(q.thresholds ?? {})) {
    if (!(LEVELS as readonly string[]).includes(k)) throw new PackError(`question "${q.id}": unknown threshold "${k}"`, path);
    if (typeof v !== "number" || v < 0 || v > 1) throw new PackError(`question "${q.id}": threshold ${k} must be 0–1`, path);
  }
}

/** `<noul>__which` choice questions enrich their noul's reason with the picked option. */
export function withWhichConvention(qs: QuestionDef[]): QuestionDef[] {
  const ids = new Set(qs.map((q) => q.id));
  return qs.map((q) => {
    if (q.type !== "noul" || !ids.has(`${q.id}__which`)) return q;
    const whichId = `${q.id}__which`;
    const base = q.reason ?? `${q.id.replace(/_/g, " ")} ({p}%)`;
    return {
      ...q,
      reasonFor: (a: Answer, answers: Record<string, Answer>) => {
        const pick = answers[whichId];
        if (a.type !== "noul" || pick?.type !== "choice" || pick.choice === "none" || pick.confidence < 0.5) return undefined;
        return base.replace("{p}", String(Math.round(a.noul * 100))).replace(/^One recipient|^One item|^Something/, pick.choice).replace("{which}", pick.choice);
      },
    };
  });
}

export function loadPack(path: string, seen: string[] = []): LoadedPack {
  const abs = resolve(path);
  if (seen.includes(abs)) throw new PackError(`extends cycle: ${[...seen, abs].join(" → ")}`, abs);
  let file: PackFile;
  try { file = parse(readFileSync(abs, "utf8")) as PackFile; } catch (e) { throw new PackError(`cannot read: ${(e as Error).message}`, abs); }
  if (!file || typeof file !== "object") throw new PackError("empty pack", abs);
  if (!ID_RE.test(String(file.pack ?? "").replace(/-/g, "_"))) throw new PackError(`"pack" name must be a slug`, abs);
  if (typeof file.version !== "number") throw new PackError(`"version" must be a number`, abs);
  if (!file.surface) throw new PackError(`"surface" required`, abs);
  if (!Array.isArray(file.questions)) throw new PackError(`"questions" must be a list`, abs);

  const parents = (file.extends ?? []).map((ref) => loadPack(resolveExtend(abs, ref), [...seen, abs]));
  const questions: QuestionDef[] = [];
  const l0: Record<string, VerdictLevel> = {};
  for (const p of parents) {
    for (const q of p.questions) {
      if (questions.some((x) => x.id === q.id)) throw new PackError(`question "${q.id}" defined by more than one parent`, abs);
      questions.push({ ...q, origin: "org" });
    }
    Object.assign(l0, p.l0);
  }
  for (const q of file.questions) {
    validateQuestion(q, abs);
    if (questions.some((x) => x.id === q.id)) throw new PackError(`question "${q.id}" already defined (by a parent or twice)`, abs);
    questions.push({ id: q.id, type: q.type, instructions: q.instructions.trim(), criteria: q.criteria, thresholds: q.thresholds, reason: q.reason, weight: q.weight ?? 1, origin: "builtin" });
  }
  for (const [id, t] of Object.entries(file.thresholds ?? {})) {
    const q = questions.find((x) => x.id === id);
    if (!q) throw new PackError(`thresholds override for unknown question "${id}"`, abs);
    if (q.type !== "noul") throw new PackError(`thresholds override on non-noul "${id}"`, abs);
    q.thresholds = { ...q.thresholds, ...t };
  }
  for (const rule of file.l0 ?? []) {
    if (!rule.flag || !["confirm", "block"].includes(rule.level)) throw new PackError(`l0 rules need {flag, level: confirm|block}`, abs);
    l0[rule.flag] = rule.level;
  }
  const tests = (file.tests ?? []).map((t) => {
    if (!t.name || !t.expect?.level) throw new PackError(`test "${t.name ?? "?"}" needs name and expect.level`, abs);
    if (typeof t.state === "string") {
      const sp = resolve(dirname(abs), t.state);
      if (!existsSync(sp)) throw new PackError(`test "${t.name}": state file ${t.state} not found`, abs);
      return { ...t, state: JSON.parse(readFileSync(sp, "utf8")), statePath: sp };
    }
    return t;
  });
  if (!parents.length && !tests.length) throw new PackError(`a pack without tests is refused; add at least one under "tests"`, abs);
  return { name: file.pack, version: file.version, surface: file.surface, description: file.description, path: abs, questions: withWhichConvention(questions), l0, tests };
}

/** Built-in packs ship next to the CLI; `INTERLOCK_PACKS` or ~/.config/interlock/packs override by name. */
export function findPack(name: string, dirs: string[]): string {
  for (const d of dirs) {
    for (const cand of [join(d, `${name}.pack.yaml`), join(d, `${name}.yaml`), join(d, name)]) if (existsSync(cand)) return cand;
  }
  throw new Error(`pack "${name}" not found in ${dirs.join(", ")}`);
}
