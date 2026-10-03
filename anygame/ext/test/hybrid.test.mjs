// The hybrid: fingerprints, support scores, modes, the VLM fallback (stubbed) merging a verified mode, demonstrations.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { PNG } from "pngjs";
import { BUNDLED_PACKS, packFromText, Agent, StillDevice, RandomSensor, fingerprint, fpDistance, FingerprintIndex, fpToBase64, fpFromBase64,
  VLMFallback, digest, clusterClicks, dumpPack, loadPack } from "../dist/core.js";

const PACKS = join(process.cwd(), "..", "packs");
const png = (p) => { const x = PNG.sync.read(readFileSync(p)); return { width: x.width, height: x.height, data: new Uint8ClampedArray(x.data.buffer, x.data.byteOffset, x.data.length) }; };
const blank = (w, h, rgb = [17, 24, 39]) => { const d = new Uint8ClampedArray(w * h * 4); for (let i = 0; i < w * h; i++) { d[i * 4] = rgb[0]; d[i * 4 + 1] = rgb[1]; d[i * 4 + 2] = rgb[2]; d[i * 4 + 3] = 255; } return { width: w, height: h, data: d }; };

test("fingerprints: same screen with different contents is near, a different screen is far, base64 round-trips", () => {
  const a = png(join(PACKS, "tictactoe", "fixtures", "probe-1.png")), b = png(join(PACKS, "tictactoe", "fixtures", "probe-4.png"));
  const c = png(join(PACKS, "connect4", "fixtures", "start.png"));
  const fa = fingerprint(a), fb = fingerprint(b), fc = fingerprint(c);
  assert.ok(fpDistance(fa, fb) < 25, `same layout should be near: ${fpDistance(fa, fb)}`);
  assert.ok(fpDistance(fa, fc) > 40, `different game should be far: ${fpDistance(fa, fc)}`);
  assert.deepEqual([...fpFromBase64(fpToBase64(fa))], [...fa]);
  const idx = new FingerprintIndex(40);
  idx.add("main", fa);
  assert.equal(idx.known(fb)?.name, "main");
  assert.equal(idx.known(fc), null);
});

test("support: the pack's own screen scores high, a blank screen scores low and counts as a miss", async () => {
  const pack = packFromText(BUNDLED_PACKS.tictactoe, "tictactoe");
  const good = png(join(PACKS, "tictactoe", "fixtures", "probe-2.png"));
  const ag = new Agent(pack, new StillDevice([good, blank(540, 560, [200, 30, 200])], pack.size), new RandomSensor(1));
  const r1 = await ag.step();
  assert.ok(r1.support >= 0.9, `support on the real screen: ${r1.support}`);
  assert.equal(r1.mode, "main");
  const r2 = await ag.step();
  assert.ok(r2.support < 0.5, `support on a magenta screen: ${r2.support}`);
  assert.equal(r2.known, null);
});

test("modes: a read condition picks the mode, the mode's own actions and reads apply, and modes survive a dump/load round trip", async () => {
  const raw = `
game: modal
screen: { size: [100, 100] }
zones:
  status: { rect: [0, 0, 1, 0.1] }
read:
  status: { kind: color, zone: status, options: { play: "#111827", menu: "#c81ec8" }, max_dist: 60, otherwise: play }
act:
  - { id: go, kind: key, key: ArrowRight }
play: main screen
modes:
  menu:
    when: { read: status, equals: menu }
    act:
      - { id: start, kind: key, key: Enter }
    play: press start
    stop_when: null
tests: []
`;
  const pack = loadPack(raw, "modal");
  assert.deepEqual(Object.keys(pack.modes), ["menu"]);
  assert.equal(pack.modes.menu.actions[0].id, "start");
  const round = loadPack(dumpPack(pack.raw), "modal2");
  assert.equal(round.modes.menu.play, "press start");
  const keys = [];
  const dev = new StillDevice([blank(100, 100, [200, 30, 200]), blank(100, 100, [17, 24, 39])], [100, 100]);
  dev.key = async (k) => { keys.push(k); };
  const ag = new Agent(pack, dev, new RandomSensor(1));
  const r1 = await ag.step();
  assert.equal(r1.mode, "menu"); assert.equal(r1.known, "menu"); assert.equal(keys[0], "Enter");
  const r2 = await ag.step();
  assert.equal(r2.mode, "main"); assert.equal(keys[1], "ArrowRight");
});

test("fallback: an unsupported screen goes to the (stubbed) VLM, its transient input is replayed from the memo, and a verified mode is merged", async () => {
  const pack = packFromText(BUNDLED_PACKS.tictactoe, "tictactoe");
  const good = png(join(PACKS, "tictactoe", "fixtures", "probe-2.png"));
  const magenta = blank(540, 560, [200, 30, 200]);
  const keys = [];
  const dev = new StillDevice([magenta, magenta, magenta, good], pack.size);
  dev.key = async (k) => { keys.push(k); };
  const ag = new Agent(pack, dev, new RandomSensor(1));
  const calls = [];
  const fakeChat = { model: "stub", cost: 0, complete: async (messages) => { calls.push(messages); return { text: JSON.stringify({ now: { kind: "key", key: "Enter" }, screen: "transient", name: "start_prompt", note: "a magenta start card" }), usage: {}, ms: 1 }; } };
  ag.fallback = new VLMFallback(fakeChat);
  const changes = [];
  ag.onPackChange = (y, why) => changes.push(why);
  const r1 = await ag.step();                       // miss 1: wait
  assert.equal(r1.action, "wait"); assert.match(r1.reason, /unsupported/);
  const r2 = await ag.step();                       // miss 2: the VLM decides
  assert.equal(calls.length, 1); assert.equal(keys[0], "Enter"); assert.match(r2.fallback, /^vlm transient start_prompt/);
  assert.ok(changes.some((c) => c.includes("learned transient screen start_prompt")));
  const r3 = await ag.step();                       // same screen again: memo, no model call
  assert.equal(calls.length, 1); assert.equal(keys[1], "Enter"); assert.match(r3.fallback, /^memo/);
  const r4 = await ag.step();                       // the real game: supported, Jev (random) plays
  assert.equal(r4.mode, "main"); assert.ok(r4.support >= 0.9); assert.equal(r4.choice, "mark");

  // a mode definition that reads this frame correctly is merged; one that lies about the frame is rejected
  const ag2 = new Agent(packFromText(BUNDLED_PACKS.tictactoe, "tictactoe"), new StillDevice([magenta], pack.size), null);
  const log = [];
  ag2.onPackChange = (y, why) => log.push(why);
  const goodMode = { zones: { banner: { rect_px: [0, 0, 540, 560] } }, read: { banner: { kind: "color", zone: "banner", options: { magenta: "#c81ec8", other: "#111827" }, max_dist: 60, otherwise: "other" } }, act: [{ id: "dismiss", kind: "key", key: "Enter" }], play: "press dismiss", questions: [], rules: [], stop_when: null, act_when: null };
  assert.equal(ag2.mergeMode("red_card", goodMode, { banner: "magenta" }, magenta, fingerprint(magenta)), true);
  assert.ok(Object.keys(ag2.base.modes).includes("red_card") && log.some((w) => w === "learned mode red_card"));
  assert.equal(ag2.mergeMode("liar", goodMode, { banner: "other" }, magenta, fingerprint(magenta)), false);
  assert.ok(log.some((w) => w.startsWith("mode liar rejected")));
});

test("demonstrations: clicks cluster into candidate zones and the digest names keys, hot regions and intents", () => {
  const f1 = blank(200, 200), f2 = blank(200, 200); for (let y = 100; y < 150; y++) for (let x = 0; x < 200; x++) { const i = (y * 200 + x) * 4; f2.data[i] = 255; }
  const demo = { source: "human", frames: [{ t: 0, frame: f1 }, { t: 300, frame: f2 }, { t: 600, frame: f1 }],
    events: [{ t: 100, type: "click", x: 50, y: 50 }, { t: 400, type: "click", x: 55, y: 48, intent: "take the centre" }, { t: 500, type: "key", key: "ArrowLeft" }, { t: 550, type: "key", key: "ArrowLeft" }] };
  const cl = clusterClicks(demo.events);
  assert.equal(cl.length, 1); assert.equal(cl[0].n, 2);
  const d = digest(demo);
  assert.equal(d.keys.ArrowLeft, 2); assert.ok(d.pairs.length >= 1); assert.deepEqual(d.intents, ["take the centre"]);
  assert.ok(d.changeMap[4].some((v) => v > 0.15) && d.text.includes("DEMONSTRATION (human)"));
});

test("chat: no chat model configured stops, and OpenRouter is refused for any chat model", async () => {
  const { Chat } = await import("../dist/core.js");
  assert.throws(() => new Chat({ openrouter: "sk-or-x" }), /no chat model configured/);
  assert.throws(() => new Chat({ openrouter: "sk-or-x", llmBase: "https://openrouter.ai/api/v1" }), /authoring model/);
  for (const m of ["anthropic/claude-sonnet-5", "openai/gpt-5.6-luna"]) assert.throws(() => new Chat({ llmBase: "https://openrouter.ai/api/v1", llmKey: "k", llmModel: m }), /Jev only/);
  assert.equal(new Chat({ llmBase: "https://r.openai.azure.com/openai/v1", llmKey: "k", llmModel: "gpt-5.6-luna" }).api, "azure");
});

test("a count read and a list act_when: the agent waits while the marks say it is not its turn", async () => {
  const { countOf } = await import("../dist/core.js");
  assert.equal(countOf({ c1r1: "X", c2r1: "O", c3r1: "X" }, { symbol: "X", minus: "O" }), 1);
  assert.equal(countOf(["X..", ".O.", "..O"], { symbol: "O" }), 2);
  const base = packFromText(BUNDLED_PACKS.tictactoe, "tictactoe");
  const raw = JSON.parse(JSON.stringify(base.raw));
  const grid = Object.keys(raw.read).find((k) => raw.read[k].kind === "color" && raw.read[k].as === "matrix");
  raw.read.turn = { kind: "count", in: grid, symbol: "X", minus: "O" };
  raw.act_when = [{ read: "turn", gte: -5 }, { read: "turn", equals: 1 }];   // the fixture has four X and four O: turn 0
  raw.tests = [];
  const pack = loadPack(dumpPack(raw), "ttt-turn");
  const ag = new Agent(pack, new StillDevice([png(join(PACKS, "tictactoe", "fixtures", "probe-4.png"))], pack.size), new RandomSensor(1));
  const r = await ag.step();
  assert.equal(r.screen.turn, 0); assert.equal(r.action, "wait"); assert.equal(r.reason, "turn is 0");
});
