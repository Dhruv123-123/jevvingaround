// The Go compiler: same semantics as anygame/perceive/go.py. A board read becomes groups, liberties and the
// consequences of every move for one colour; stateless, so a ko recapture looks legal and the page refuses it.
import type { ReadDef } from "./pack.js";

type B = Map<string, string>;
const key = (c: number, r: number) => `c${c}r${r}`;

function board(src: any): { b: B; w: number; h: number } {
  const b: B = new Map();
  if (Array.isArray(src)) src.forEach((row, r) => [...String(row)].forEach((ch, c) => b.set(key(c + 1, r + 1), ch)));
  else if (src && typeof src === "object") for (const [k, v] of Object.entries(src)) if (/^c\d+r\d+$/.test(k)) b.set(k, String(v));
  let w = 0, h = 0;
  for (const k of b.keys()) { const m = /^c(\d+)r(\d+)$/.exec(k)!; w = Math.max(w, +m[1]); h = Math.max(h, +m[2]); }
  return { b, w, h };
}

const xy = (k: string): [number, number] => { const m = /^c(\d+)r(\d+)$/.exec(k)!; return [+m[1], +m[2]]; };
function nbrs(k: string, w: number, h: number): string[] {
  const [c, r] = xy(k);
  return [[1, 0], [-1, 0], [0, 1], [0, -1]].map(([dc, dr]) => [c + dc, r + dr]).filter(([x, y]) => x >= 1 && x <= w && y >= 1 && y <= h).map(([x, y]) => key(x, y));
}

function group(b: B, p: string, w: number, h: number, empty: string): [Set<string>, Set<string>] {
  const col = b.get(p), st = new Set([p]), lb = new Set<string>(), todo = [p];
  while (todo.length) {
    const q = todo.pop()!;
    for (const n of nbrs(q, w, h)) {
      const v = b.get(n);
      if (v === empty) lb.add(n);
      else if (v === col && !st.has(n)) { st.add(n); todo.push(n); }
    }
  }
  return [st, lb];
}

function estimate(b: B, us: string, them: string, reach = 3): [number, number] {
  const pts: Record<string, [number, number][]> = { [us]: [], [them]: [] };
  for (const [k, v] of b) if (v in pts) pts[v].push(xy(k));
  const s: Record<string, number> = { [us]: pts[us].length, [them]: pts[them].length };
  for (const [k, v] of b) {
    if (v in pts) continue;
    const [c, r] = xy(k);
    const d = (side: string) => pts[side].reduce((m, [x, y]) => Math.min(m, Math.abs(c - x) + Math.abs(r - y)), 99);
    const du = d(us), dt = d(them);
    if (du < dt && du <= reach) s[us]++;
    else if (dt < du && dt <= reach) s[them]++;
  }
  return [s[us], s[them]];
}

function play(b: B, p: string, col: string, other: string, w: number, h: number, empty: string): { nb: B; taken: number; libs: number } | null {
  if (b.get(p) !== empty) return null;
  const nb = new Map(b);
  nb.set(p, col);
  let taken = 0;
  for (const n of nbrs(p, w, h)) {
    if (nb.get(n) !== other) continue;
    const [st, lb] = group(nb, n, w, h, empty);
    if (!lb.size) { for (const s of st) nb.set(s, empty); taken += st.size; }
  }
  const [, libs] = group(nb, p, w, h, empty);
  return libs.size ? { nb, taken, libs: libs.size } : null;
}

// The chain at p is in atari and its owner moves: extend, or capture an attacking chain in atari; three liberties is
// safe, two means the attacker reads on. Same as _respond in go.py.
function respond(b: B, p: string, att: string, dfn: string, w: number, h: number, empty: string, depth: number): boolean {
  const [st, lb] = group(b, p, w, h, empty);
  const moves = new Set(lb);
  for (const s of st) for (const n of nbrs(s, w, h)) if (b.get(n) === att) { const [, alb] = group(b, n, w, h, empty); if (alb.size === 1) alb.forEach(x => moves.add(x)); }
  for (const m of moves) {
    const res = play(b, m, dfn, att, w, h, empty);
    if (!res) continue;
    const libs = group(res.nb, p, w, h, empty)[1].size;
    if (libs >= 3 || (libs === 2 && !attack(res.nb, p, att, dfn, w, h, empty, depth - 1))) return true;
  }
  return false;
}

// The attacker moves: can it capture the chain at p however its owner answers? Ataris only (ladders, short chases).
function attack(b: B, p: string, att: string, dfn: string, w: number, h: number, empty: string, depth = 12): boolean {
  if (b.get(p) !== dfn) return false;
  const [, lb] = group(b, p, w, h, empty);
  if (lb.size === 1) return true;
  if (lb.size >= 3 || depth <= 0) return false;
  for (const lib of lb) {
    const res = play(b, lib, att, dfn, w, h, empty);
    if (res && !respond(res.nb, p, att, dfn, w, h, empty, depth)) return true;
  }
  return false;
}

function isEye(b: B, p: string, col: string, w: number, h: number, empty: string): boolean {
  if (b.get(p) !== empty || nbrs(p, w, h).some(n => b.get(n) !== col)) return false;
  const [c, r] = xy(p);
  const diag = [[-1, -1], [1, -1], [-1, 1], [1, 1]].map(([dc, dr]) => [c + dc, r + dr]).filter(([x, y]) => x >= 1 && x <= w && y >= 1 && y <= h);
  const bad = diag.filter(([x, y]) => { const v = b.get(key(x, y)); return v !== col && v !== empty; }).length;
  return diag.length < 4 ? bad === 0 : bad <= 1;
}

function areaScore(b: B, us: string, them: string, w: number, h: number, empty: string): [number, number] {
  const s: Record<string, number> = { [us]: 0, [them]: 0 };
  for (const v of b.values()) if (v in s) s[v]++;
  const seen = new Set<string>();
  for (const [p, v] of b) {
    if (v !== empty || seen.has(p)) continue;
    const region = new Set([p]), border = new Set<string>(), todo = [p];
    while (todo.length) {
      const q = todo.pop()!;
      for (const n of nbrs(q, w, h)) {
        const nv = b.get(n)!;
        if (nv === empty && !region.has(n)) { region.add(n); todo.push(n); }
        else if (nv in s) border.add(nv);
      }
    }
    region.forEach(x => seen.add(x));
    if (border.size === 1) s[[...border][0]] += region.size;
  }
  return [s[us], s[them]];
}

// ---- random playouts: a flat 1-D board (0 empty, 1 us, 2 them), as _playout in go.py -------------------------------
function geometry(w: number, h: number): [number[][], number[][]] {
  const nb: number[][] = [], dg: number[][] = [];
  for (let r = 0; r < h; r++) for (let c = 0; c < w; c++) {
    nb.push([[1, 0], [-1, 0], [0, 1], [0, -1]].filter(([dc, dr]) => c + dc >= 0 && c + dc < w && r + dr >= 0 && r + dr < h).map(([dc, dr]) => (r + dr) * w + c + dc));
    dg.push([[-1, -1], [-1, 1], [1, -1], [1, 1]].filter(([dc, dr]) => c + dc >= 0 && c + dc < w && r + dr >= 0 && r + dr < h).map(([dc, dr]) => (r + dr) * w + c + dc));
  }
  return [nb, dg];
}

/** A seeded generator in [0, 1): the board string picks the stream, so the same board reads the same. (Python seeds
 *  random.Random with the same string; the streams differ, the statistics do not.) */
function seeded(text: string): () => number {
  let h = 1779033703 ^ text.length;
  for (let i = 0; i < text.length; i++) { h = Math.imul(h ^ text.charCodeAt(i), 3432918353); h = (h << 13) | (h >>> 19); }
  let a = h >>> 0;
  return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

function hasLib(g: Uint8Array, i: number, nb: number[][], seen: Uint8Array, stack: number[]): boolean {
  const c = g[i]; seen.fill(0); seen[i] = 1; stack.length = 0; stack.push(i);
  while (stack.length) for (const n of nb[stack.pop()!]) { const v = g[n]; if (v === 0) return true; if (v === c && !seen[n]) { seen[n] = 1; stack.push(n); } }
  return false;
}

function chain(g: Uint8Array, i: number, nb: number[][]): number[] {
  const c = g[i], out = [i], seen = new Set([i]), todo = [i];
  while (todo.length) for (const n of nb[todo.pop()!]) if (g[n] === c && !seen.has(n)) { seen.add(n); out.push(n); todo.push(n); }
  return out;
}

/** Random moves to the end (two passes or 150 moves) from g with p to move: never an own eye, never suicide, the
 *  same policy as the page's `ai=mc` white. Our (1) area minus theirs. */
function playout(g0: Uint8Array, p: number, rng: () => number, nb: number[][], dg: number[][]): number {
  const g = Uint8Array.from(g0), seen = new Uint8Array(g.length), stack: number[] = [];
  const empt: number[] = []; g.forEach((v, i) => { if (!v) empt.push(i); });
  let passes = 0, n = 0;
  while (passes < 2 && n < 150) {
    let moved = false, k = empt.length;
    while (k > 0) {
      const j = Math.floor(rng() * k), i = empt[j];
      empt[j] = empt[k - 1]; empt[k - 1] = i;
      k--;
      if (nb[i].every((m) => g[m] === p)) {            // an own eye: never filled
        const d = dg[i]; let bad = 0; for (const x of d) if (g[x] === 3 - p) bad++;
        if (d.length < 4 ? bad === 0 : bad <= 1) continue;
      }
      g[i] = p;
      const caps: number[] = [];
      for (const m of nb[i]) if (g[m] === 3 - p && !hasLib(g, m, nb, seen, stack)) caps.push(...chain(g, m, nb));
      for (const s of caps) g[s] = 0;
      if (!caps.length && !hasLib(g, i, nb, seen, stack)) { g[i] = 0; continue; }    // suicide
      empt[k] = empt[empt.length - 1]; empt.pop();
      for (const s of new Set(caps)) empt.push(s);
      moved = true;
      break;
    }
    passes = moved ? 0 : passes + 1;
    n++;
    p = 3 - p;
  }
  const sc = [0, 0, 0];
  for (let i = 0; i < g.length; i++) {
    if (g[i]) { sc[g[i]]++; continue; }
    let o = 0, mixed = false;
    for (const m of nb[i]) { const v = g[m]; if (!v) { mixed = true; break; } if (o && v !== o) { mixed = true; break; } o = v; }
    if (!mixed && o) sc[o]++;
  }
  return sc[1] - sc[2];
}

const PLAYOUT_CACHE = new Map<string, Record<string, number[]>>();      // per board: each candidate's game margins so far

/** For each candidate move of ours: n random games from the board after it (white to move), our win rate and mean
 *  margin after komi. Cached per board and seeded from it, so a board that has not changed costs nothing. */
export function goPlayouts(b: B, cands: string[], us: string, them: string, w: number, h: number, empty: string, komi: number, n: number,
                           top = 0, topN = 0): Record<string, { win: number; margin: number; n: number }> {
  // `top` with `topN`: the `top` best of the first pass are played on to `topN` games each, so the close contenders separate
  const flat = (bb: B) => { const g = new Uint8Array(w * h); for (let r = 1; r <= h; r++) for (let c = 1; c <= w; c++) { const v = bb.get(key(c, r)); g[(r - 1) * w + c - 1] = v === us ? 1 : v === them ? 2 : 0; } return g; };
  const k = `${w}x${h}:${komi}:` + flat(b).join("");
  let runs = PLAYOUT_CACHE.get(k);
  if (!runs) { if (PLAYOUT_CACHE.size > 64) PLAYOUT_CACHE.clear(); runs = {}; PLAYOUT_CACHE.set(k, runs); }
  const starts: Record<string, Uint8Array | null> = {};
  let geo: [number[][], number[][]] | null = null;
  const more = (p: string, upto: number) => {
    const got = (runs![p] ??= []);
    if (got.length >= upto) return;
    if (!(p in starts)) { const res = play(b, p, us, them, w, h, empty); starts[p] = res ? flat(res.nb) : null; }
    const g = starts[p];
    if (!g) return;
    geo ??= geometry(w, h);
    const rng = seeded(k + p + got.length);     // seeded by the games it already has: same board, same games
    while (got.length < upto) got.push(playout(g, 2, rng, geo![0], geo![1]) - komi);
  };
  const summary = (p: string) => { const m = runs![p]; return { win: Math.round((m.filter((x) => x > 0).length / m.length) * 100) / 100, margin: Math.round((m.reduce((a, x) => a + x, 0) / m.length) * 10) / 10, n: m.length }; };
  for (const p of cands) more(p, n);
  const done = cands.filter((p) => runs![p]?.length);
  if (top && topN > n) {
    const lead = [...done].sort((x, y) => { const a = summary(x), c = summary(y); return c.win - a.win || c.margin - a.margin; }).slice(0, top);
    for (const p of lead) more(p, topN);
  }
  return Object.fromEntries(done.map((p) => [p, summary(p)]));
}
export const clearGoPlayoutCache = () => PLAYOUT_CACHE.clear();

/** `rerank: playouts`: the playout leader goes first in `best` when its win rate beats the first `best` move's by
 *  `margin` or more (`extra.reranked` says {from, to, gap}). The leader is picked among the good moves with the most
 *  games (the `playouts_top` leaders), so a lucky 32-game result never jumps the queue; a tie on win goes to the
 *  higher margin, then to the `best` order. Port of rerank in perceive/go.py. */
export function goRerank(best: string[], po: Record<string, { win: number; margin: number; n: number }>, good: Set<string>, margin: number, extra: Record<string, any>): string[] {
  const top = best[0];
  if (!(top in po)) return best;
  const ranked = Object.keys(po).filter((k) => good.has(k));
  const most = Math.max(0, ...ranked.map((k) => po[k].n));
  const pool = ranked.filter((k) => po[k].n === most);
  if (!pool.length) return best;
  const order = (k: string) => (best.includes(k) ? best.indexOf(k) : best.length);
  const lead = pool.reduce((a, k) => {
    const d = po[k].win - po[a].win || po[k].margin - po[a].margin || order(a) - order(k);
    return d > 0 ? k : a;
  });
  const gap = Math.round((po[lead].win - po[top].win) * 100) / 100;
  if (lead === top || gap < margin - 1e-9) return best;
  extra.reranked = { from: top, to: lead, gap };
  return [lead, ...best.filter((k) => k !== lead)];
}

export function goRead(src: any, r: ReadDef): Record<string, any> | null {
  const { b, w, h } = board(src);
  if (!b.size) return null;
  const us = String(r.us ?? "B"), them = String(r.them ?? "W"), empty = String(r.empty ?? "."), komi = Number(r.komi ?? 0);
  const order = [...b.keys()].sort((a, c) => { const [ac, ar] = xy(a), [cc, cr] = xy(c); return ar - cr || ac - cc; });
  const ourAtari = new Set<string>(), theirAtari = new Set<string>(), seen = new Set<string>();
  for (const p of order) {
    const v = b.get(p);
    if ((v !== us && v !== them) || seen.has(p)) continue;
    const [st, lb] = group(b, p, w, h, empty);
    st.forEach(x => seen.add(x));
    if (lb.size === 1) st.forEach(x => (v === us ? ourAtari : theirAtari).add(x));
  }
  // chains white can capture by moving first (a ladder or a chase): ours on two liberties that do not get away
  const danger = new Set<string>(), chased: [string, Set<string>][] = [];
  seen.clear();
  for (const p of order) {
    if (b.get(p) !== us || seen.has(p)) continue;
    const [st, lb] = group(b, p, w, h, empty);
    st.forEach(x => seen.add(x));
    if (lb.size === 2 && attack(b, p, them, us, w, h, empty)) { st.forEach(x => danger.add(x)); chased.push([p, st]); }
  }
  const legal: string[] = [], good: string[] = [], captures: string[] = [], saves: string[] = [], selfAtari: string[] = [], eyes: string[] = [], doomed: string[] = [];
  const takenBy: Record<string, number> = {}, worth: Record<string, number> = {};
  const [eu0, et0] = estimate(b, us, them);
  for (const p of order) {
    if (b.get(p) !== empty) continue;
    const res = play(b, p, us, them, w, h, empty);
    if (!res) continue;
    legal.push(p);
    if (res.taken) { captures.push(p); takenBy[p] = res.taken; }
    const dies = res.libs === 2 && attack(res.nb, p, them, us, w, h, empty);
    if (res.libs >= 2 && !dies && nbrs(p, w, h).some(n => ourAtari.has(n))) saves.push(p);
    const eye = isEye(b, p, us, w, h, empty);
    if (eye) eyes.push(p);
    const sa = res.libs === 1 && !res.taken;
    if (sa) selfAtari.push(p);
    if (dies && !res.taken && !sa) doomed.push(p);
    if (!eye && !sa) {
      good.push(p);
      const [eu, et] = estimate(res.nb, us, them);
      let v = (eu - eu0) - (et - et0);
      const atariNbrs = new Set(nbrs(p, w, h).filter(n => ourAtari.has(n)));
      const counted = new Set<string>();
      for (const n of atariNbrs) if (!counted.has(n)) { const [st] = group(b, n, w, h, empty); st.forEach(x => counted.add(x)); v += 2 * st.size; }
      const mine = group(res.nb, p, w, h, empty)[0];
      if (dies) v -= 2 * mine.size + 5;
      for (const [q, st3] of chased)
        if ((res.taken || nbrs(p, w, h).some(n => st3.has(n))) && !attack(res.nb, q, them, us, w, h, empty)) v += 2 * st3.size + 4;
      const hit = new Set<string>();
      for (const n of nbrs(p, w, h)) {
        if (res.nb.get(n) !== them || hit.has(n)) continue;
        const [st2, lb2] = group(res.nb, n, w, h, empty);
        st2.forEach(x => hit.add(x));
        if (lb2.size === 1 && !dies) v += respond(res.nb, n, us, them, w, h, empty, 12) ? 0.5 * st2.size : 2 * st2.size;
      }
      worth[p] = Math.round(v * 10) / 10;
    }
  }
  const [su, st] = areaScore(b, us, them, w, h, empty);
  const byPos = (s: Set<string>) => order.filter(k => s.has(k));
  let best = Object.keys(worth).sort((a, c) => worth[c] - worth[a]).slice(0, Number(r.top_k ?? 6));
  const extra: Record<string, any> = {};
  const nPo = Number(r.playouts ?? 0);
  if (nPo > 0) {
    extra.playouts = goPlayouts(b, [...new Set([...best, ...captures, ...saves])], us, them, w, h, empty, komi, nPo, Number(r.playouts_top ?? 0), Number(r.playouts_top_n ?? 0));
    if (r.rerank === "playouts" && best.length) best = goRerank(best, extra.playouts, new Set(good), Number(r.rerank_margin ?? 0.06), extra);
  }
  return {
    ...extra,
    legal, good, captures, saves, self_atari: selfAtari, eyes,
    urgent: [...captures, ...saves.filter(c => !captures.includes(c))],
    our_atari: byPos(ourAtari), their_atari: byPos(theirAtari), danger: byPos(danger), doomed,
    moves_left: good.length, captured_by_move: takenBy,
    best, worth: Object.fromEntries(best.map(k => [k, worth[k]])),
    estimate: { us: eu0, them: et0 + komi, lead: eu0 - et0 - komi },
    stones: { us: [...b.values()].filter(v => v === us).length, them: [...b.values()].filter(v => v === them).length },
    score: { us: su, them: st + komi, lead: su - st - komi },
  };
}
