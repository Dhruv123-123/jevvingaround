// Colour reads: median / accent colour of a region, nearest named colour in Lab. Matches the Python runtime's
// OpenCV conventions (8-bit Lab: L scaled to 0..255, a and b offset by 128) so the packs' max_dist values carry over.
import type { Frame } from "./geometry.js";

export type RGB = [number, number, number];

function lin(c: number): number {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
}

export function rgbToLab(r: number, g: number, b: number): [number, number, number] {
  const R = lin(r), G = lin(g), B = lin(b);
  let x = (0.4124564 * R + 0.3575761 * G + 0.1804375 * B) / 0.95047;
  let y = 0.2126729 * R + 0.7151522 * G + 0.072175 * B;
  let z = (0.0193339 * R + 0.119192 * G + 0.9503041 * B) / 1.08883;
  const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  x = f(x); y = f(y); z = f(z);
  const L = 116 * y - 16, a = 500 * (x - y), bb = 200 * (y - z);
  return [(L * 255) / 100, a + 128, bb + 128];
}

export function hexToRgb(hex: string): RGB {
  const s = hex.replace("#", "");
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
}

export function rgbToHex([r, g, b]: RGB): string {
  return "#" + [r, g, b].map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("");
}

export function labDist(a: [number, number, number], b: [number, number, number]): number {
  return Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]) + Math.abs(a[2] - b[2]);
}

function medianOfHist(h: Uint32Array, n: number): number {
  let acc = 0;
  const half = n / 2;
  for (let i = 0; i < 256; i++) {
    acc += h[i];
    if (acc >= half) return i;
  }
  return 255;
}

/** Per-channel median over the pixels selected by `mask` (or all). O(n) via histograms. */
export function medianColor(f: Frame, mask?: Uint8Array): RGB {
  const hr = new Uint32Array(256), hg = new Uint32Array(256), hb = new Uint32Array(256);
  let n = 0;
  const d = f.data;
  for (let i = 0, p = 0; i < d.length; i += 4, p++) {
    if (mask && !mask[p]) continue;
    hr[d[i]]++; hg[d[i + 1]]++; hb[d[i + 2]]++; n++;
  }
  if (!n) return [0, 0, 0];
  return [medianOfHist(hr, n), medianOfHist(hg, n), medianOfHist(hb, n)];
}

export function meanColor(f: Frame): RGB {
  let r = 0, g = 0, b = 0, n = 0;
  const d = f.data;
  for (let i = 0; i < d.length; i += 4) { r += d[i]; g += d[i + 1]; b += d[i + 2]; n++; }
  return n ? [Math.round(r / n), Math.round(g / n), Math.round(b / n)] : [0, 0, 0];
}

/**
 * The colour of the thing drawn on a flat background: the background is the median of the cell's border band
 * (which a glyph never covers); the accent is the median of the interior pixels that differ from it. Fewer than
 * minShare differing pixels means the cell is empty and the background is returned.
 */
export function accentColor(f: Frame, minShare = 0.03, tol = 40, insetFrac = 0): RGB {
  const { width: w, height: h, data: d } = f;
  const b = Math.max(1, Math.floor(0.08 * Math.min(w, h)));
  const border = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (y < b || y >= h - b || x < b || x >= w - b) border[y * w + x] = 1;
  const bg = medianColor(f, border);
  const labBg = rgbToLab(bg[0], bg[1], bg[2]);
  const m = Math.floor(insetFrac * Math.min(w, h));
  const inner = new Uint8Array(w * h);
  let total = 0, diff = 0;
  for (let y = m; y < h - m; y++) {
    for (let x = m; x < w - m; x++) {
      const p = y * w + x, i = p * 4;
      total++;
      if (labDist(rgbToLab(d[i], d[i + 1], d[i + 2]), labBg) > Math.floor((tol * 3) / 2)) { inner[p] = 1; diff++; }
    }
  }
  if (!total || diff / total < minShare) return bg;
  return medianColor(f, inner);
}

export function nearestNamed(rgb: RGB, options: Record<string, string>): [string, number] {
  const src = rgbToLab(rgb[0], rgb[1], rgb[2]);
  let best = "", bd = 1e9;
  for (const [name, hex] of Object.entries(options)) {
    const [r, g, b] = hexToRgb(hex);
    const dist = labDist(rgbToLab(r, g, b), src);
    if (dist < bd) { best = name; bd = dist; }
  }
  return [best, bd];
}

/** Dominant colours by a coarse quantisation (for the author's palette): hex, share, bbox in px. */
export function palette(f: Frame, k = 14): { hex: string; share: number; bbox_px: [number, number, number, number] }[] {
  const step = 4;
  const bins = new Map<number, { n: number; r: number; g: number; b: number; x0: number; y0: number; x1: number; y1: number }>();
  let total = 0;
  for (let y = 0; y < f.height; y += step) {
    for (let x = 0; x < f.width; x += step) {
      const i = (y * f.width + x) * 4;
      const r = f.data[i], g = f.data[i + 1], b = f.data[i + 2];
      const key = ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4);
      let e = bins.get(key);
      if (!e) { e = { n: 0, r: 0, g: 0, b: 0, x0: x, y0: y, x1: x, y1: y }; bins.set(key, e); }
      e.n++; e.r += r; e.g += g; e.b += b;
      if (x < e.x0) e.x0 = x; if (y < e.y0) e.y0 = y; if (x > e.x1) e.x1 = x; if (y > e.y1) e.y1 = y;
      total++;
    }
  }
  return [...bins.values()]
    .filter((e) => e.n / total >= 0.002)
    .sort((a, b) => b.n - a.n)
    .slice(0, k)
    .map((e) => ({ hex: rgbToHex([e.r / e.n, e.g / e.n, e.b / e.n]), share: Math.round((e.n / total) * 1000) / 1000, bbox_px: [e.x0, e.y0, e.x1 + step, e.y1 + step] as [number, number, number, number] }));
}
