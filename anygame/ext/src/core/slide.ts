// The 2048 compiler: each swipe simulated exactly and ranked by an expectimax search over the random spawn,
// presented as ranked, annotated options. Port of anygame/perceive/slide.py.
type Grid = number[];
const DIRS = ["up", "down", "left", "right"] as const;
const CORNERS: Record<string, [number, number]> = { c1r1: [0, 0], c4r1: [0, 3], c1r4: [3, 0], c4r4: [3, 3] };

function slideRow(row: number[]): [number[], number] {
  const t = row.filter((x) => x);
  const out: number[] = [];
  let gain = 0;
  for (let i = 0; i < t.length; i++) {
    if (i + 1 < t.length && t[i] === t[i + 1]) { out.push(t[i] * 2); gain += t[i] * 2; i++; } else out.push(t[i]);
  }
  while (out.length < 4) out.push(0);
  return [out, gain];
}

export function move(g: Grid, d: string): [Grid, number] {
  const nb = new Array(16).fill(0);
  let gain = 0;
  for (let k = 0; k < 4; k++) {
    const idx = [0, 1, 2, 3].map((m) => d === "left" ? k * 4 + m : d === "right" ? k * 4 + 3 - m : d === "up" ? m * 4 + k : (3 - m) * 4 + k);
    const [line, s] = slideRow(idx.map((i) => g[i]));
    gain += s;
    idx.forEach((i, j) => { nb[i] = line[j]; });
  }
  return [nb, gain];
}

function weights(corner: [number, number]): number[] {
  const order: [number, number][] = [];
  [3, 2, 1, 0].forEach((r, i) => { const cols = i % 2 === 0 ? [3, 2, 1, 0] : [0, 1, 2, 3]; for (const c of cols) order.push([r, c]); });
  const w = new Array(16).fill(0);
  order.forEach(([r, c], n) => {
    const rr = corner[0] === 3 ? r : 3 - r, cc = corner[1] === 3 ? c : 3 - c;
    w[rr * 4 + cc] = 4 ** (15 - n) / 4 ** 10;
  });
  return w;
}

const same = (a: Grid, b: Grid) => a.every((v, i) => v === b[i]);
const score = (g: Grid, w: number[]) => g.reduce((s, v, i) => s + v * w[i], 0) + 64 * g.filter((v) => v === 0).length;

function best(g: Grid, depth: number, w: number[], memo: Map<string, number>): number {
  const key = g.join(",") + "|" + depth;
  const hit = memo.get(key);
  if (hit !== undefined) return hit;
  let b: number | null = null;
  for (const d of DIRS) {
    const [ng, gain] = move(g, d);
    if (same(ng, g)) continue;
    const v = chance(ng, depth - 1, w, memo) + gain;
    if (b === null || v > b) b = v;
  }
  const out = b === null ? -1e9 : b;
  memo.set(key, out);
  return out;
}

function chance(g: Grid, depth: number, w: number[], memo: Map<string, number>): number {
  const empties = g.map((v, i) => (v ? -1 : i)).filter((i) => i >= 0);
  if (depth <= 0) return score(g, w);
  if (!empties.length) return best(g, depth, w, memo);
  let total = 0;
  for (const i of empties) for (const [tile, p] of [[2, 0.9], [4, 0.1]]) { const ng = [...g]; ng[i] = tile; total += p * best(ng, depth, w, memo); }
  return total / empties.length;
}

export function gridOf(src: any): Grid | null {
  if (Array.isArray(src) && src.length === 16) return src.map((v) => Number(v || 0));
  if (!src || typeof src !== "object") return null;
  const g = new Array(16).fill(0);
  for (const [k, v] of Object.entries(src)) {
    const m = /^c(\d)r(\d)$/.exec(k);
    if (!m) return null;
    g[(Number(m[2]) - 1) * 4 + Number(m[1]) - 1] = Number(v || 0);
  }
  return g;
}

export function rank(g: Grid, depth = 2, corner = "c4r4"): Record<string, any> {
  const cr = CORNERS[corner] ?? [3, 3];
  const w = weights(cr);
  const top = Math.max(...g);
  const memo = new Map<string, number>();
  const rows: { v: number; d: string; gain: number; empty: number; anchored: boolean }[] = [];
  for (const d of DIRS) {
    const [ng, gain] = move(g, d);
    if (same(ng, g)) continue;
    rows.push({ v: chance(ng, depth - 1, w, memo) + gain, d, gain, empty: ng.filter((x) => x === 0).length, anchored: top > 0 && ng[cr[0] * 4 + cr[1]] === top });
  }
  rows.sort((a, b) => b.v - a.v);
  const ranked: Record<string, string> = {};
  rows.forEach((r, n) => {
    ranked[r.d] = `${n === 0 ? "#1 best" : `#${n + 1}`}: merges +${r.gain}, ${r.empty} empty after, ${r.anchored ? "largest tile stays in the corner" : "largest tile NOT in the corner"}`;
  });
  return { legal: rows.map((r) => r.d), best: rows[0]?.d ?? "none", ranked, empty: g.filter((v) => v === 0).length, max: top,
           max_in_corner: top > 0 && g[cr[0] * 4 + cr[1]] === top };
}

export function slideOf(src: any, r: Record<string, any>): Record<string, any> | null {
  const g = gridOf(src);
  return g ? rank(g, Number(r.depth ?? 2), String(r.corner ?? "c4r4")) : null;
}
