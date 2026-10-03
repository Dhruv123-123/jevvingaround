// A pack: the typed contract between one game and Jev. Same YAML as the Python runtime.
import yaml from "js-yaml";
import { Zone, type Rect } from "./geometry.js";

export type ReadDef = Record<string, any> & { kind: string };
export interface ActionDef { id: string; kind: string; params: Record<string, any> }
export interface Question { id: string; type: "noul" | "choice" | "score"; instructions: string; criteria: Record<string, string | null> }
export interface Test { frame?: string; state?: string; expect: Record<string, any>; expect_action?: any; expect_cell?: string; requires_sensor?: boolean }

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
  tasks: TaskDef[];                            // goals with a verifier over the reads
}
export interface TaskDef { id: string; instruction: string; done: Record<string, any>[]; when?: Record<string, any>; hold_ticks: number; limit_ticks: number; category: string; [k: string]: any }
export const TASK_CATEGORIES = ["navigate", "collect", "score", "survive", "clear", "build", "avoid", "other"];

const condOk = (c: any) => c && typeof c === "object" && "read" in c && ["equals", "in", "not", "gte", "lte", "contains"].some((k) => k in c);

// Bounds on a task's tick budget. Any pack: limit_ticks and hold_ticks are whole numbers of at least 1, and the
// condition must hold for no longer than the attempt lasts. Proposed by the setter (a model guessing at the game):
// limit_ticks is clamped to [SETTER_LIMIT_MIN, SETTER_LIMIT_MAX]. Same bounds as pack.py.
export const TASK_LIMIT_MAX = 20000;
export const SETTER_LIMIT_MIN = 20, SETTER_LIMIT_MAX = 2000;

const whole = (v: any): number | null => (typeof v === "number" && Number.isInteger(v) ? v : null);
const isNum = (v: any) => typeof v === "number" && Number.isFinite(v);

/** The values a read can take when they are a closed set (a colour read on one rect, or a zone without a grid, with
 *  named options), else null: open values, or a zone not known here. */
function labelsOf(r: ReadDef | undefined, zones?: Record<string, Zone>): Set<any> | null {
  if (!r || r.kind !== "color" || !r.options || typeof r.options !== "object" || Array.isArray(r.options) || r.parse || r.as) return null;
  if ("zone" in r && (!zones || !zones[r.zone] || zones[r.zone].grid)) return null;
  return new Set([...Object.keys(r.options), r.otherwise ?? "unknown"]);
}

/** Why these conditions (all must hold) can never hold together, or "". Same checks as pack.py's _impossible. */
export function impossibleConds(conds: Record<string, any>[], reads: Record<string, ReadDef>, zones?: Record<string, Zone>): string {
  const lo: Record<string, number> = {}, hi: Record<string, number> = {};
  for (const c of conds) {
    const rid = String(c.read);
    const labels = labelsOf(reads[rid], zones);
    const names = () => JSON.stringify([...(labels ?? [])].map(String).sort());
    for (const op of ["gte", "lte"] as const) {
      if (!(op in c)) continue;
      if (!isNum(c[op])) return `${rid} ${op} ${JSON.stringify(c[op])}: a threshold must be a number`;
      if (labels) return `${rid} gives one of ${names()}, never a number to compare with ${op}`;
      if (op === "gte") lo[rid] = Math.max(lo[rid] ?? -Infinity, c[op]); else hi[rid] = Math.min(hi[rid] ?? Infinity, c[op]);
    }
    if ("in" in c && (!Array.isArray(c.in) || !c.in.length)) return `${rid} in ${JSON.stringify(c.in)}: \`in\` takes a non-empty list`;
    if (labels) {
      const want = "equals" in c ? [c.equals] : "in" in c ? c.in : [];
      const bad = want.filter((v: any) => !labels.has(v));
      if (bad.length && bad.length === want.length) return `${rid} never reads ${JSON.stringify(bad[0])}: it gives one of ${names()}`;
    }
  }
  for (const rid of Object.keys(lo)) if (rid in hi && lo[rid] > hi[rid]) return `${rid} cannot be at least ${lo[rid]} and at most ${hi[rid]}`;
  return "";
}

/** Tasks are goals the runtime can verify from the reads: `done` (one condition or a list that must all hold) marks
 *  completion once it has held `hold_ticks` ticks; `when` says when the task is available; `limit_ticks` bounds the attempt.
 *  A task that can never complete is refused; `clamp` [lo, hi] pulls limit_ticks into that range first (the setter's). */
export function checkTasks(tasks: any, reads: Record<string, ReadDef>, where = "pack", clamp?: [number, number], zones?: Record<string, Zone>): TaskDef[] {
  const out: TaskDef[] = []; const seen = new Set<string>();
  for (const t of (tasks ?? []) as any[]) {
    if (!t || typeof t !== "object" || !t.id || !t.instruction || t.done === undefined) throw new PackError(`${where}: every task needs id, instruction and done: {read, equals|in|not|gte|lte} (or a list of them)`);
    const id = String(t.id);
    if (seen.has(id)) throw new PackError(`${where}: task '${id}' is listed twice`);
    seen.add(id);
    const conds = Array.isArray(t.done) ? t.done : [t.done];
    if (!conds.length) throw new PackError(`${where}: task '${id}': done is an empty list`);
    for (const c of [...conds, ...(t.when ? [t.when] : [])]) {
      if (!condOk(c)) throw new PackError(`${where}: task '${id}': a condition is {read: <id or id.path>, equals|in|not|gte|lte: v}`);
      if (!(String(c.read).split(".")[0] in reads)) throw new PackError(`${where}: task '${id}': unknown read '${c.read}'`);
    }
    const why = impossibleConds(conds, reads, zones) || (t.when ? impossibleConds([t.when], reads, zones) : "");
    if (why) throw new PackError(`${where}: task '${id}' can never be done: ${why}`);
    let limit = whole(t.limit_ticks ?? 150); const hold = whole(t.hold_ticks ?? 1);
    if (limit === null || hold === null) throw new PackError(`${where}: task '${id}': limit_ticks and hold_ticks are whole numbers of ticks`);
    if (clamp && limit >= 1) limit = Math.max(clamp[0], Math.min(clamp[1], limit));
    if (limit < 1 || limit > TASK_LIMIT_MAX) throw new PackError(`${where}: task '${id}': limit_ticks ${limit} is outside 1..${TASK_LIMIT_MAX}`);
    if (hold < 1 || hold > limit) throw new PackError(`${where}: task '${id}': hold_ticks ${hold} must be between 1 and limit_ticks (${limit}), or the task can never be done`);
    const cat = String(t.category ?? "other");
    out.push({ ...t, id, done: conds, hold_ticks: hold, limit_ticks: limit, category: TASK_CATEGORIES.includes(cat) ? cat : "other" });
  }
  return out;
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

export const READ_KINDS = new Set(["bar", "templates", "ocr", "vocab", "blobs", "color", "locate", "runs", "around", "tetris", "json", "json_grid", "predict", "margin", "go", "slide", "head", "gap", "count"]);
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
    if (r.kind === "locate" || r.kind === "runs" || r.kind === "count") {
      if (!(r.in in reads) || r.symbol === undefined) throw new PackError(`${name}: read '${rid}': ${r.kind} needs 'in' (a grid read id) and 'symbol'`);
    } else if (r.kind === "around") {
      if (!(r.of in reads) || !(r.in in reads)) throw new PackError(`${name}: read '${rid}': around needs 'of' and 'in'`);
    } else if (r.kind === "go") {
      if (!(r.in in reads)) throw new PackError(`${name}: read '${rid}': go needs 'in' (the board grid read)`);
    } else if (r.kind === "tetris") {
      if (!(r.in in reads)) throw new PackError(`${name}: read '${rid}': tetris needs 'in'`);
    } else if (r.kind === "slide") {
      if (!(r.in in reads)) throw new PackError(`${name}: read '${rid}': slide needs 'in' (the 4x4 number grid read), optionally depth and corner`);
    } else if (r.kind === "gap") {
      if (!(r.in in reads) || r.symbol === undefined) throw new PackError(`${name}: read '${rid}': gap needs 'in' (a grid read, scanned left to right) and 'symbol' (what counts as an obstacle)`);
    } else if (r.kind === "head") {
      if (!(r.in in reads)) throw new PackError(`${name}: read '${rid}': head needs 'in' (a grid read) and 'symbol' (the body's symbol)`);
    } else if (r.kind === "margin") {
      if (!(r.of in reads) || (r.in !== undefined && !(r.in in reads)) || (r.in === undefined && r.lower === undefined && r.upper === undefined)) throw new PackError(`${name}: read '${rid}': margin needs 'of' (a locate read) and 'in' (a grid read), or 'of' (a number read) with lower and/or upper`);
    } else if (r.kind === "predict") {
      if (!(r.of in reads) || !reads[r.of].history) throw new PackError(`${name}: read '${rid}': predict needs 'of' (a locate read with history: 1)`);
    } else if (r.kind === "json_grid") {
      if (r.cols === undefined || r.rows === undefined || !r.symbols || typeof r.symbols !== "object") throw new PackError(`${name}: read '${rid}': json_grid needs cols, rows and symbols`);
    } else if (r.kind === "json") {
      if (r.path === undefined) throw new PackError(`${name}: read '${rid}': json needs 'path'`);
    } else if (!r.zone && !r.rect) {
      throw new PackError(`${name}: read '${rid}': needs zone or rect`);
    }
  }
  const actions: ActionDef[] = [];
  for (const a of raw.act ?? []) {
    if (!a.id) throw new PackError(`${name}: every action needs an id`);
    const kind = a.kind ?? (a.id === "wait" ? "wait" : "tap");
    if (kind === "macro" && !a.options) throw new PackError(`${name}: action '${a.id}': macro needs 'options: <read id>'`);
    if (kind === "chunk" && !(Array.isArray(a.keys) && a.keys.length)) throw new PackError(`${name}: action '${a.id}': chunk needs 'keys: [<key>, ...]' (optionally key_ms, hold_ms)`);
    if (kind === "mouse_move" && a.dx === undefined && a.dy === undefined) throw new PackError(`${name}: action '${a.id}': mouse_move needs dx and/or dy (pixels of relative motion)`);
    if (kind === "key" && a.key === undefined) throw new PackError(`${name}: action '${a.id}': key needs 'key' (optionally hold_ms)`);
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
    const cs: any[] = Array.isArray(rl.if) && rl.if.length ? rl.if : [rl.if ?? {}];   // a list: all must hold
    for (const c of cs) {
      const okNoul = c && "noul" in c && ("gte" in c || "lte" in c);
      if (!okNoul && !condOk(c)) throw new PackError(`${name}: rule needs if: {noul, gte|lte} or if: {read, equals|in|not|gte|lte|contains}`);
    }
    if (rl.unless !== undefined && !(Array.isArray(rl.unless) && rl.unless.length ? rl.unless : [rl.unless]).every(condOk))
      throw new PackError(`${name}: rule 'unless' needs {read, equals|in|not|gte|lte|contains}: the rule does not apply when it holds`);
    if (!["exclude", "set", "avoid", "only"].some((k) => k in rl)) throw new PackError(`${name}: rule needs exclude, set, avoid or only`);
  }
  const tests: Test[] = raw.tests ?? [];
  const tasks = checkTasks(raw.tasks, reads, name, undefined, zones);
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
    questions, rules, tests, raw, modes, fingerprints, tasks,
  };
}
