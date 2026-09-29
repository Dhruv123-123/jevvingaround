// `author` inside the extension: probe the tab, hand a vision model the frames (with a pixel grid and the
// measured palette), the pack format and the bundled packs, check its pack against the frames, then play and
// tune. Port of anygame/author.py; the model call goes wherever the LLM settings point (Azure or OpenAI-compatible).
import { Chat } from "./chat.js";
import { palette } from "./color.js";
import type { Frame } from "./geometry.js";
import { Agent, sleep, type Device, type Sensor } from "./loop.js";
import { loadPack, type Pack } from "./pack.js";
import { StillDevice, evalPack } from "./index.js";
import type { Keys } from "./sensors.js";
import { BUNDLED_PACKS } from "../packs.generated.js";

export const FORMAT = `
# Pack format (YAML). Everything the runtime needs to play a game from its screen.
game: <name>
screen: { orientation: portrait, size: [W, H] }          # the frame size the rects below are measured on
zones:                                                    # named rectangles; rect_px is pixels on that frame,
  board: { rect_px: [x0, y0, x1, y1], grid: [cols, rows] }   # rect is normalized 0..1. grid names cells c<col>r<row>
  status: { rect_px: [x0, y0, x1, y1] }                   # (1-based); a 1-row grid names c1..cN, a 1-col grid r1..rN
read:                                                     # each read is one key of the state the model sees
  <id>: { kind: color, zone: <zone>, options: { <label>: "#hex", ... }, max_dist: 60, otherwise: <label>, inset: 0.25, as: matrix, parse: int }
        # nearest named colour of the region's MEDIAN colour (per cell when the zone has a grid). max_dist is
        # Lab distance (40 strict, 90 loose). inset trims the cell border fraction. as: matrix shows a grid
        # as row strings (top row first). parse: int turns labels into numbers. stat: accent reads the colour
        # of whatever is DRAWN on the cell (a glyph, an icon, a piece) instead of the background: use it when
        # the symbols are letters or shapes on a flat cell, with the background colour as the empty option.
  <id>: { kind: bar, zone: <zone>, color: "#hex", scale: 10 }   # fraction of a bar filled with a colour, times scale
  <id>: { kind: locate, in: <grid read id>, symbol: <label>, many: true, row: 1 }   # cell(s) holding a label
  <id>: { kind: runs, in: <grid read id>, symbol: <label>, length: 4, empty: ".", gravity: down, mode: hands }
        # empty cells that would complete \`length\` in a line for \`symbol\`; gravity: down keeps only landing
        # cells; mode: hands = landing cells whose cell above completes the line (drop there and you lose)
  <id>: { kind: around, of: <locate read id>, in: <grid read id>, free: [".", F] }
        # {up,down,left,right,ahead} neighbours plus <dir>_free (open cells that way) and <dir>_space (flood fill)
  <id>: { ..., history: 1 }        # also exposes <id>_prev; for a located cell <id>_moving and <id>_reverse
  <id>: { kind: tetris, in: <board grid read>, next_in: <preview grid read>, empty: ".", top_k: 6, moves_per_row: 3,
          keys: { rotate: ArrowUp, left: ArrowLeft, right: ArrowRight, drop: Space } }
        # falling-block games: the piece, the stack's features, and the reachable landings with computed
        # consequences as options a..f; pair it with a macro action
  # NOT available here: ocr, templates, blobs, vocab. Read numbers and text by colour where you can, or skip them.
act:                                                      # typed actions; the model chooses one per tick
  - { id: <name>, kind: tap, zone: <grid zone>, description: "..." }   # the runtime also asks which cell: <id>__cell
  - { id: <name>, kind: tap, zone: <zone> }                            # tap the zone centre
  - { id: <name>, kind: swipe, zone: <zone>, dir: up|down|left|right, ms: 60 }
  - { id: <name>, kind: key, key: ArrowUp }                            # keyboard
  - { id: place, kind: macro, options: <tetris read id>, key_ms: 40 }   # the runtime asks <id>__option among the read's landings and plays the keys
  - { id: keep, kind: wait, description: "do nothing this tick" }
tick_hz: 4                                                # decisions per second, at most
act_when:  { read: <id>, equals: <value> }                # only act when this holds (our turn)
stop_when: { read: <id>, in: [<value>, ...] }             # end the run
settle: screen_change                                     # after an action wait for the screen to change before deciding again (real-time games)
play: >                                                   # the paragraph: how to play, in terms of the read ids above
  ...
questions:                                                # asked every tick, all in one call; the model sees the reads
  - { id: <belief>, type: noul, instructions: "...?", criteria: { true: "...", false: "..." } }
  - { id: <name>, type: choice, instructions: "...", criteria: { a: "...", b: "..." } }
rules:                                                    # policy the runtime enforces in the same tick
  - { if: { noul: <belief>, gte: 0.6 }, exclude: [<action>, $<read>] }      # $read = that read's value
  - { if: { read: <id>.<path>, in: [s, wall] }, exclude: [<action>] }       # equals|in|not|gte|lte
  - { if: { noul: <belief>, gte: 0.5 }, set: { <action>__cell: <choice question id> } }
  - { if: { read: <id>, equals: our_turn }, avoid: { <action>__cell: <read listing cells> } }   # drop those cells
  - { if: { read: <id>, equals: our_turn }, only:  { <action>__cell: <read listing cells> } }   # offer only those cells
tests:                                                    # required: perception checks on the frames provided
  - { frame: fixtures/probe-1.png, expect: { <read id>: <exact value>, ... } }
`;

export const SYSTEM = `You write anygame packs: a YAML file that lets a fast judgment model (TypeSafe Jev) play a game from
its screen. Jev sees only the compiled reads (labels, numbers, cells), never pixels, and it cannot count or
compare numbers reliably, so anything arithmetic (which cell completes a line, what is next to the head) must
be a derived read (locate, runs, around), and anything fatal must be a rule, not advice.

Write colour reads from the palette hex codes given (they are measured), rects from the pixel grid drawn on
the frames, and tests whose expectations are exactly what the frames show. Prefer colour reads over anything
else. Keep the play paragraph short and in terms of the read ids.
Answer with ONE fenced \`\`\`yaml block containing the whole pack.yaml, then a short note.`;

export function extractYaml(text: string): string | null {
  const m = /```ya?ml\s*\n([\s\S]*?)```/.exec(text);
  return m ? m[1] : null;
}

export async function frameToDataUrl(f: Frame, grid = false): Promise<string> {
  const canvas = new OffscreenCanvas(f.width, f.height);
  const ctx = canvas.getContext("2d")!;
  ctx.putImageData(new ImageData(f.data as any, f.width, f.height), 0, 0);
  if (grid) {
    ctx.strokeStyle = "rgba(255,255,255,0.7)"; ctx.lineWidth = 1; ctx.fillStyle = "#ffff00"; ctx.font = "10px sans-serif";
    for (let x = 0; x < f.width; x += 50) { ctx.beginPath(); ctx.moveTo(x + 0.5, 0); ctx.lineTo(x + 0.5, f.height); ctx.stroke(); ctx.fillText(String(x), x + 2, 10); }
    for (let y = 0; y < f.height; y += 50) { ctx.beginPath(); ctx.moveTo(0, y + 0.5); ctx.lineTo(f.width, y + 0.5); ctx.stroke(); ctx.fillText(String(y), 2, y ? y - 2 : 10); }
  }
  const blob = await canvas.convertToBlob({ type: "image/png" });
  const buf = new Uint8Array(await blob.arrayBuffer());
  let s = "";
  for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  return "data:image/png;base64," + btoa(s);
}

function frameHash(f: Frame): string {
  let h = 0;
  for (let i = 0; i < f.data.length; i += 97) h = (h * 31 + f.data[i]) >>> 0;
  return h.toString(16);
}

/** Frames from a short exploration: the start, then after taps and keys, looking right away and once settled. */
export async function probe(device: Device, n = 6, keys = true, log?: (m: string) => void): Promise<Frame[]> {
  const [w, h] = device.size();
  const frames: Frame[] = [];
  const seen = new Set<string>();
  const keep = async () => { const f = await device.frame(); const k = frameHash(f); if (!seen.has(k) && frames.length < n) { seen.add(k); frames.push(f); } };
  await sleep(500); await keep();
  const taps: [number, number][] = [[w / 2, h / 2], [w / 4, h / 2], [(3 * w) / 4, h / 2], [w / 2, h / 4], [w / 2, (3 * h) / 4], [w / 4, h / 4], [(3 * w) / 4, (3 * h) / 4], [w / 4, (3 * h) / 4], [(3 * w) / 4, h / 4]];
  for (const [x, y] of taps) { if (frames.length >= n) break; await device.tap(Math.round(x), Math.round(y)); await sleep(120); await keep(); await sleep(800); await keep(); }
  if (keys) for (const k of ["ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown", "Space"]) { if (frames.length >= n) break; await device.key(k); await sleep(120); await keep(); await sleep(800); await keep(); }
  log?.(`probed ${frames.length} distinct frames`);
  return frames;
}

export function checkPack(text: string, frames: Record<string, Frame>): { ok: boolean; report: string; pack?: Pack } {
  let pack: Pack;
  try { pack = loadPack(text, "pack"); } catch (e) { return { ok: false, report: `PACK ERROR: ${(e as Error).message}` }; }
  const lines: string[] = [];
  for (const [name, f] of Object.entries(frames)) {
    try {
      const ag = new Agent(pack, new StillDevice([f], pack.size), null);
      const { values } = ag.observe(f);
      lines.push(`${name}: reads → ${JSON.stringify(values).slice(0, 1800)}`);
    } catch (e) { lines.push(`${name}: READ ERROR ${(e as Error).message}`); }
  }
  const res = evalPack(pack, frames);
  for (const l of res) lines.push(l.ok ? `TEST ${l.frame}: ok` : `TEST ${l.frame}: MISMATCH ` + Object.entries(l.misses).map(([k, m]) => `${k}: expected ${JSON.stringify(m.expected)} got ${JSON.stringify(m.got)}`).join("; "));
  return { ok: res.length > 0 && res.every((l) => l.ok), report: lines.join("\n"), pack };
}

export function expectations(text: string): Record<string, Record<string, any>> {
  try { const p = loadPack(text); return Object.fromEntries(p.tests.map((t) => [t.frame, { ...(t.expect ?? {}) }])); } catch { return {}; }
}

export class Author {
  chat: Chat;
  model: string;
  messages: any[] = [{ role: "system", content: SYSTEM }];
  constructor(keys: Keys) { this.chat = new Chat(keys); this.model = this.chat.model; }
  get cost() { return this.chat.cost; }
  async ask(parts: any[]): Promise<string> {
    this.messages.push({ role: "user", content: parts });
    const { text } = await this.chat.complete(this.messages, 12000, 0.2);
    this.messages.push({ role: "assistant", content: text });
    return text;
  }
}

export interface AuthorOptions {
  game: string; play?: string; rounds?: number; framesN?: number; playTicks?: number; tune?: number;
  keys: Keys; sensor: Sensor | null; device: Device; log?: (m: string) => void; onPack?: (yaml: string) => void; shouldStop?: () => boolean;
}

function digest(recs: any[], reason: string | undefined, ticks: number): string {
  const dec = recs.filter((r) => r.jev_ms !== undefined);
  const count = (xs: string[]) => { const c: Record<string, number> = {}; for (const x of xs) c[x] = (c[x] ?? 0) + 1; return c; };
  const lines = [
    `OUTCOME: ${reason ?? `tick cap reached (${ticks} ticks)`}`,
    `ticks ${ticks}, decisions ${dec.length}, screen-unchanged waits ${recs.filter((r) => r.reason === "screen unchanged").length}`,
    `actions taken: ${JSON.stringify(count(dec.map((r) => String(r.action).split(" (")[0])))}`,
    `rules fired: ${JSON.stringify(count(dec.flatMap((r) => (r.rules ?? []).map((x: string) => x.split(" → ")[0]))))}`,
    `final screen: ${JSON.stringify(recs[recs.length - 1]?.screen ?? {}).slice(0, 600)}`,
  ];
  const step = Math.max(1, Math.floor(dec.length / 12));
  for (const r of dec.filter((_, i) => i % step === 0).slice(0, 12)) lines.push(`tick ${r.tick}: screen=${JSON.stringify(r.screen).slice(0, 400)} → ${r.action} probs=${JSON.stringify(r.action_probs)} beliefs=${JSON.stringify(r.nouls)} rules=${JSON.stringify(r.rules)}`);
  return lines.join("\n");
}

/** Returns the final pack YAML (or null) and whether it passes its own tests. */
export async function author(o: AuthorOptions): Promise<{ ok: boolean; yaml: string | null; fixtures: Record<string, Frame> }> {
  const log = o.log ?? (() => {});
  const frames = await probe(o.device, o.framesN ?? 6, true, log);
  const fixtures: Record<string, Frame> = {};
  frames.forEach((f, i) => (fixtures[`fixtures/probe-${i + 1}.png`] = f));
  const [w, h] = o.device.size();
  const au = new Author(o.keys);
  const examples = ["2048", "connect4", "snake"].map((n) => `### example pack: ${n}\n\`\`\`yaml\n${BUNDLED_PACKS[n]}\n\`\`\``).join("\n\n");
  const parts: any[] = [{ type: "text", text:
    `Game: ${o.game}\nFrame size: ${w}x${h} pixels (write rect_px in these pixels).\n${o.play ? `How the user wants it played: ${o.play}\n` : ""}` +
    `\nProbe frames are fixtures/probe-1.png … fixtures/probe-${frames.length}.png, in order: the start screen, then after taps and arrow keys, ` +
    `looking right after each input and once settled. Each is shown twice: raw, then with a 50 px grid.\n` + FORMAT + "\n\n" + examples }];
  for (let i = 0; i < frames.length; i++) {
    parts.push({ type: "text", text: `--- fixtures/probe-${i + 1}.png raw, then with grid. Dominant colours (hex, share, bbox px): ${JSON.stringify(palette(frames[i]))}` });
    parts.push({ type: "image_url", image_url: { url: await frameToDataUrl(frames[i]) } });
    parts.push({ type: "image_url", image_url: { url: await frameToDataUrl(frames[i], true) } });
  }
  parts.push({ type: "text", text: "Write the complete pack.yaml now, with a test for every probe frame." });
  let ok = false, yaml: string | null = null, prevExp: Record<string, Record<string, any>> = {};
  let next: any[] = parts;
  for (let rnd = 1; rnd <= (o.rounds ?? 3); rnd++) {
    if (o.shouldStop?.()) break;
    log(`round ${rnd}: asking ${au.model} …`);
    const text = await au.ask(next);
    const y = extractYaml(text);
    if (!y) { next = [{ type: "text", text: "I could not find a ```yaml block. Send the whole pack.yaml in one fenced yaml block." }]; continue; }
    yaml = y; o.onPack?.(y);
    const res = checkPack(y, fixtures);
    ok = res.ok;
    let report = res.report;
    const curExp = expectations(y);
    if (ok && Object.keys(prevExp).length) {
      const changed: [string, string, any, any][] = [];
      for (const [frame, exp] of Object.entries(curExp)) for (const [read, val] of Object.entries(exp)) {
        const old = prevExp[frame]?.[read];
        if (old !== undefined && JSON.stringify(old) !== JSON.stringify(val)) changed.push([frame, read, old, val]);
      }
      if (changed.length) {
        const vp: any[] = [{ type: "text", text: 'Some test expectations changed between rounds. For each item look at the frame again and answer whether the NEW value is exactly what the frame shows. Reply with one JSON object {"1": true/false, ...} and nothing else.' }];
        for (let i = 0; i < changed.length; i++) {
          const [frame, read, old, val] = changed[i];
          vp.push({ type: "text", text: `${i + 1}. frame ${frame}, read \`${read}\`: previously expected ${JSON.stringify(old)}, now expected ${JSON.stringify(val)}` });
          if (fixtures[frame]) vp.push({ type: "image_url", image_url: { url: await frameToDataUrl(fixtures[frame]) } });
        }
        const vt = await au.ask(vp);
        let verdict: any = {};
        try { const m = /\{[\s\S]*\}/.exec(vt); verdict = m ? JSON.parse(m[0]) : {}; } catch { verdict = {}; }
        const rejected = changed.filter((_, i) => !verdict[String(i + 1)]).map(([frame, read, old, val]) => `${frame}: \`${read}\` now expects ${JSON.stringify(val)} but the frame shows ${JSON.stringify(old)}: the READ is wrong, fix the read and restore the expectation`);
        if (rejected.length) { ok = false; report += "\nEXPECTATIONS CHANGED TO FIT A WRONG READ:\n" + rejected.join("\n"); }
      }
    }
    if (!Object.keys(prevExp).length) prevExp = curExp;
    log(report);
    log(`round ${rnd}: ${ok ? "PASS" : "FAIL"}`);
    if (ok) break;
    next = [{ type: "text", text: "Here is what your pack does on the probe frames. Fix the pack so every test passes: correct colours (use the measured hex values), rects, grid sizes, max_dist, and the expectations themselves only where the read is right and the expectation was wrong. Return the whole corrected pack.yaml in one fenced yaml block.\n\n" + report }];
  }
  if (ok && yaml && o.playTicks && o.sensor) {
    let bestYaml = yaml, best: { reason?: string; ticks: number; won: boolean; lost: boolean } | null = null;
    for (let t = 0; t <= (o.tune ?? 0); t++) {
      if (o.shouldStop?.()) break;
      const pack = loadPack(yaml!);
      const ag = new Agent(pack, o.device, o.sensor, o.playTicks);
      const recs: any[] = []; const shots: Frame[] = [];
      ag.onRecord = (rec, frame) => { recs.push(rec); if (shots.length < 40) shots.push(frame); };
      const last = await ag.run(o.shouldStop);
      const summary = { reason: last.reason, ticks: ag.tick, won: /won/.test(String(last.reason)), lost: /lost|dead|over/.test(String(last.reason)) };
      log(`play ${t}: ${summary.reason ?? "tick cap"} after ${summary.ticks} ticks`);
      const better = !best || (summary.won && !best.won) || (!summary.lost && best.lost) || (summary.lost === best.lost && summary.ticks > best.ticks);
      if (better) { best = summary; bestYaml = yaml!; }
      if (t === (o.tune ?? 0)) break;
      let dg = digest(recs, last.reason, ag.tick);
      if (last.reason && ag.tick <= 3 && /stop_when/.test(yaml!)) dg = `WARNING: stop_when fired after only ${ag.tick} ticks. Almost certainly a read met a state it has no option for (the opponent's turn, an animation) and fell to \`otherwise\`. Look at the last frames below, add the missing options with their colours, and make stop_when match only real end states.\n\n` + dg;
      const tp: any[] = [{ type: "text", text: "The pack passes its perception tests. Here is how it PLAYED. Revise the pack so it plays better: the play paragraph, the questions, the rules (move any counting into derived reads: runs, around, locate; make fatal or wasted moves impossible with exclude/avoid/only rules; add act_when/settle/stop_when if the log shows waits or missed turns). Keep the zones, reads and tests that pass unless the log or the frames show a read is wrong. Return the whole pack.yaml in one fenced yaml block.\n\n" + dg }];
      for (const f of shots.length > 2 ? [shots[Math.floor(shots.length / 2)], shots[shots.length - 1]] : shots) {
        tp.push({ type: "text", text: "frame from the play run (raw, then with the pixel grid):" });
        tp.push({ type: "image_url", image_url: { url: await frameToDataUrl(f) } });
        tp.push({ type: "image_url", image_url: { url: await frameToDataUrl(f, true) } });
      }
      log(`tune ${t + 1}: asking ${au.model} …`);
      let text: string;
      try { text = await au.ask(tp); } catch (e) { log(`tune ${t + 1}: model call failed (${(e as Error).message.slice(0, 120)}); keeping the best pack so far`); break; }
      const y = extractYaml(text);
      if (!y) break;
      const res = checkPack(y, fixtures);
      if (!res.ok) { log("tuned pack broke perception; keeping the previous one\n" + res.report); break; }
      yaml = y; o.onPack?.(y);
    }
    yaml = bestYaml; o.onPack?.(yaml);
  }
  log(`author done (${au.model}${au.cost ? `, $${au.cost.toFixed(4)}` : ""})`);
  return { ok, yaml, fixtures };
}
