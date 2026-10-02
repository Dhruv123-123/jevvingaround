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
  const legal: string[] = [], good: string[] = [], captures: string[] = [], saves: string[] = [], selfAtari: string[] = [], eyes: string[] = [];
  const takenBy: Record<string, number> = {}, worth: Record<string, number> = {};
  const [eu0, et0] = estimate(b, us, them);
  for (const p of order) {
    if (b.get(p) !== empty) continue;
    const res = play(b, p, us, them, w, h, empty);
    if (!res) continue;
    legal.push(p);
    if (res.taken) { captures.push(p); takenBy[p] = res.taken; }
    if (res.libs >= 2 && nbrs(p, w, h).some(n => ourAtari.has(n))) saves.push(p);
    const eye = isEye(b, p, us, w, h, empty);
    if (eye) eyes.push(p);
    const sa = res.libs === 1 && !res.taken;
    if (sa) selfAtari.push(p);
    if (!eye && !sa) {
      good.push(p);
      const [eu, et] = estimate(res.nb, us, them);
      let v = (eu - eu0) - (et - et0);
      const atariNbrs = new Set(nbrs(p, w, h).filter(n => ourAtari.has(n)));
      const counted = new Set<string>();
      for (const n of atariNbrs) if (!counted.has(n)) { const [st] = group(b, n, w, h, empty); st.forEach(x => counted.add(x)); v += 2 * st.size; }
      if (res.libs === 2) v -= group(res.nb, p, w, h, empty)[0].size;
      for (const n of nbrs(p, w, h)) {
        if (res.nb.get(n) !== them) continue;
        const [st2, lb2] = group(res.nb, n, w, h, empty);
        if (lb2.size === 1 && res.libs >= 2) v += st2.size;
      }
      worth[p] = Math.round(v * 10) / 10;
    }
  }
  const [su, st] = areaScore(b, us, them, w, h, empty);
  const byPos = (s: Set<string>) => order.filter(k => s.has(k));
  const best = Object.keys(worth).sort((a, c) => worth[c] - worth[a]).slice(0, Number(r.top_k ?? 6));
  return {
    legal, good, captures, saves, self_atari: selfAtari, eyes,
    urgent: [...captures, ...saves.filter(c => !captures.includes(c))],
    our_atari: byPos(ourAtari), their_atari: byPos(theirAtari),
    moves_left: good.length, captured_by_move: takenBy,
    best, worth: Object.fromEntries(best.map(k => [k, worth[k]])),
    estimate: { us: eu0, them: et0 + komi, lead: eu0 - et0 - komi },
    stones: { us: [...b.values()].filter(v => v === us).length, them: [...b.values()].filter(v => v === them).length },
    score: { us: su, them: st + komi, lead: su - st - komi },
  };
}
