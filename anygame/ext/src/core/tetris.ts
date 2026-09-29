// The Tetris compiler: the falling piece, the stack's features, and every reachable landing dropped in
// simulation with its consequences, as a typed choice. Port of anygame/perceive/tetris.py.
type Cell = [number, number];
type Offs = Cell[];

export const SHAPES: Record<string, Offs[]> = {
  I: [[[0, 1], [1, 1], [2, 1], [3, 1]], [[2, 0], [2, 1], [2, 2], [2, 3]], [[0, 2], [1, 2], [2, 2], [3, 2]], [[1, 0], [1, 1], [1, 2], [1, 3]]],
  O: [[[1, 0], [2, 0], [1, 1], [2, 1]], [[1, 0], [2, 0], [1, 1], [2, 1]], [[1, 0], [2, 0], [1, 1], [2, 1]], [[1, 0], [2, 0], [1, 1], [2, 1]]],
  T: [[[1, 0], [0, 1], [1, 1], [2, 1]], [[1, 0], [1, 1], [2, 1], [1, 2]], [[0, 1], [1, 1], [2, 1], [1, 2]], [[1, 0], [0, 1], [1, 1], [1, 2]]],
  S: [[[1, 0], [2, 0], [0, 1], [1, 1]], [[1, 0], [1, 1], [2, 1], [2, 2]], [[1, 1], [2, 1], [0, 2], [1, 2]], [[0, 0], [0, 1], [1, 1], [1, 2]]],
  Z: [[[0, 0], [1, 0], [1, 1], [2, 1]], [[2, 0], [1, 1], [2, 1], [1, 2]], [[0, 1], [1, 1], [1, 2], [2, 2]], [[1, 0], [0, 1], [1, 1], [0, 2]]],
  J: [[[0, 0], [0, 1], [1, 1], [2, 1]], [[1, 0], [2, 0], [1, 1], [1, 2]], [[0, 1], [1, 1], [2, 1], [2, 2]], [[1, 0], [1, 1], [0, 2], [1, 2]]],
  L: [[[2, 0], [0, 1], [1, 1], [2, 1]], [[1, 0], [1, 1], [1, 2], [2, 2]], [[0, 1], [1, 1], [2, 1], [0, 2]], [[0, 0], [1, 0], [1, 1], [1, 2]]],
};
const UNIQUE_ROTS: Record<string, number[]> = { I: [0, 1], O: [0], T: [0, 1, 2, 3], S: [0, 1], Z: [0, 1], J: [0, 1, 2, 3], L: [0, 1, 2, 3] };
const LABELS = "abcdefghij";
const k = (c: number, r: number) => `${c},${r}`;

function norm(cells: Cell[]): string {
  const mx = Math.min(...cells.map((c) => c[0])), my = Math.min(...cells.map((c) => c[1]));
  return cells.map(([c, r]) => k(c - mx, r - my)).sort().join(";");
}
const SHAPE_INDEX = new Map<string, [string, number][]>();
for (const [s, rots] of Object.entries(SHAPES)) rots.forEach((offs, r) => { const key = norm(offs); SHAPE_INDEX.set(key, [...(SHAPE_INDEX.get(key) ?? []), [s, r]]); });

export function identify(cells: Cell[]): [string, number, number, number] | null {
  if (cells.length !== 4) return null;
  const cands = SHAPE_INDEX.get(norm(cells));
  if (!cands) return null;
  const [s, r] = [...cands].sort((a, b) => a[1] - b[1])[0];
  const offs = SHAPES[s][r];
  const mx = Math.min(...cells.map((c) => c[0])), my = Math.min(...cells.map((c) => c[1]));
  const ox = Math.min(...offs.map((o) => o[0])), oy = Math.min(...offs.map((o) => o[1]));
  return [s, r, mx - ox, my - oy];
}

export function gridCells(src: any, empty: string): { filled: Set<string>; w: number; h: number } {
  const filled = new Set<string>();
  if (Array.isArray(src)) {
    src.forEach((row: string, r: number) => [...row].forEach((ch, c) => { if (ch !== empty) filled.add(k(c, r)); }));
    return { filled, w: src[0]?.length ?? 0, h: src.length };
  }
  let w = 0, h = 0;
  for (const [key, v] of Object.entries(src ?? {})) {
    const m = key.match(/^c(\d+)r(\d+)$/);
    if (!m) continue;
    const c = +m[1] - 1, r = +m[2] - 1;
    w = Math.max(w, c + 1); h = Math.max(h, r + 1);
    if (String(v) !== empty) filled.add(k(c, r));
  }
  return { filled, w, h };
}

export interface Features { heights: number[]; max_height: number; holes: number; bumpiness: number; well_col: number | null; well_depth: number; sum_height: number }

export function features(stack: Set<string>, w: number, h: number): Features {
  const heights: number[] = [];
  for (let c = 0; c < w; c++) {
    let top = h;
    for (let r = 0; r < h; r++) if (stack.has(k(c, r))) { top = r; break; }
    heights.push(h - top);
  }
  let holes = 0;
  for (let c = 0; c < w; c++) { const top = h - heights[c]; for (let r = top + 1; r < h; r++) if (!stack.has(k(c, r))) holes++; }
  let bump = 0;
  for (let i = 0; i < w - 1; i++) bump += Math.abs(heights[i] - heights[i + 1]);
  let wellCol = -1, wellDepth = 0;
  for (let c = 0; c < w; c++) {
    const left = c > 0 ? heights[c - 1] : 99, right = c < w - 1 ? heights[c + 1] : 99;
    const d = Math.min(left, right) - heights[c];
    if (d > wellDepth) { wellCol = c; wellDepth = d; }
  }
  return { heights, max_height: Math.max(0, ...heights), holes, bumpiness: bump, well_col: wellCol >= 0 ? wellCol + 1 : null, well_depth: wellDepth, sum_height: heights.reduce((a, b) => a + b, 0) };
}

export function drop(stack: Set<string>, shape: string, rot: number, x: number, w: number, h: number): [Cell[], number] | null {
  const offs = SHAPES[shape][rot];
  if (offs.some(([dx]) => x + dx < 0 || x + dx >= w)) return null;
  let y = -Math.min(...offs.map((o) => o[1])) - 1;
  let last: [Cell[], number] | null = null;
  for (;;) {
    const cells: Cell[] = offs.map(([dx, dy]) => [x + dx, y + dy]);
    if (cells.some(([c, r]) => r >= h || (r >= 0 && stack.has(k(c, r))))) break;
    last = [cells, y];
    y++;
  }
  if (!last || last[0].some(([, r]) => r < 0)) return null;
  return last;
}

export function settle(stack: Set<string>, cells: Cell[], w: number, h: number): [Set<string>, number] {
  const s = new Set(stack);
  for (const [c, r] of cells) s.add(k(c, r));
  const full: number[] = [];
  for (let r = 0; r < h; r++) { let ok = true; for (let c = 0; c < w; c++) if (!s.has(k(c, r))) { ok = false; break; } if (ok) full.push(r); }
  if (!full.length) return [s, 0];
  const out = new Set<string>();
  for (const key of s) {
    const [c, r] = key.split(",").map(Number);
    if (full.includes(r)) continue;
    const shift = full.filter((fr) => fr > r).length;
    out.add(k(c, r + shift));
  }
  return [out, full.length];
}

function score(base: Features, after: Features, lines: number): number {
  return 0.76 * lines - 0.51 * after.sum_height - 0.36 * after.holes - 0.18 * after.bumpiness - 1.5 * Math.max(0, after.holes - base.holes);
}

function components(cells: Set<string>): Set<string>[] {
  const seen = new Set<string>();
  const comps: Set<string>[] = [];
  const sorted = [...cells].map((s) => s.split(",").map(Number) as Cell).sort((a, b) => a[1] - b[1] || a[0] - b[0]);
  for (const start of sorted) {
    const sk = k(start[0], start[1]);
    if (seen.has(sk)) continue;
    const comp = new Set<string>();
    const todo: Cell[] = [start];
    while (todo.length) {
      const [c, r] = todo.pop()!;
      const key = k(c, r);
      if (seen.has(key) || !cells.has(key)) continue;
      seen.add(key); comp.add(key);
      todo.push([c + 1, r], [c - 1, r], [c, r + 1], [c, r - 1]);
    }
    comps.push(comp);
  }
  return comps;
}

interface Cand { rot: number; x: number; cells: Cell[]; lines: number; holes: number; height: number; bump: number; wellKept: boolean; reachable: boolean; score: number; rots: number; dx: number; label?: string }

export class TetrisTracker {
  keys: Record<string, string>;
  topK: number;
  movesPerRow: number;
  lastPiece: [string, number, number] | null = null;
  macros: Record<string, string[]> = {};
  predicted: Set<string> | null = null;
  settled: Set<string> | null = null;
  linesCleared = 0;
  private pendingLines = 0;
  private lastPlacement: string | null = null;
  private cands: Record<string, Cand> = {};
  private w = 0; private h = 0;

  constructor(public cfg: Record<string, any>) {
    this.keys = { rotate: "ArrowUp", left: "ArrowLeft", right: "ArrowRight", drop: "Space", ...(cfg.keys ?? {}) };
    this.topK = Number(cfg.top_k ?? 6);
    this.movesPerRow = Number(cfg.moves_per_row ?? 3);
  }

  read(board: any, preview: any): Record<string, any> {
    const empty = String(this.cfg.empty ?? ".");
    const { filled, w, h } = gridCells(board, empty);
    this.w = w; this.h = h;
    let nxt: string | null = null;
    if (preview !== null && preview !== undefined) {
      const pc = gridCells(preview, empty).filled;
      const ident = pc.size === 4 ? identify([...pc].map((s) => s.split(",").map(Number) as Cell)) : null;
      nxt = ident ? ident[0] : null;
    }
    let active: Set<string> | null = null;
    let ident: [string, number, number, number] | null = null;
    const expected = this.settled;
    if (expected && [...expected].every((c) => filled.has(c))) {
      const extra = new Set([...filled].filter((c) => !expected.has(c)));
      if (extra.size === 4) { const id = identify([...extra].map((s) => s.split(",").map(Number) as Cell)); if (id) { active = extra; ident = id; } }
    }
    if (!active) {
      const comps = components(filled).sort((a, b) => Math.min(...[...a].map((s) => +s.split(",")[1])) - Math.min(...[...b].map((s) => +s.split(",")[1])));
      const top = comps[0];
      if (top && top.size === 4) { const id = identify([...top].map((s) => s.split(",").map(Number) as Cell)); if (id) { active = top; ident = id; } }
    }
    const stack = new Set([...filled].filter((c) => !active || !active.has(c)));
    if (active) this.settled = stack;
    const feats = features(stack, w, h);
    const out: Record<string, any> = {
      phase: "none", shape: null, rot: null, col: null, row: null, next: nxt,
      stack: { max_height: feats.max_height, holes: feats.holes, bumpiness: feats.bumpiness, well_col: feats.well_col, well_depth: feats.well_depth, sum_height: feats.sum_height, danger: feats.max_height >= h - 6 },
      landings: {}, last_placement: null, lines_cleared: this.linesCleared,
    };
    if (this.predicted && active) {
      const same = expected && expected.size === stack.size && [...expected].every((c) => stack.has(c));
      this.lastPlacement = same ? "ok" : "missed";
      out.last_placement = this.lastPlacement;
      if (this.lastPlacement === "ok") this.linesCleared += this.pendingLines;
      this.pendingLines = 0;
      this.predicted = null;
      if (this.lastPlacement === "missed") this.settled = null;
      out.lines_cleared = this.linesCleared;
    }
    if (!ident || !active) { this.macros = {}; return out; }
    const [shape, rot, x, y] = ident;
    const phase = !this.lastPiece || this.lastPiece[0] !== shape || y < this.lastPiece[2] || this.lastPiece[2] - y > 4 ? "spawned" : "falling";
    this.lastPiece = [shape, x, y];
    Object.assign(out, { phase, shape, rot, col: x + 1, row: y + 1 });
    const straight = drop(stack, shape, rot, x, w, h);
    const rowsLeft = straight ? straight[1] - y : 0;
    const cands: Cand[] = [];
    for (const r2 of UNIQUE_ROTS[shape]) {
      const offs = SHAPES[shape][r2];
      const minDx = Math.min(...offs.map((o) => o[0])), maxDx = Math.max(...offs.map((o) => o[0]));
      for (let x2 = -minDx; x2 < w - maxDx; x2++) {
        const landed = drop(stack, shape, r2, x2, w, h);
        if (!landed) continue;
        const [cells] = landed;
        const [newStack, lines] = settle(stack, cells, w, h);
        const after = features(newStack, w, h);
        const rots = ((r2 - rot) % 4 + 4) % 4;
        const moves = rots + Math.abs(x2 - x);
        const reachable = moves <= rowsLeft * this.movesPerRow + 1;
        const wellKept = feats.well_col === null || cells.every(([c]) => c !== feats.well_col! - 1) || lines > 0;
        cands.push({ rot: r2, x: x2, cells, lines, holes: after.holes - feats.holes, height: after.max_height, bump: after.bumpiness, wellKept, reachable, score: score(feats, after, lines), rots, dx: x2 - x });
      }
    }
    let reach = cands.filter((c) => c.reachable);
    if (!reach.length) reach = cands;
    reach.sort((a, b) => b.score - a.score);
    this.macros = {}; this.cands = {};
    reach.slice(0, this.topK).forEach((c, i) => {
      const lab = LABELS[i];
      out.landings[lab] = `rot${c.rot} col${c.x + 1}: clears ${c.lines}, holes ${c.holes >= 0 ? "+" : ""}${c.holes}, height ${c.height}, bumpiness ${c.bump}, ${c.wellKept ? "keeps well" : "FILLS the well"}`;
      this.macros[lab] = [...Array(c.rots).fill(this.keys.rotate), ...Array(Math.abs(c.dx)).fill(c.dx < 0 ? this.keys.left : this.keys.right), this.keys.drop];
      c.label = lab; this.cands[lab] = c;
    });
    out.reachable_only = reach.slice(0, this.topK).every((c) => c.reachable);
    out.rows_left = rowsLeft;
    return out;
  }

  predict(label: string): void {
    const c = this.cands[label];
    this.predicted = c ? new Set(c.cells.map(([x, y]) => k(x, y))) : null;
    this.pendingLines = c ? c.lines : 0;
    if (c && this.settled) this.settled = settle(this.settled, c.cells, this.w, this.h)[0];
  }
}
