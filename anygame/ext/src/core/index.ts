export * from "./geometry.js";
export * from "./color.js";
export * from "./pack.js";
export * from "./reads.js";
export * from "./tetris.js";
export * from "./loop.js";
export * from "./sensors.js";
export * from "./chat.js";
export { BUNDLED_PACKS } from "../packs.generated.js";

/** The runtime's own `eval`: run a pack's tests on decoded fixture frames. Used by the Node tests and the panel. */
import { loadPack, type Pack } from "./pack.js";
import { Agent, type Device } from "./loop.js";
import type { Frame } from "./geometry.js";

export function matches(expected: any, got: any, tol = 0.05): boolean {
  if (expected && typeof expected === "object" && !Array.isArray(expected)) {
    if (!got || typeof got !== "object") return false;
    return Object.entries(expected).every(([k, v]) => matches(v, got[k], tol));
  }
  if (Array.isArray(expected)) return Array.isArray(got) && expected.length === got.length && expected.every((v, i) => matches(v, got[i], tol));
  if (typeof expected === "number" && typeof got === "number") return Math.abs(expected - got) <= (Number.isInteger(expected) ? 0 : tol);
  return String(expected) === String(got);
}

export class StillDevice implements Device {
  constructor(private frames: Frame[], private sz: [number, number]) {}
  i = 0;
  size(): [number, number] { return this.sz; }
  async frame(): Promise<Frame> { return this.frames[Math.min(this.i++, this.frames.length - 1)]; }
  async tap() {}
  async swipe() {}
  async key() {}
  async close() {}
}

export interface EvalLine { frame: string; ok: boolean; misses: Record<string, { expected: any; got: any }>; skipped?: boolean }

export function evalPack(pack: Pack, frames: Record<string, Frame>): EvalLine[] {
  const out: EvalLine[] = [];
  for (const t of pack.tests) {
    const f = frames[t.frame];
    if (!f) { out.push({ frame: t.frame, ok: false, misses: { frame: { expected: "a decoded fixture", got: "missing" } } }); continue; }
    const ag = new Agent(pack, new StillDevice([f], pack.size), null);
    const { values } = ag.observe(f);
    const misses: Record<string, { expected: any; got: any }> = {};
    for (const [k, v] of Object.entries(t.expect)) {
      // reads the extension cannot do (ocr, templates, blobs, vocab) are skipped, not failed
      const kind = pack.reads[k]?.kind;
      if (["ocr", "templates", "blobs", "vocab"].includes(kind)) continue;
      if (!matches(v, values[k])) misses[k] = { expected: v, got: values[k] };
    }
    out.push({ frame: t.frame, ok: !Object.keys(misses).length, misses });
  }
  return out;
}

export function packFromText(text: string, name?: string): Pack { return loadPack(text, name); }
