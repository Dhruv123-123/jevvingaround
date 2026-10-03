// The room in front of a runner and how fast it closes. Port of GapTracker in anygame/perceive/__init__.py.
// A grid read is scanned from its first column (the side the mover faces) to the first column holding `symbol` in
// any row. Per frame: the free distance (`cells`, and `px` with `cell_px`), the obstacle's `width_px`, which named
// rows it fills (`rows`: e.g. "low", "chest" or "chest,low"), the closing `speed` in px/s, `ttc_ms` until contact,
// `age_ms` since it became the nearest, and `then_px`/`then_ms` to the obstacle after it. The speed is measured
// over the obstacle's whole approach; until it has been watched for `baseline_s`, the last speed (first `speed0`) stands.
import type { ReadDef } from "./pack.js";

export class GapTracker {
  speed: number | null;
  last: [number, number] | null = null;       // [px, t] of the nearest obstacle on the last frame
  first: [number, number] | null = null;      // [px, t] where that obstacle was first seen

  constructor(public r: ReadDef) { this.speed = r.speed0 !== undefined && r.speed0 !== null ? Number(r.speed0) : null; }

  /** `t` in seconds. */
  read(grid: any, t: number): Record<string, any> | null {
    if (!grid || typeof grid !== "object" || Array.isArray(grid)) return null;
    const sym = String(this.r.symbol);
    const cols = new Map<number, Set<number>>();
    let nrows = 0;
    for (const [k, v] of Object.entries(grid)) {
      const m = /^c(\d+)r(\d+)$/.exec(k);
      if (!m) continue;
      const c = +m[1], rw = +m[2];
      nrows = Math.max(nrows, rw);
      if (!cols.has(c)) cols.set(c, new Set());
      if (String(v) === sym) cols.get(c)!.add(rw);
    }
    const ncols = Math.max(0, ...cols.keys());
    const filled = (c: number) => (cols.get(c)?.size ?? 0) > 0;
    const cell = Number(this.r.cell_px ?? 1);
    const names: string[] = (this.r.row_names ?? Array.from({ length: nrows }, (_, i) => `r${i + 1}`)).map(String);
    let first: number | null = null;
    for (let c = 1; c <= ncols; c++) if (filled(c)) { first = c; break; }
    const free = first ? first - 1 : ncols;
    const out: Record<string, any> = { cells: free, px: Math.round(free * cell), width_px: 0, rows: "none", then_px: null };
    if (first) {
      let w = 0; const hit = new Set<number>();
      const join = Number(this.r.join ?? 1);         // a cactus group or a flapping bird can show 1 empty column inside
      for (let c = first, empty = 0; c <= ncols && empty <= join; c++) {
        if (filled(c)) { cols.get(c)!.forEach((x) => hit.add(x)); w = c - first + 1; empty = 0; } else empty++;
      }
      out.width_px = Math.round(w * cell);
      let nxt2: number | null = null;
      for (let c = first + w + join + 1; c <= ncols; c++) if (filled(c)) { nxt2 = c; break; }
      out.then_px = nxt2 ? Math.round((nxt2 - first) * cell) : null;
      out.rows = [...hit].sort((a, b) => a - b).map((i) => (i - 1 < names.length ? names[i - 1] : `r${i}`)).join(",");
      const px = out.px;
      if (this.first === null || px > this.last![0] + 2 * cell) this.first = [px, t];     // a new obstacle
      else if (t - this.first[1] >= Number(this.r.baseline_s ?? 0.15)) {
        const v = (this.first[0] - px) / (t - this.first[1]);
        const [lo, hi] = (this.r.speed_range ?? [50, 5000]).map(Number);
        if (lo <= v && v <= hi) this.speed = v;
      }
      this.last = [px, t];
    } else this.first = this.last = null;
    out.speed = this.speed ? Math.round(this.speed) : null;
    out.ttc_ms = first && this.speed ? Math.round((out.px / this.speed) * 1000) : null;
    out.age_ms = first && this.first ? Math.round((t - this.first[1]) * 1000) : null;
    out.then_ms = out.then_px !== null && this.speed ? Math.round((out.then_px / this.speed) * 1000) : null;
    return out;
  }
}
