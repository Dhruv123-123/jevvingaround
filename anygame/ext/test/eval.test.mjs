// The TypeScript runtime must see what the Python runtime sees: every bundled pack's fixture tests, decoded with
// pngjs, run through the ported reads and derived reads. OCR/template reads are skipped (not in the extension).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { PNG } from "pngjs";
import { BUNDLED_PACKS, packFromText, evalPack, Agent, StillDevice, RandomSensor, runsOf, aroundOf, goRead, TetrisTracker, accentColor, matches } from "../dist/core.js";

const PACKS = join(process.cwd(), "..", "packs");

function png(path) {
  const p = PNG.sync.read(readFileSync(path));
  return { width: p.width, height: p.height, data: new Uint8ClampedArray(p.data.buffer, p.data.byteOffset, p.data.length) };
}

for (const [name, text] of Object.entries(BUNDLED_PACKS)) {
  test(`pack ${name}: fixture tests pass in the TypeScript runtime`, () => {
    const pack = packFromText(text, name);
    const frames = {}, states = {};
    for (const t of pack.tests) {
      if (t.frame) { const p = join(PACKS, name, t.frame); if (existsSync(p) && p.endsWith(".png")) frames[t.frame] = png(p); }
      if (t.state) { const p = join(PACKS, name, t.state); if (existsSync(p)) states[t.state] = JSON.parse(readFileSync(p, "utf8")); }
    }
    const lines = evalPack(pack, frames, states).filter((l) => frames[l.frame] || states[l.frame]);
    for (const l of lines) assert.ok(l.ok, `${name} ${l.frame}: ${JSON.stringify(l.misses).slice(0, 400)}`);
    assert.ok(lines.length > 0 || pack.tests.every((t) => !(t.frame ?? "").endsWith(".png")), `${name}: no decodable fixtures`);
  });
}

test("runs, around and accent behave like the Python reads", () => {
  const board = {};
  for (let c = 1; c <= 7; c++) for (let r = 1; r <= 6; r++) board[`c${c}r${r}`] = ".";
  Object.assign(board, { c3r6: "Y", c3r5: "Y", c3r4: "Y", c4r6: "R", c5r6: "R", c6r6: "R" });
  assert.deepEqual(runsOf(board, { symbol: "Y", length: 4, gravity: "down" }), ["c3r3"]);
  assert.deepEqual(runsOf(board, { symbol: "R", length: 4, gravity: "down" }), ["c7r6"]);
  const cells = {};
  for (let c = 1; c <= 4; c++) for (let r = 1; r <= 4; r++) cells[`c${c}r${r}`] = ".";
  Object.assign(cells, { c2r2: "H", c2r3: "s", c2r4: "s", c3r2: "F" });
  const a = aroundOf("c2r2", cells, "up", { free: [".", "F"] });
  assert.equal(a.down, "s"); assert.equal(a.right_free, 2); assert.equal(a.ahead_free, 1); assert.equal(a.down_space, 0); assert.equal(a.up_space, 13);
  const w = 166, h = 166, data = new Uint8ClampedArray(w * h * 4);
  for (let i = 0; i < w * h; i++) { data[i * 4] = 31; data[i * 4 + 1] = 41; data[i * 4 + 2] = 55; data[i * 4 + 3] = 255; }
  assert.deepEqual(accentColor({ width: w, height: h, data }, 0.03, 40, 0.25), [31, 41, 55]);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const d = Math.hypot(x - 83, y - 83); if (d > 40 && d < 62) { const i = (y * w + x) * 4; data[i] = 96; data[i + 1] = 165; data[i + 2] = 250; } }
  assert.deepEqual(accentColor({ width: w, height: h, data }, 0.03, 40, 0.25), [96, 165, 250]);
});

test("tetris tracker ranks landings and builds macros", () => {
  const board = Array.from({ length: 20 }, () => ".".repeat(10));
  board[0] = "...T......"; board[1] = "..TTT.....";
  board[18] = "###...####"; board[19] = "####.#####";
  const t = new TetrisTracker({ top_k: 4 });
  const v = t.read(board, null);
  assert.equal(v.phase, "spawned"); assert.equal(v.shape, "T"); assert.equal(v.col, 3); assert.equal(v.stack.max_height, 2);
  assert.ok(v.landings.a.startsWith("rot2 col4: clears 2"));
  assert.deepEqual(t.macros.a, ["ArrowUp", "ArrowUp", "ArrowRight", "Space"]);
  t.predict("a");
  const nxt = Array.from({ length: 20 }, () => ".".repeat(10)); nxt[1] = "...IIII...";
  const v2 = t.read(nxt, null);
  assert.equal(v2.last_placement, "ok"); assert.equal(v2.shape, "I"); assert.equal(v2.lines_cleared, 2);
});

test("the loop plays tic-tac-toe frames with the random sensor and only offers legal cells", async () => {
  const pack = packFromText(BUNDLED_PACKS.tictactoe, "tictactoe");
  const f = png(join(PACKS, "tictactoe", "fixtures", "probe-4.png"));
  const ag = new Agent(pack, new StillDevice([f, f], pack.size), new RandomSensor(3));
  const { values } = ag.observe(f);
  assert.deepEqual(values.board, [".X.", "XXO", "OO."]);
  assert.deepEqual(values.o_wins_at, ["c3r3"]);
  const qs = ag.questions(values);
  assert.deepEqual(Object.keys(qs.mark__cell.criteria).sort(), ["c1r1", "c3r1", "c3r3"]);
  const rec = await ag.step();
  assert.equal(rec.choice, "mark");
  assert.ok(matches({ a: 1 }, { a: 1, b: 2 }) && !matches([1, 2], [1]));
});

test("go read matches the Python compiler", () => {
  const mid = ["BBW......", "B.W......", ".BBW.....", "..W......", ".....B...", "....WW...", "...B.....", "....B...W", ".WBW....B"];
  let v = goRead(mid, { kind: "go", us: "B", them: "W", komi: 6.5 });
  assert.deepEqual(v.saves, ["c3r8", "c8r9"]);
  assert.deepEqual(v.our_atari, ["c3r9", "c9r9"]);
  assert.deepEqual(v.self_atari, ["c1r9"]);
  v = goRead([".........", ".........", "..W......", "....B....", "...BWB...", ".........", "..W......", ".........", "........."], { kind: "go" });
  assert.deepEqual(v.captures, ["c5r6"]);
  assert.deepEqual(v.urgent, ["c5r6"]);
  v = goRead([".B.......", "B........", ...Array(7).fill(".........")], { kind: "go" });
  assert.deepEqual(v.eyes, ["c1r1"]);
  assert.equal(v.score.us, 81);
});

test("go worth ranks the same moves as the Python compiler", () => {
  const mid = ["BBW......", "B.W......", ".BBW.....", "..W......", ".....B...", "....WW...", "...B.....", "....B...W", ".WBW....B"];
  const v = goRead(mid, { kind: "go", komi: 6.5 });
  assert.deepEqual(v.best, ["c6r2", "c7r2", "c7r1", "c5r2", "c8r2", "c5r3"]);
  assert.equal(v.worth.c6r2, 14);
  assert.deepEqual(v.estimate, { us: 21, them: 34.5, lead: -13.5 });
});
