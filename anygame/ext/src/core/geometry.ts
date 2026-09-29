// Normalized rectangles and grids of named cells. Same naming as the Python runtime: c<col>r<row> (1-based),
// c<n> for a single row, r<n> for a single column.
export interface Rect { x0: number; y0: number; x1: number; y1: number }

export function rectPx(r: Rect, w: number, h: number): [number, number, number, number] {
  return [Math.round(r.x0 * w), Math.round(r.y0 * h), Math.round(r.x1 * w), Math.round(r.y1 * h)];
}

export function center(r: Rect): [number, number] {
  return [(r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2];
}

export class Zone {
  constructor(public name: string, public rect: Rect, public grid: [number, number] | null = null) {}

  cells(): Record<string, Rect> {
    if (!this.grid) return { [this.name]: this.rect };
    const [cols, rows] = this.grid;
    const cw = (this.rect.x1 - this.rect.x0) / cols;
    const rh = (this.rect.y1 - this.rect.y0) / rows;
    const out: Record<string, Rect> = {};
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const key = rows === 1 ? `${this.name}.c${c + 1}` : cols === 1 ? `${this.name}.r${r + 1}` : `${this.name}.c${c + 1}r${r + 1}`;
        out[key] = { x0: this.rect.x0 + c * cw, y0: this.rect.y0 + r * rh, x1: this.rect.x0 + (c + 1) * cw, y1: this.rect.y0 + (r + 1) * rh };
      }
    }
    return out;
  }
}

/** A captured frame: RGBA bytes, like ImageData. */
export interface Frame { width: number; height: number; data: Uint8ClampedArray }

export function crop(f: Frame, r: Rect): Frame {
  const [x0, y0, x1, y1] = rectPx(r, f.width, f.height);
  const w = Math.max(0, x1 - x0), h = Math.max(0, y1 - y0);
  const data = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) {
    const src = ((y0 + y) * f.width + x0) * 4;
    data.set(f.data.subarray(src, src + w * 4), y * w * 4);
  }
  return { width: w, height: h, data };
}

export function inset(f: Frame, frac: number): Frame {
  if (!frac) return f;
  const m = Math.floor(frac * Math.min(f.width, f.height));
  if (m <= 0 || f.width - 2 * m <= 0 || f.height - 2 * m <= 0) return f;
  return crop(f, { x0: m / f.width, y0: m / f.height, x1: (f.width - m) / f.width, y1: (f.height - m) / f.height });
}
