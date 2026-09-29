// The VLM fallback: for a frame the pack does not understand, a vision model returns an action to take now
// and what the screen is. Decisions are memoised by fingerprint, and a mode definition it returns is verified
// against the frame before the loop merges it into the pack, so the same screen is Jev's next time.
import { Chat } from "./chat.js";
import { fingerprint, fpDistance, type Fingerprint } from "./fingerprint.js";
import type { Frame } from "./geometry.js";
import type { Pack } from "./pack.js";
import { frameToDataUrl } from "./author.js";

export interface FallbackAction { action?: string; cell?: string; key?: string; at?: [number, number]; kind?: "key" | "tap" | "wait" }
export interface FallbackDecision {
  now: FallbackAction;                       // what to do this tick
  screen: "transient" | "mode" | "unknown";  // a dismissable overlay / a real game screen / no idea
  name?: string;                             // short mode name, e.g. "menu", "game_over", "level_up"
  mode?: Record<string, any>;                // a mode definition (zones/read/act/play/questions/rules/act_when/stop_when) for this screen
  expect?: Record<string, any>;              // what the mode's reads must return on THIS frame
  note?: string;
  memo?: boolean;                            // came from the memo, no model call
  ms: number;
}

const SYSTEM = `You are the fallback for a game-playing runtime. The fast path plays from a typed "pack" (zones, colour reads,
typed actions); it has hit a screen it cannot read. You see the frame. Answer with ONE JSON object:
{
  "now": {"action": "<one of the pack's action ids>", "cell": "<c<col>r<row> if that action taps a grid>"}   // or
         {"kind": "key", "key": "Enter"} or {"kind": "tap", "at": [x, y]} (pixels on this frame) or {"kind": "wait"},
  "screen": "transient" | "mode" | "unknown",
  "name": "<short snake_case name for this screen>",
  "note": "<one line: what this screen is and why that input>",
  "mode": { ... }           // only for "mode": a definition of how to play THIS screen, same YAML keys as a pack
                            // (zones with rect_px, read with colour options, act, play, questions, rules, act_when, stop_when),
                            // as a JSON object. Read only what matters on this screen. Colours are measured hex values.
  "expect": { "<read id>": <value>, ... }   // for "mode": what the mode's reads must return on this exact frame
}
"transient" is a dialog, overlay or animation that one input dismisses (a start prompt, a game-over card, a
level-up popup): give the input in "now" and no mode. "mode" is a real screen the runtime will see again and
must play (a shop, a map, a battle): give the input for now AND a mode definition. Prefer the pack's own typed
actions when one fits; raw key/tap only when none does. Never invent an action id.`;

export class VLMFallback {
  chat: Chat;
  private memo: { fp: Fingerprint; decision: FallbackDecision }[] = [];
  calls = 0;
  constructor(chat: Chat, public memoThreshold = 25, public maxCalls = 50) { this.chat = chat; }

  recall(fp: Fingerprint): FallbackDecision | null {
    let best: { d: number; decision: FallbackDecision } | null = null;
    for (const m of this.memo) { const d = fpDistance(m.fp, fp); if (!best || d < best.d) best = { d, decision: m.decision }; }
    return best && best.d <= this.memoThreshold ? { ...best.decision, memo: true, ms: 0 } : null;
  }

  remember(fp: Fingerprint, decision: FallbackDecision) { this.memo.push({ fp, decision: { ...decision, mode: undefined, expect: undefined } }); }

  async decide(frame: Frame, pack: Pack, goal: string, recent: string[], palette: any[]): Promise<FallbackDecision> {
    const fp = fingerprint(frame);
    const hit = this.recall(fp);
    if (hit) return hit;
    if (this.calls >= this.maxCalls) return { now: { kind: "wait" }, screen: "unknown", note: "fallback budget spent", ms: 0 };
    this.calls++;
    const actions = pack.actions.map((a) => {
      const z = a.params.zone ? pack.zones[a.params.zone] : null;
      return `${a.id} (${a.kind}${a.params.key ? " " + a.params.key : ""}${a.params.dir ? " " + a.params.dir : ""}${z ? `, zone ${a.params.zone}${z.grid ? ` grid ${z.grid[0]}x${z.grid[1]}` : ""}` : ""})${a.params.description ? ": " + a.params.description : ""}`;
    });
    const t0 = performance.now();
    const { text } = await this.chat.complete([
      { role: "system", content: SYSTEM },
      { role: "user", content: [
        { type: "text", text: `Game: ${pack.name}. Goal: ${goal}\nFrame: ${frame.width}x${frame.height} px. Recent actions: ${JSON.stringify(recent.slice(-6))}\nPack actions:\n${actions.join("\n")}\nDominant colours (hex, share, bbox px): ${JSON.stringify(palette)}\nThe frame, raw then with a 50 px grid:` },
        { type: "image_url", image_url: { url: await frameToDataUrl(frame) } },
        { type: "image_url", image_url: { url: await frameToDataUrl(frame, true) } },
      ] },
    ], 4000, 0);
    const m = /\{[\s\S]*\}/.exec(text);
    let j: any = {};
    try { j = m ? JSON.parse(m[0]) : {}; } catch { j = {}; }
    const decision: FallbackDecision = {
      now: j.now && typeof j.now === "object" ? j.now : { kind: "wait" },
      screen: ["transient", "mode", "unknown"].includes(j.screen) ? j.screen : "unknown",
      name: typeof j.name === "string" ? j.name.replace(/[^a-z0-9_]+/gi, "_").slice(0, 32) : undefined,
      mode: j.mode && typeof j.mode === "object" ? j.mode : undefined,
      expect: j.expect && typeof j.expect === "object" ? j.expect : undefined,
      note: typeof j.note === "string" ? j.note.slice(0, 200) : undefined,
      ms: Math.round(performance.now() - t0),
    };
    if (decision.screen !== "unknown") this.remember(fp, decision);
    return decision;
  }
}
