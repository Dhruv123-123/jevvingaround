// Perception: pixels → values, and the derived reads that do the counting Jev must never do
// (locate, runs, around). OCR / templates / detectors are not available in the extension and read as null.
import { crop, inset, type Frame, type Rect } from "./geometry.js";
import { accentColor, hexToRgb, labDist, meanColor, medianColor, nearestNamed, rgbToLab, type RGB } from "./color.js";
import type { Pack, ReadDef } from "./pack.js";

export type Values = Record<string, any>;

function rectFor(pack: Pack, r: ReadDef): Rect {
  if (r.zone) return pack.zones[r.zone].rect;
  const [x0, y0, x1, y1] = (r.rect as number[]).map(Number);
  return { x0, y0, x1, y1 };
}

function sample(img: Frame, r: ReadDef): RGB {
  const st = r.stat ?? "median";
  const ins = Number(r.inset ?? 0);
  if (st === "accent") return accentColor(img, Number(r.min_share ?? 0.03), 40, ins);
  const f = inset(img, ins);
  return st === "median" ? medianColor(f) : meanColor(f);
}

function labelOf(img: Frame, r: ReadDef, hit?: { n: number; ok: number }): any {
  if (!img.width || !img.height) return r.otherwise ?? "unknown";
  const options: Record<string, string> = {};
  for (const [k, v] of Object.entries(r.options ?? {})) options[String(k)] = String(v);
  const [name, dist] = nearestNamed(sample(img, r), options);
  const matched = dist <= Number(r.max_dist ?? 120);
  if (hit) { hit.n++; if (matched) hit.ok++; }
  let val: any = matched ? name : (r.otherwise ?? "unknown");
  if (r.parse === "int") {
    const n = parseInt(String(val), 10);
    val = Number.isNaN(n) ? (r.empty ?? 0) : n;
  }
  return val;
}

export function readColor(frame: Frame, pack: Pack, r: ReadDef, hit?: { n: number; ok: number }): any {
  const zone = r.zone ? pack.zones[r.zone] : null;
  if (zone && zone.grid) {
    const out: Record<string, any> = {};
    for (const [name, cr] of Object.entries(zone.cells())) out[name.split(".", 2)[1]] = labelOf(crop(frame, cr), r, hit);
    return out;
  }
  return labelOf(crop(frame, rectFor(pack, r)), r, hit);
}

export function readBar(frame: Frame, pack: Pack, r: ReadDef): number {
  const img = crop(frame, rectFor(pack, r));
  if (!img.width || !img.height) return 0;
  const target = rgbToLab(...hexToRgb(String(r.color)));
  const tol = Math.floor((Number(r.tol ?? 40) * 3) / 2);
  const axis = r.axis ?? "x";
  const len = axis === "x" ? img.width : img.height;
  const per = new Float64Array(len);
  for (let y = 0; y < img.height; y++) {
    for (let x = 0; x < img.width; x++) {
      const i = (y * img.width + x) * 4;
      const on = labDist(rgbToLab(img.data[i], img.data[i + 1], img.data[i + 2]), target) <= tol ? 1 : 0;
      if (axis === "x") per[x] += on / img.height; else per[img.height - 1 - y] += on / img.width;
    }
  }
  let n = 0, gap = 0;
  for (let i = 0; i < len; i++) {
    if (per[i] > 0.3) { n++; gap = 0; } else { gap++; if (gap > Math.max(2, Math.floor(len / 40))) break; n++; }
  }
  const frac = Math.min(1, n / Math.max(1, len));
  const scale = Number(r.scale ?? 1), step = Number(r.step ?? 0.1);
  return Math.round(Math.round((frac * scale) / step) * step * 100) / 100;
}

export function locate(src: any, r: ReadDef): any {
  let cells = Object.entries(src ?? {}).filter(([, v]) => String(v) === String(r.symbol)).map(([k]) => k);
  if (r.row !== undefined) cells = cells.filter((c) => c.endsWith(`r${r.row}`));
  if (r.col !== undefined) cells = cells.filter((c) => c.startsWith(`c${r.col}r`) || c === `c${r.col}`);
  return r.many ? cells : cells[0] ?? null;
}

type Cell = [number, number];
function parseCells(src: any): Map<string, string> {
  const m = new Map<string, string>();
  if (!src || typeof src !== "object" || Array.isArray(src)) return m;
  for (const [k, v] of Object.entries(src)) if (/^c\d+r\d+$/.test(k)) m.set(k, String(v));
  return m;
}
const key = (c: number, r: number) => `c${c}r${r}`;

/** Empty cells that would complete `length` of `symbol` in a line; gravity: down keeps landing cells; mode: hands finds poisoned drops. */
export function runsOf(src: any, r: ReadDef): string[] {
  const cells = parseCells(src);
  if (!cells.size) return [];
  const sym = String(r.symbol), empty = String(r.empty ?? "."), need = Number(r.length ?? 4);
  let rows = 0;
  const coords: Cell[] = [];
  for (const k of cells.keys()) { const m = k.match(/^c(\d+)r(\d+)$/)!; const c = +m[1], rr = +m[2]; coords.push([c, rr]); rows = Math.max(rows, rr); }
  const completes = (c: number, rw: number) => {
    for (const [dc, dr] of [[1, 0], [0, 1], [1, 1], [1, -1]] as const) {
      let n = 1;
      for (const sgn of [1, -1]) {
        let cc = c + sgn * dc, rr = rw + sgn * dr;
        while (cells.get(key(cc, rr)) === sym) { n++; cc += sgn * dc; rr += sgn * dr; }
      }
      if (n >= need) return true;
    }
    return false;
  };
  const out: string[] = [];
  coords.sort((a, b) => a[1] - b[1] || a[0] - b[0]);
  for (const [c, rw] of coords) {
    if (cells.get(key(c, rw)) !== empty) continue;
    const landing = !(r.gravity === "down" && rw < rows && cells.get(key(c, rw + 1)) === empty);
    if (r.mode === "hands") {
      if (landing && rw > 1 && cells.get(key(c, rw - 1)) === empty && completes(c, rw - 1)) out.push(key(c, rw));
      continue;
    }
    if (r.gravity === "down" && !landing) continue;
    if (completes(c, rw)) out.push(key(c, rw));
  }
  return out;
}

function space(cells: Map<string, string>, start: Cell, free: Set<string>): number {
  if (!free.has(cells.get(key(start[0], start[1])) ?? "wall")) return 0;
  const seen = new Set<string>([key(start[0], start[1])]);
  const todo: Cell[] = [start];
  while (todo.length) {
    const [c, r] = todo.pop()!;
    for (const [dc, dr] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const k = key(c + dc, r + dr);
      if (!seen.has(k) && free.has(cells.get(k) ?? "wall")) { seen.add(k); todo.push([c + dc, r + dr]); }
    }
  }
  return seen.size;
}

/** What sits next to a located cell: neighbours, straight ahead, free run and flood-fill space per direction. */
export function aroundOf(cell: any, src: any, moving: string | null, r: ReadDef): Record<string, any> | null {
  const m = String(cell ?? "").match(/^c(\d+)r(\d+)$/);
  const cells = parseCells(src);
  if (!m || !cells.size) return null;
  const c = +m[1], rw = +m[2];
  const free = new Set<string>(((r.free as any[]) ?? ["."]).map(String));
  const out: Record<string, any> = {};
  for (const [name, [dc, dr]] of Object.entries({ up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] } as Record<string, [number, number]>)) {
    out[name] = cells.get(key(c + dc, rw + dr)) ?? "wall";
    let n = 0, cc = c + dc, rr = rw + dr;
    while (free.has(cells.get(key(cc, rr)) ?? "wall")) { n++; cc += dc; rr += dr; }
    out[`${name}_free`] = n;
    out[`${name}_space`] = space(cells, [c + dc, rw + dr], free);
  }
  if (moving && moving in out) { out.ahead = out[moving]; out.ahead_free = out[`${moving}_free`]; out.ahead_space = out[`${moving}_space`]; }
  return out;
}

/** The pixel and simple derived reads. Loop-state reads (around, tetris) are computed by the Agent. */
/** Confidence per read, 0..1: how much of what the read looked for it actually found. The loop averages
 *  these into a support score; a screen the pack does not understand scores low. */
export function readAll(pack: Pack, frame: Frame, only?: Set<string>): { values: Values; timings: Record<string, number>; conf: Record<string, number> } {
  const values: Values = {};
  const timings: Record<string, number> = {};
  const conf: Record<string, number> = {};
  for (const [rid, r] of Object.entries(pack.reads)) {
    if (only && !only.has(rid)) continue;
    const t0 = performance.now();
    switch (r.kind) {
      case "color": { const hit = { n: 0, ok: 0 }; values[rid] = readColor(frame, pack, r, hit); if (hit.n) conf[rid] = hit.ok / hit.n; break; }
      case "bar": values[rid] = readBar(frame, pack, r); conf[rid] = 1; break;
      case "locate": values[rid] = locate(values[r.in], r); if (!r.many) conf[rid] = values[rid] ? 1 : 0; break;
      case "runs": values[rid] = runsOf(values[r.in], r); break;
      case "around": case "tetris": continue;
      default: values[rid] = null;   // ocr, templates, blobs, vocab: not in the extension
    }
    timings[rid] = Math.round((performance.now() - t0) * 10) / 10;
  }
  return { values, timings, conf };
}
