// The explorer: a vision model plays the game slowly for a while, one input every few seconds with a one-line
// intent, and the result is a demonstration in the same format a human recording produces. Nobody touches the
// game; the demonstration then feeds the author.
import { Chat } from "./chat.js";
import type { Demo, DemoEvent } from "./demo.js";
import type { Frame } from "./geometry.js";
import { sleep, type Device } from "./loop.js";
import { frameToDataUrl } from "./author.js";

const SYSTEM = `You are exploring a game to learn how it is played, one input at a time. Each turn you see the current frame.
Reply with ONE JSON object: {"action": {"kind": "key", "key": "ArrowLeft"} | {"kind": "tap", "at": [x, y]} | {"kind": "wait"},
"intent": "<one short line: what you are trying to do and what you expect to happen>"}.
Keys you may use: ArrowUp ArrowDown ArrowLeft ArrowRight Space Enter Escape and single letters. Taps are pixels on the frame.
Try the obvious controls first, then play to make progress. Say when a screen is a menu, a dialog, a game over, or the game itself.`;

export interface ExploreOptions { device: Device; chat: Chat; seconds: number; game: string; fps?: number; log?: (m: string) => void; shouldStop?: () => boolean }

export async function explore(o: ExploreOptions): Promise<Demo> {
  const frames: Demo["frames"] = [], events: DemoEvent[] = [];
  const t0 = performance.now();
  const messages: any[] = [{ role: "system", content: SYSTEM }];
  const [w, h] = o.device.size();
  let step = 0;
  while (performance.now() - t0 < o.seconds * 1000 && !o.shouldStop?.()) {
    const f: Frame = await o.device.frame();
    const t = performance.now() - t0;
    frames.push({ t, frame: f });
    const content: any[] = [{ type: "text", text: `Game: ${o.game}. Step ${++step}, ${Math.round(t / 1000)}s in, frame ${w}x${h}.` }, { type: "image_url", image_url: { url: await frameToDataUrl(f) } }];
    messages.push({ role: "user", content });
    let j: any = {};
    try {
      const { text } = await o.chat.complete(messages, 300, 0);
      messages.push({ role: "assistant", content: text });
      const m = /\{[\s\S]*\}/.exec(text);
      j = m ? JSON.parse(m[0]) : {};
    } catch (e) { o.log?.(`explore: ${(e as Error).message.slice(0, 100)}`); await sleep(2000); continue; }
    if (messages.length > 14) messages.splice(1, 2);        // keep the last few turns
    const a = j.action ?? {};
    const te = performance.now() - t0;
    if (a.kind === "key" && typeof a.key === "string") { await o.device.key(a.key); events.push({ t: te, type: "key", key: a.key, intent: j.intent }); }
    else if (a.kind === "tap" && Array.isArray(a.at)) { const [x, y] = a.at.map(Number); await o.device.tap(Math.round(x), Math.round(y)); events.push({ t: te, type: "click", x, y, intent: j.intent }); }
    else events.push({ t: te, type: "key", key: "(wait)", intent: j.intent });
    o.log?.(`explore ${step}: ${JSON.stringify(a)} — ${j.intent ?? ""}`);
    await sleep(400);
    frames.push({ t: performance.now() - t0, frame: await o.device.frame() });
  }
  return { frames, events: events.filter((e) => e.key !== "(wait)" || e.intent), source: "explorer" };
}
