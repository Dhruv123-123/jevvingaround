// Learning from experience: episodes, incidents, and a revision that must replay better than the incumbent before
// it is accepted. Snake boards are painted with the pack's own colours, so the reads are real.
import { test } from "node:test";
import assert from "node:assert/strict";
import { BUNDLED_PACKS, packFromText, loadPack, dumpPack, outcome, betterEpisode, medianEpisode, answersOf, incidentOf, replay, verifyRevision, improve, incidentDigest, Bank } from "../dist/core.js";
import yaml from "js-yaml";

const W = 540, H = 560;
const hex = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
const fill = (f, x0, y0, x1, y1, rgb) => { for (let y = Math.max(0, y0); y < Math.min(f.height, y1); y++) for (let x = Math.max(0, x0); x < Math.min(f.width, x1); x++) { const i = (y * f.width + x) * 4; f.data[i] = rgb[0]; f.data[i + 1] = rgb[1]; f.data[i + 2] = rgb[2]; f.data[i + 3] = 255; } };

/** A Snake screen: the board cells from a map {c<col>r<row>: symbol}, the status band blue. */
function board(cells) {
  const f = { width: W, height: H, data: new Uint8ClampedArray(W * H * 4) };
  fill(f, 0, 0, W, H, hex("#0b1020"));
  const rect = [0.0352, 0.0857, 0.9648, 0.9821], grid = 12;
  const x0 = rect[0] * W, y0 = rect[1] * H, cw = (rect[2] - rect[0]) * W / grid, rh = (rect[3] - rect[1]) * H / grid;
  const colour = { ".": "#1f2937", s: "#4ade80", H: "#16a34a", F: "#ef4444" };
  for (let r = 1; r <= grid; r++) for (let c = 1; c <= grid; c++) {
    const sym = cells[`c${c}r${r}`] ?? ".";
    fill(f, Math.round(x0 + (c - 1) * cw), Math.round(y0 + (r - 1) * rh), Math.round(x0 + c * cw), Math.round(y0 + r * rh), hex(colour[sym]));
  }
  fill(f, Math.round(0.752 * W), Math.round(0.0125 * H), Math.round(0.974 * W), Math.round(0.059 * H), hex("#3b82f6"));
  return f;
}

const rec = (tick, choice, probs, extra = {}) => ({ tick, hash: "", perception_ms: 1, timings_ms: {}, screen: {}, action: choice, choice, action_probs: probs, nouls: { head_will_hit_something_if_straight: 0.2 }, rules: [], jev_ms: 200, ...extra });

/** Three decisions moving right along row 6; the third is at the right wall and still chooses right. */
function snakeIncident() {
  const frames = [
    board({ c6r6: "H", c5r6: "s", c4r6: "s", c9r6: "F" }),
    board({ c7r6: "H", c6r6: "s", c5r6: "s", c9r6: "F" }),
    board({ c12r6: "H", c11r6: "s", c10r6: "s", c3r3: "F" }),
  ];
  const recs = [rec(10, "right", { right: 0.8, up: 0.1, down: 0.1 }), rec(12, "right", { right: 0.8, up: 0.1, down: 0.1 }), rec(20, "right", { right: 0.6, up: 0.3, down: 0.1 })];
  return incidentOf(frames.map((frame, i) => ({ rec: recs[i], frame })), "status is dead", 21);
}

/** The Snake pack without its guard: no around read, no rules. What a first authored pack often looks like. */
function stripped() {
  const raw = yaml.load(BUNDLED_PACKS.snake);
  delete raw.read.head_around; raw.rules = []; raw.tests = [];
  raw.play = "Snake. Move toward the food.";
  return loadPack(dumpPack(raw), "snake-stripped");
}

test("episodes: outcome, ordering and the median", () => {
  const lostShort = outcome([rec(1, "up", {}), { tick: 2, action: "stop", reason: "status is dead", screen: { score: 30 }, total_cost_usd: 0.001 }], 1, 1, "score");
  const lostLong = outcome(Array.from({ length: 40 }, (_, i) => rec(i + 1, "up", {})).concat([{ tick: 41, action: "stop", reason: "status is dead", screen: { score: 90 } }]), 2, 1, "score");
  const survived = outcome(Array.from({ length: 10 }, (_, i) => rec(i + 1, "up", {})), 3, 2, "score");
  const won = outcome([{ tick: 1, action: "stop", reason: "status is won", screen: {} }], 4, 2);
  assert.equal(lostShort.lost, true); assert.equal(lostShort.score, 30); assert.equal(lostShort.won, false);
  assert.equal(won.won, true); assert.equal(won.lost, false);
  assert.ok(betterEpisode(lostShort, lostLong)); assert.ok(!betterEpisode(lostLong, lostShort));
  assert.ok(betterEpisode(lostLong, survived)); assert.ok(betterEpisode(survived, won));
  assert.equal(medianEpisode([lostShort, lostLong, survived]).n, 2);
  const bank = new Bank(2, 3);
  for (const e of [lostShort, lostLong, survived, won]) bank.addEpisode(e);
  assert.equal(bank.episodes.length, 3); assert.equal(bank.ofVersion(2).length, 2);
});

test("replay: the recorded answers go back through the reads and rules, the guard rule fires at the wall", () => {
  const inc = snakeIncident();
  const full = packFromText(BUNDLED_PACKS.snake, "snake");
  const a = answersOf(inc.decisions[2].rec);
  assert.equal(a.action.choice, "right"); assert.equal(a.head_will_hit_something_if_straight.noul, 0.2);
  const r = replay(full, inc);
  assert.ok(r.support.every((s) => s >= 0.9), `support ${r.support}`);
  assert.equal(r.values[2].head, "c12r6"); assert.equal(r.values[2].head_around.right, "wall"); assert.equal(r.values[2].head_moving, "right");
  assert.deepEqual(r.choices.slice(0, 2), ["right", "right"]);
  assert.notEqual(r.choices[2], "right");
  assert.ok(r.applied[2].some((x) => x.includes("not right")), r.applied[2].join(" | "));
});

test("verify: the guarded revision is accepted, the unchanged, over-blocking and blind ones are rejected", () => {
  const inc = snakeIncident();
  const incumbent = stripped();
  const full = packFromText(BUNDLED_PACKS.snake, "snake");
  const v = verifyRevision(full, incumbent, inc);
  assert.ok(v.ok, v.why); assert.ok(v.guarded); assert.ok(v.distinguished.some((k) => k.startsWith("head_around")), v.distinguished.join(","));
  assert.equal(v.overblocked, 0);
  // the same pack again: nothing learned
  const same = verifyRevision(stripped(), incumbent, inc);
  assert.ok(!same.ok); assert.match(same.why, /neither/);
  // a rule that forbids "right" whenever the game is on: blocks the ordinary decisions too
  const raw = yaml.load(dumpPack(incumbent.raw)); raw.rules = [{ if: { read: "status", equals: "playing" }, exclude: ["right"] }];
  const blunt = verifyRevision(loadPack(dumpPack(raw), "blunt"), incumbent, inc);
  assert.ok(!blunt.ok); assert.match(blunt.why, /blocks 2 of 2/);
  // a revision that repaints the cells' colours cannot read the screens any more
  const raw2 = yaml.load(dumpPack(full.raw)); raw2.read.cells.options = { ".": "#ffffff", s: "#ff00ff", H: "#00ffff", F: "#ffff00" };
  const blind = verifyRevision(loadPack(dumpPack(raw2), "blind"), incumbent, inc);
  assert.ok(!blind.ok); assert.match(blind.why, /reads the incident screens worse/);
  // a revision with no new rule but a new read that separates the fatal tick counts as visible
  const raw3 = yaml.load(dumpPack(incumbent.raw)); raw3.read.head_around = { kind: "around", of: "head", in: "cells", free: [".", "F"] };
  const visible = verifyRevision(loadPack(dumpPack(raw3), "visible"), incumbent, inc);
  assert.ok(visible.ok, visible.why); assert.ok(!visible.guarded); assert.ok(visible.distinguished.includes("head_around.right"));
});

test("improve: the chat model's revision is taken only when it replays better", async () => {
  const inc = snakeIncident();
  const incumbent = stripped();
  const digest = incidentDigest(inc, [outcome([{ tick: 3, action: "stop", reason: "status is dead", screen: {} }], 1, 1)]);
  assert.match(digest, /FATAL tick 20/); assert.match(digest, /EPISODES so far/);
  const asked = [];
  const chatWith = (text) => ({ model: "stub", complete: async (messages) => { asked.push(messages[0].content); return { text, usage: {}, ms: 1 }; } });
  const good = await improve(chatWith("```yaml\n" + BUNDLED_PACKS.snake + "\n```"), incumbent, inc, [], () => {});
  assert.ok(good.pack, good.verdict?.why); assert.ok(good.verdict.ok);
  assert.ok(asked[0].some((p) => p.type === "image_url"), "the fatal frame goes to the model");
  assert.ok(asked[0][0].text.includes("grow the TYPED FRAME"));
  const bad = await improve(chatWith("```yaml\n" + dumpPack(incumbent.raw) + "\n```"), incumbent, inc, [], () => {});
  assert.equal(bad.pack, null); assert.ok(!bad.verdict.ok);
  const none = await improve(chatWith("no yaml here"), incumbent, inc, [], () => {});
  assert.equal(none.pack, null); assert.equal(none.verdict, null);
});
