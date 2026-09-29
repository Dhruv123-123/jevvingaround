// A pack: the typed contract between one game and Jev. Same YAML as the Python runtime.
import yaml from "js-yaml";
import { Zone, type Rect } from "./geometry.js";

export type ReadDef = Record<string, any> & { kind: string };
export interface ActionDef { id: string; kind: string; params: Record<string, any> }
export interface Question { id: string; type: "noul" | "choice" | "score"; instructions: string; criteria: Record<string, string | null> }
export interface Test { frame: string; expect: Record<string, any>; expect_action?: any; expect_cell?: string; requires_sensor?: boolean }

export interface Pack {
  name: string;
  size: [number, number];
  zones: Record<string, Zone>;
  reads: Record<string, ReadDef>;
  actions: ActionDef[];
  tickHz: number;
  play: string;
  questions: Question[];
  rules: Record<string, any>[];
  tests: Test[];
  raw: Record<string, any>;
  modes: Record<string, Pack>;                 // sub-packs for other screens, each with a `when`
  fingerprints: Record<string, string>;        // screen name → base64 fingerprint (main and every mode)
}

export interface ModeWhen { read?: string; equals?: any; in?: any[]; not?: any; fingerprint?: string }

/** A mode is the base pack with these keys overridden or merged. */
export const MODE_KEYS = ["zones", "read", "act", "play", "questions", "rules", "act_when", "stop_when", "settle", "tick_hz"];

export function mergeMode(base: Record<string, any>, mode: Record<string, any>): Record<string, any> {
  const out: Record<string, any> = { ...base };
  delete out.modes; delete out.tests; delete out.fingerprints;
  for (const k of MODE_KEYS) {
    if (!(k in mode)) continue;
    if ((k === "zones" || k === "read") && mode[k] && typeof mode[k] === "object") out[k] = { ...(base[k] ?? {}), ...mode[k] };
    else out[k] = mode[k];
  }
  if (mode.act_when === null) delete out.act_when;
  if (mode.stop_when === null) delete out.stop_when;
  return out;
}

export function dumpPack(raw: Record<string, any>): string {
  return yaml.dump(raw, { lineWidth: 120, noRefs: true, sortKeys: false });
}

export class PackError extends Error {}

export const READ_KINDS = new Set(["bar", "templates", "ocr", "vocab", "blobs", "color", "locate", "runs", "around", "tetris"]);
export const QUESTION_TYPES = new Set(["noul", "choice", "score"]);

function parseRect(v: any): Rect {
  if (!Array.isArray(v) || v.length !== 4) throw new PackError(`rect must be [x0, y0, x1, y1], got ${JSON.stringify(v)}`);
  const [x0, y0, x1, y1] = v.map(Number);
  return { x0, y0, x1, y1 };
}

export function loadPack(text: string, name = "pack"): Pack {
  let raw: any;
  try {
    raw = yaml.load(text);
  } catch (e) {
    throw new PackError(`${name}: cannot read: ${(e as Error).message}`);
  }
  if (!raw || typeof raw !== "object" || !raw.game) throw new PackError(`${name}: 'game' is required`);
  const screen = raw.screen ?? {};
  const size: [number, number] = [Number((screen.size ?? [540, 960])[0]), Number((screen.size ?? [540, 960])[1])];
  const px = (d: any, what: string) => {
    if (d && d.rect_px && !d.rect) {
      const [x0, y0, x1, y1] = (d.rect_px as any[]).map(Number);
      if ([x0, y0, x1, y1].some((v) => Number.isNaN(v))) throw new PackError(`${name}: ${what}: rect_px must be [x0, y0, x1, y1] pixels`);
      d.rect = [x0 / size[0], y0 / size[1], x1 / size[0], y1 / size[1]];
    }
  };
  const zones: Record<string, Zone> = {};
  for (const [zn, z] of Object.entries<any>(raw.zones ?? {})) {
    px(z, `zone '${zn}'`);
    if (!z.rect) throw new PackError(`${name}: zone '${zn}': needs rect or rect_px`);
    zones[zn] = new Zone(zn, parseRect(z.rect), z.grid ? [Number(z.grid[0]), Number(z.grid[1])] : null);
  }
  const reads: Record<string, ReadDef> = raw.read ?? {};
  for (const [rid, r] of Object.entries<any>(reads)) {
    if (!READ_KINDS.has(r.kind)) throw new PackError(`${name}: read '${rid}': kind must be one of ${[...READ_KINDS].sort().join(", ")}`);
    px(r, `read '${rid}'`);
    if (r.zone && !zones[r.zone]) throw new PackError(`${name}: read '${rid}': unknown zone '${r.zone}'`);
    if (r.kind === "locate" || r.kind === "runs") {
      if (!(r.in in reads) || r.symbol === undefined) throw new PackError(`${name}: read '${rid}': ${r.kind} needs 'in' (a grid read id) and 'symbol'`);
    } else if (r.kind === "around") {
      if (!(r.of in reads) || !(r.in in reads)) throw new PackError(`${name}: read '${rid}': around needs 'of' and 'in'`);
    } else if (r.kind === "tetris") {
      if (!(r.in in reads)) throw new PackError(`${name}: read '${rid}': tetris needs 'in'`);
    } else if (!r.zone && !r.rect) {
      throw new PackError(`${name}: read '${rid}': needs zone or rect`);
    }
  }
  const actions: ActionDef[] = [];
  for (const a of raw.act ?? []) {
    if (!a.id) throw new PackError(`${name}: every action needs an id`);
    const kind = a.kind ?? (a.id === "wait" ? "wait" : "tap");
    if (kind === "macro" && !a.options) throw new PackError(`${name}: action '${a.id}': macro needs 'options: <read id>'`);
    const params: Record<string, any> = {};
    for (const [k, v] of Object.entries(a)) if (k !== "id" && k !== "kind") params[k] = v;
    actions.push({ id: a.id, kind, params });
  }
  if (!actions.length) throw new PackError(`${name}: 'act' must list at least one action`);
  const questions: Question[] = raw.questions ?? [];
  for (const q of questions) {
    if (!QUESTION_TYPES.has(q.type) || !q.id || !q.instructions) throw new PackError(`${name}: question ${q?.id}: needs id, type (noul|choice|score), instructions`);
    q.criteria = q.criteria ?? {};
  }
  if (raw.settle !== undefined && raw.settle !== null && raw.settle !== "screen_change") throw new PackError(`${name}: settle must be 'screen_change'`);
  const rules: Record<string, any>[] = raw.rules ?? [];
  for (const rl of rules) {
    const c = rl.if ?? {};
    const okNoul = "noul" in c && ("gte" in c || "lte" in c);
    const okRead = "read" in c && ["equals", "in", "not", "gte", "lte"].some((k) => k in c);
    if (!okNoul && !okRead) throw new PackError(`${name}: rule needs if: {noul, gte|lte} or if: {read, equals|in|not|gte|lte}`);
    if (!["exclude", "set", "avoid", "only"].some((k) => k in rl)) throw new PackError(`${name}: rule needs exclude, set, avoid or only`);
  }
  const tests: Test[] = raw.tests ?? [];
  const modes: Record<string, Pack> = {};
  for (const [mn, m] of Object.entries<any>(raw.modes ?? {})) {
    if (!m || typeof m !== "object" || !m.when) throw new PackError(`${name}: mode '${mn}' needs 'when' ({read, equals|in|not} or {fingerprint})`);
    const merged = mergeMode(raw, m);
    merged.game = `${raw.game}/${mn}`;
    modes[mn] = loadPack(yaml.dump(merged), `${name}/${mn}`);
    modes[mn].raw.when = m.when;
    modes[mn].raw.own_reads = Object.keys(m.read ?? {});     // a mode's support is judged on the reads it defines itself
  }
  const fingerprints: Record<string, string> = { ...(raw.fingerprints ?? {}) };
  for (const [mn, m] of Object.entries<any>(raw.modes ?? {})) if (m.when?.fingerprint) fingerprints[mn] = m.when.fingerprint;
  return {
    name: String(raw.game), size, zones, reads, actions, tickHz: Number(raw.tick_hz ?? 3), play: String(raw.play ?? "").trim(),
    questions, rules, tests, raw, modes, fingerprints,
  };
}
