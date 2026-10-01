// Demonstrations: a short log of frames and inputs, from a human ("record me"), from the VLM explorer, or from
// the blind probe. The digest turns it into what the author needs: the action set as used, where clicks land
// (candidate zones), where the screen changes after inputs (where the state lives), before/after pairs.
import type { Frame } from "./geometry.js";

export interface DemoEvent { t: number; type: "key" | "click"; key?: string; x?: number; y?: number; intent?: string }
export interface DemoFrame { t: number; frame: Frame }
export interface Demo { frames: DemoFrame[]; events: DemoEvent[]; notes?: string; source: "human" | "explorer" | "probe" }

export interface ClickCluster { x: number; y: number; n: number; w: number; h: number }
export interface DemoDigest {
  seconds: number;
  keys: Record<string, number>;
  clicks: ClickCluster[];
  changeMap: number[][];                       // 8x8, 0..1: how much each region changed across the demo
  pairs: { event: DemoEvent; before: Frame; after: Frame }[];
  intents: string[];
  chunks: [string[], number][];      // recurring key runs: candidates for a chunk action
  text: string;                                // the summary handed to the author
}

function frameDiff(a: Frame, b: Frame, grid = 8): number[][] {
  const out = Array.from({ length: grid }, () => Array(grid).fill(0));
  const cw = a.width / grid, ch = a.height / grid;
  for (let gy = 0; gy < grid; gy++) for (let gx = 0; gx < grid; gx++) {
    let s = 0, n = 0;
    for (let y = Math.floor(gy * ch); y < Math.floor((gy + 1) * ch); y += 4) for (let x = Math.floor(gx * cw); x < Math.floor((gx + 1) * cw); x += 4) {
      const i = (y * a.width + x) * 4;
      s += Math.abs(a.data[i] - b.data[i]) + Math.abs(a.data[i + 1] - b.data[i + 1]) + Math.abs(a.data[i + 2] - b.data[i + 2]); n++;
    }
    out[gy][gx] = n ? Math.min(1, s / n / 120) : 0;
  }
  return out;
}

export function clusterClicks(events: DemoEvent[], radius = 40): ClickCluster[] {
  const cs: ClickCluster[] = [];
  for (const e of events) {
    if (e.type !== "click" || e.x === undefined || e.y === undefined) continue;
    const c = cs.find((k) => Math.hypot(k.x - e.x!, k.y - e.y!) <= radius);
    if (c) { c.x = (c.x * c.n + e.x) / (c.n + 1); c.y = (c.y * c.n + e.y) / (c.n + 1); c.n++; c.w = Math.max(c.w, Math.abs(e.x - c.x) * 2); c.h = Math.max(c.h, Math.abs(e.y - c.y) * 2); }
    else cs.push({ x: e.x, y: e.y, n: 1, w: 0, h: 0 });
  }
  return cs.sort((a, b) => b.n - a.n).map((c) => ({ ...c, x: Math.round(c.x), y: Math.round(c.y), w: Math.round(c.w), h: Math.round(c.h) }));
}

export function digest(demo: Demo, maxPairs = 6): DemoDigest {
  const keys: Record<string, number> = {};
  for (const e of demo.events) if (e.type === "key" && e.key) keys[e.key] = (keys[e.key] ?? 0) + 1;
  const clicks = clusterClicks(demo.events);
  const change = Array.from({ length: 8 }, () => Array(8).fill(0));
  let nDiff = 0;
  for (let i = 1; i < demo.frames.length; i++) {
    const d = frameDiff(demo.frames[i - 1].frame, demo.frames[i].frame);
    for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) change[y][x] += d[y][x];
    nDiff++;
  }
  const changeMap = change.map((row) => row.map((v) => (nDiff ? Math.round((v / nDiff) * 100) / 100 : 0)));
  const pairs: DemoDigest["pairs"] = [];
  const step = Math.max(1, Math.floor(demo.events.length / maxPairs));
  for (let i = 0; i < demo.events.length && pairs.length < maxPairs; i += step) {
    const e = demo.events[i];
    const before = [...demo.frames].reverse().find((f) => f.t <= e.t);
    const after = demo.frames.find((f) => f.t >= e.t + 150);
    if (before && after && before !== after) pairs.push({ event: e, before: before.frame, after: after.frame });
  }
  const seconds = demo.frames.length ? Math.round((demo.frames[demo.frames.length - 1].t - demo.frames[0].t) / 100) / 10 : 0;
  const intents = demo.events.map((e) => e.intent).filter((x): x is string => !!x);
  const chunks = keyRuns(demo.events);
  const hot = changeMap.flatMap((row, y) => row.map((v, x) => ({ v, x, y }))).filter((c) => c.v > 0.15).sort((a, b) => b.v - a.v).slice(0, 12);
  const text = [
    `DEMONSTRATION (${demo.source}): ${seconds}s, ${demo.frames.length} frames, ${demo.events.length} inputs.`,
    `keys used: ${JSON.stringify(keys)}`,
    `click clusters (px, count): ${JSON.stringify(clicks.slice(0, 12))}`,
    `regions that change most (8x8 grid cells, x then y, 0..1): ${JSON.stringify(hot.map((c) => [c.x, c.y, c.v]))}`,
    intents.length ? `what the player said they were doing: ${JSON.stringify(intents.slice(0, 20))}` : "",
    chunks.length ? `recurring key runs (keys pressed within 600 ms of each other, count; candidates for a chunk action): ${JSON.stringify(chunks)}` : "",
    demo.notes ? `notes: ${demo.notes}` : "",
  ].filter(Boolean).join("\n");
  return { seconds, keys, clicks, changeMap, pairs, intents, chunks, text };
}

/** Key sequences the player repeats: runs of 2 to maxLen keys each within gapMs of the previous one, counted across
 *  the demonstration. A run that recurs is a candidate `chunk` action. Same rule as demo.key_runs. */
export function keyRuns(events: DemoEvent[], gapMs = 600, maxLen = 4, minCount = 2): [string[], number][] {
  const keys = events.filter((e) => e.key && e.key !== "(wait)" && e.t !== undefined).map((e) => [e.t as number, e.key as string] as [number, string]);
  const runs: string[][] = []; let cur: [number, string][] = [];
  for (const [t, k] of keys) { if (cur.length && t - cur[cur.length - 1][0] > gapMs) { runs.push(cur.map((x) => x[1])); cur = []; } cur.push([t, k]); }
  if (cur.length) runs.push(cur.map((x) => x[1]));
  const c = new Map<string, number>();
  for (const r of runs) for (let n = 2; n <= maxLen; n++) for (let i = 0; i + n <= r.length; i++) { const k = JSON.stringify(r.slice(i, i + n)); c.set(k, (c.get(k) ?? 0) + 1); }
  return [...c.entries()].sort((a, b) => b[1] - a[1] || b[0].length - a[0].length).slice(0, 12).map(([k, v]) => [JSON.parse(k) as string[], v] as [string[], number])
    .filter(([k, v]) => (v >= minCount && new Set(k).size > 1) || (v >= minCount && k.length >= 3)).slice(0, 6);
}
