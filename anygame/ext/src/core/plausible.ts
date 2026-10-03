// Plausibility checks: invariants a pack declares over its reads, judged every tick against the last reading the
// runtime accepted. A tick whose reads break one is read again from a fresh frame; if the reads still break it,
// nothing is done on it; if it persists, the episode ends with the broken check as its reason. Port of plausible.py.
//
//   plausible:
//     - { read: board, sticky: [X, O] }                 # a placed mark never changes or disappears (a reset to all-empty is fine)
//     - { read: board, max_changes: 2 }                 # at most N cells change between two readings
//     - { read: board, count: [X, O], diff: [0, 1] }    # count(X) - count(O) stays within [lo, hi]
//     - { when: { line: board, symbols: [X, O], length: 3 }, require: { read: status, in: [we_won, we_lost, draw] } }
import type { ReadDef } from "./pack.js";

export const ASSERTIONS = ["sticky", "max_changes", "count", "require"] as const;
type Grid = Map<string, string>;            // "c,r" → symbol

/** A grid read as {"c,r": symbol}, from either form the loop holds: {c<col>r<row>: v} or rows of characters. */
export function gridOf(v: any): Grid | null {
  if (v && typeof v === "object" && !Array.isArray(v)) {
    const out: Grid = new Map();
    for (const [k, x] of Object.entries(v)) { const m = /^c(\d+)r(\d+)$/.exec(k); if (m) out.set(`${+m[1]},${+m[2]}`, String(x)); }
    return out.size ? out : null;
  }
  if (Array.isArray(v) && v.length && v.every((r) => typeof r === "string")) {
    const out: Grid = new Map();
    v.forEach((row: string, r: number) => [...row].forEach((ch, c) => out.set(`${c + 1},${r + 1}`, ch)));
    return out;
  }
  return null;
}

function getPath(values: any, path: string): any {
  let cur = values;
  for (const part of String(path).split(".")) { if (!cur || typeof cur !== "object" || Array.isArray(cur)) return undefined; cur = cur[part]; }
  return cur;
}

/** The first symbol with `length` in a straight line, or null. */
function line(g: Grid, symbols: string[], length: number): string | null {
  for (const [k, s] of g) {
    if (!symbols.includes(s)) continue;
    const [c, r] = k.split(",").map(Number);
    for (const [dc, dr] of [[1, 0], [0, 1], [1, 1], [1, -1]]) {
      let ok = true;
      for (let i = 0; i < length && ok; i++) ok = g.get(`${c + i * dc},${r + i * dr}`) === s;
      if (ok) return s;
    }
  }
  return null;
}

const eq = (a: any, b: any) => a === b || (a !== null && b !== null && typeof a === "object" && JSON.stringify(a) === JSON.stringify(b));

export function plausibleCond(c: any, values: Record<string, any>): boolean {
  if ("line" in c) { const g = gridOf(values[c.line]); return !!g && line(g, (c.symbols ?? []).map(String), Number(c.length ?? 3)) !== null; }
  const v = getPath(values, c.read);
  if ("equals" in c) return eq(v, c.equals);
  if ("in" in c) return (c.in as any[]).some((x) => eq(v, x));
  if ("not" in c) return !eq(v, c.not);
  const n = Number(v);
  if (v === null || v === undefined || typeof v === "boolean" || Number.isNaN(n)) return false;
  if ("gte" in c) return n >= Number(c.gte);
  if ("lte" in c) return n <= Number(c.lte);
  return false;
}

function condProblem(c: any, reads: Record<string, ReadDef>): string | null {
  const shape = "a condition is {read, equals|in|not|gte|lte} or {line: <grid read>, symbols, length}";
  if (!c || typeof c !== "object" || Array.isArray(c)) return shape;
  if ("line" in c) {
    if (!(c.line in reads)) return `unknown read '${c.line}'`;
    if (!Array.isArray(c.symbols) || !c.symbols.length) return "a line condition needs symbols: [<char>, ...]";
    return null;
  }
  if (!("read" in c) || !["equals", "in", "not", "gte", "lte"].some((k) => k in c)) return shape;
  if (!(String(c.read).split(".")[0] in reads)) return `unknown read '${c.read}'`;
  return null;
}

/** null when the `plausible` list is well formed, else what is wrong with it (the loader raises it). */
export function checkPlausible(spec: any, reads: Record<string, ReadDef>): string | null {
  if (spec === null || spec === undefined) return null;
  if (!Array.isArray(spec)) return "plausible must be a list of checks";
  for (const [i, chk] of spec.entries()) {
    const where = `plausible[${i}]`;
    if (!chk || typeof chk !== "object" || Array.isArray(chk)) return `${where}: a check is a mapping`;
    const kinds = ASSERTIONS.filter((k) => k in chk);
    if (kinds.length !== 1) return `${where}: needs exactly one of ${ASSERTIONS.join(", ")}`;
    if ("when" in chk) { const bad = condProblem(chk.when, reads); if (bad) return `${where}: when: ${bad}`; }
    if (kinds[0] === "require") { const bad = condProblem(chk.require, reads); if (bad) return `${where}: require: ${bad}`; continue; }
    if (!(chk.read in reads)) return `${where}: ${kinds[0]} needs read: <a grid read id>`;
    if (kinds[0] === "sticky" && !(Array.isArray(chk.sticky) && chk.sticky.length)) return `${where}: sticky needs a list of symbols`;
    if (kinds[0] === "max_changes" && !Number.isInteger(chk.max_changes)) return `${where}: max_changes needs a whole number`;
    if (kinds[0] === "count") {
      if (!(Array.isArray(chk.count) && chk.count.length === 2)) return `${where}: count needs two symbols, [A, B]`;
      const d = chk.diff;
      if (!(Array.isArray(d) && d.length === 2 && d.every((x: any) => Number.isInteger(x)))) return `${where}: count needs diff: [lo, hi], the allowed range of count(A) - count(B)`;
    }
  }
  return null;
}

const repr = (v: any): string => (v === undefined || v === null ? "None" : typeof v === "string" ? `'${v}'` : Array.isArray(v) ? `[${v.map(repr).join(", ")}]` : String(v));

function describe(c: any): string {
  if (!c) return "";
  if ("line" in c) return `${c.line} has ${c.length ?? 3} in a line`;
  for (const k of ["equals", "in", "not", "gte", "lte"]) if (k in c) return `${c.read} ${k} ${repr(c[k])}`;
  return JSON.stringify(c);
}

/** What this reading breaks, one line per broken check, judged against `prev` (the last accepted reading). */
export function violations(spec: any[] | null | undefined, values: Record<string, any>, prev: Record<string, any> | null, reads: Record<string, ReadDef> = {}): string[] {
  const out: string[] = [];
  for (const chk of spec ?? []) {
    if ("when" in chk && !plausibleCond(chk.when, values)) continue;
    if ("require" in chk) {
      if (!plausibleCond(chk.require, values)) {
        const c = chk.require;
        const why = "read" in c ? `${c.read} is ${repr(getPath(values, c.read))}` : `no line on ${c.line}`;
        out.push(`${why} but ${describe(chk.when)} (require ${describe(c)})`);
      }
      continue;
    }
    const rid = chk.read;
    const g = gridOf(values[rid]);
    if (!g) continue;
    const empty = String(chk.empty ?? reads[rid]?.otherwise ?? ".");
    if ("count" in chk) {
      const [a, b] = chk.count.map(String);
      const [lo, hi] = chk.diff;
      let d = 0; for (const s of g.values()) d += s === a ? 1 : s === b ? -1 : 0;
      if (d < lo || d > hi) out.push(`${rid}: count(${a}) - count(${b}) is ${d}, outside [${lo}, ${hi}]` + ("when" in chk ? ` while ${describe(chk.when)}` : ""));
      continue;
    }
    const p = gridOf((prev ?? {})[rid]);
    if (!p || [...g.values()].every((s) => s === empty)) continue;     // nothing to compare with, or a restart
    if ("sticky" in chk) {
      const keep = new Set<string>(chk.sticky.map(String));
      const lost = [...p.entries()].filter(([k, s]) => keep.has(s) && g.get(k) !== s).map(([k]) => k.split(",").map(Number))
        .sort((x, y) => x[0] - y[0] || x[1] - y[1]);
      if (lost.length) {
        const cells = lost.slice(0, 4).map(([c, r]) => `c${c}r${r} ${p.get(`${c},${r}`)}→${g.get(`${c},${r}`) ?? "None"}`).join(", ");
        out.push(`${rid}: a placed ${[...keep].sort().join("/")} changed (${cells})`);
      }
    } else if ("max_changes" in chk) {
      let n = 0; for (const [k, s] of g) if (p.get(k) !== s) n++;
      if (n > Number(chk.max_changes)) out.push(`${rid}: ${n} cells changed in one tick (at most ${chk.max_changes})`);
    }
  }
  return out;
}
