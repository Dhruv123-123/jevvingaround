// Structural fingerprints: a 16x16 Lab grid of the frame, so "which screen is this" is a nearest-neighbour
// lookup in microseconds, robust to the board's contents changing because the layout dominates.
// Fingerprints serialise to base64 so a pack can carry its modes' fingerprints without any images.
import type { Frame } from "./geometry.js";
import { rgbToLab } from "./color.js";

export const FP_SIDE = 16;
export type Fingerprint = Uint8Array;   // FP_SIDE*FP_SIDE*3 bytes: L, a, b per cell

export function fingerprint(f: Frame): Fingerprint {
  const out = new Uint8Array(FP_SIDE * FP_SIDE * 3);
  const cw = f.width / FP_SIDE, ch = f.height / FP_SIDE;
  for (let gy = 0; gy < FP_SIDE; gy++) {
    for (let gx = 0; gx < FP_SIDE; gx++) {
      const x0 = Math.floor(gx * cw), x1 = Math.max(x0 + 1, Math.floor((gx + 1) * cw));
      const y0 = Math.floor(gy * ch), y1 = Math.max(y0 + 1, Math.floor((gy + 1) * ch));
      let r = 0, g = 0, b = 0, n = 0;
      const sx = Math.max(1, Math.floor((x1 - x0) / 6)), sy = Math.max(1, Math.floor((y1 - y0) / 6));
      for (let y = y0; y < y1; y += sy) for (let x = x0; x < x1; x += sx) { const i = (y * f.width + x) * 4; r += f.data[i]; g += f.data[i + 1]; b += f.data[i + 2]; n++; }
      const [L, a, bb] = rgbToLab(r / n, g / n, b / n);
      const o = (gy * FP_SIDE + gx) * 3;
      out[o] = Math.round(L); out[o + 1] = Math.round(a); out[o + 2] = Math.round(bb);
    }
  }
  return out;
}

/** Mean Lab distance per cell (0 = identical layout; ~20 same screen with different contents; >45 a different screen). */
export function fpDistance(a: Fingerprint, b: Fingerprint): number {
  let s = 0;
  for (let i = 0; i < a.length; i++) s += Math.abs(a[i] - b[i]);
  return s / (a.length / 3);
}

export function fpToBase64(fp: Fingerprint): string {
  let s = "";
  for (let i = 0; i < fp.length; i++) s += String.fromCharCode(fp[i]);
  return btoa(s);
}

export function fpFromBase64(s: string): Fingerprint {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export interface FpMatch { name: string; dist: number }

export class FingerprintIndex {
  private entries: { name: string; fp: Fingerprint }[] = [];
  constructor(public threshold = 40) {}
  add(name: string, fp: Fingerprint | string) { this.entries.push({ name, fp: typeof fp === "string" ? fpFromBase64(fp) : fp }); }
  clear() { this.entries = []; }
  get size() { return this.entries.length; }
  nearest(fp: Fingerprint): FpMatch | null {
    let best: FpMatch | null = null;
    for (const e of this.entries) { const d = fpDistance(e.fp, fp); if (!best || d < best.dist) best = { name: e.name, dist: d }; }
    return best;
  }
  known(fp: Fingerprint): FpMatch | null {
    const n = this.nearest(fp);
    return n && n.dist <= this.threshold ? n : null;
  }
}
