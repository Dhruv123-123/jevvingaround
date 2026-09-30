// The state stream in the extension runtime: json / json_grid reads, a device with state(), eval with state files.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { BUNDLED_PACKS, packFromText, getPath, readJson, readJsonGrid, Agent, evalPack, RandomSensor } from "../dist/core.js";

const PACKS = join(process.cwd(), "..", "packs");
const STATE = { snake: [[6, 6], [5, 6], [4, 6]], food: [9, 2], score: 30, over: false, nested: { a: [{ b: "x" }] } };

test("json reads: paths, parse, map, default", () => {
  assert.equal(getPath(STATE, "nested.a.0.b"), "x"); assert.equal(getPath(STATE, "nested.a.9.b"), undefined); assert.equal(getPath(STATE, "snake.0.1"), 6);
  assert.deepEqual(readJson(STATE, { path: "score", parse: "int" }), [30, 1]);
  assert.deepEqual(readJson(STATE, { path: "over", map: { true: "dead", false: "playing" } }), ["playing", 1]);
  assert.deepEqual(readJson(STATE, { path: "missing", default: "playing" }), ["playing", 0]);
  assert.deepEqual(readJson({ over: "true" }, { path: "over", parse: "bool" }), [true, 1]);
});

test("json_grid builds the matrix from coordinates", () => {
  const [grid, conf] = readJsonGrid(STATE, { cols: 12, rows: 12, symbols: { F: { path: "food" }, s: { path: "snake", slice: [1, null] }, H: { path: "snake", index: 0 } } });
  assert.equal(conf, 1); assert.equal(Object.keys(grid).length, 144);
  assert.equal(grid.c7r7, "H"); assert.equal(grid.c6r7, "s"); assert.equal(grid.c10r3, "F"); assert.equal(grid.c1r1, ".");
  const [empty, c0] = readJsonGrid({}, { cols: 3, rows: 2, symbols: { H: { path: "snake" } } });
  assert.equal(c0, 0); assert.ok(Object.values(empty).every((v) => v === "."));
});

test("the state-driven Snake pack: eval on its state fixtures, and a device with state() drives the loop", async () => {
  const pack = packFromText(BUNDLED_PACKS["snake-state"], "snake-state");
  const states = {};
  for (const t of pack.tests) if (t.state) states[t.state] = JSON.parse(readFileSync(join(PACKS, "snake-state", t.state), "utf8"));
  const blank = { width: 540, height: 560, data: new Uint8ClampedArray(540 * 560 * 4) };
  const frames = {}; for (const t of pack.tests) if (t.frame) frames[t.frame] = blank;   // the pixels do not matter here
  const lines = evalPack(pack, frames, states);
  assert.ok(lines.every((l) => l.ok), JSON.stringify(lines.filter((l) => !l.ok)));
  const seq = [{ snake: [[6, 6], [5, 6], [4, 6]], food: [9, 2], score: 0, over: false }, { snake: [[11, 6], [10, 6], [9, 6]], food: [9, 2], score: 0, over: false }];
  let i = 0; const keys = [];
  const dev = { size: () => [540, 560], frame: async () => blank, state: async () => seq[Math.min(i++, seq.length - 1)], tap: async () => {}, swipe: async () => {}, key: async (k) => { keys.push(k); }, close: async () => {} };
  const right = { ask: async (_s, qs) => ({ answers: Object.fromEntries(Object.entries(qs).map(([k, q]) => [k, q.type === "noul" ? { type: "noul", noul: 0.5 } : { type: "choice", choice: "right", probabilities: { right: 0.7, up: 0.2, down: 0.1 } }])), latency_ms: 1, input_tokens: 0, cost_usd: 0 }) };
  const ag = new Agent(pack, dev, right);
  const r1 = await ag.step();
  assert.ok(r1.support >= 0.99); assert.equal(r1.screen.head, "c7r7");
  const r2 = await ag.step();
  assert.equal(r2.screen.head, "c12r7"); assert.equal(r2.screen.head_around.right, "wall");
  assert.ok(r2.rules.some((x) => x.includes("not right")), r2.rules.join(" | "));
  assert.ok(!keys.slice(1).includes("ArrowRight"));
});
