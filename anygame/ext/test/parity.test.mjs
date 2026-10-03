// Loop and compiler features that landed in the Python CLI first: reflex, rule `unless`, plausibility checks, the
// Tetris two-piece lookahead and Go playouts. Each test mirrors the Python test of the same name.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { PNG } from "pngjs";
import yaml from "js-yaml";
import { BUNDLED_PACKS, packFromText, loadPack, dumpPack, Agent, StillDevice, violations, checkPlausible, PackError } from "../dist/core.js";

const PACKS = join(process.cwd(), "..", "packs");
const png = (p) => { const x = PNG.sync.read(readFileSync(p)); return { width: x.width, height: x.height, data: new Uint8ClampedArray(x.data.buffer, x.data.byteOffset, x.data.length) }; };
const probe = (n) => png(join(PACKS, "tictactoe", "fixtures", `probe-${n}.png`));
/** probe-3 (X at c1r2 and c2r2, O at c3r2 and c1r3) with the X at c1r2 painted out: a placed mark vanished. */
function glitch() {
  const f = probe(3); const d = new Uint8ClampedArray(f.data);
  for (let y = 218; y < 385; y++) for (let x = 20; x < 186; x++) { const i = (y * f.width + x) * 4; d[i] = 31; d[i + 1] = 41; d[i + 2] = 55; }
  return { ...f, data: d };
}
/** A sensor that always answers `noul` low and picks by fixed probabilities; counts its calls. */
function fixed(p, choice, latency = 600) {
  return { model: "fixed", calls: 0, async ask(_s, qs) {
    this.calls++;
    const answers = { action: { type: "choice", choice, probabilities: Object.fromEntries(Object.keys(qs.action.criteria).map((c) => [c, p[c] ?? 0])) } };
    for (const [k, q] of Object.entries(qs)) {
      if (k === "action") continue;
      if (q.type === "noul") answers[k] = { type: "noul", noul: 0.1 };
      else if (q.type === "choice") answers[k] = { type: "choice", choice: Object.keys(q.criteria)[0], probabilities: {} };
    }
    return { answers, latency_ms: latency, input_tokens: 10, cost_usd: 0 };
  } };
}
const stateDevice = (states, pack) => { const dev = new StillDevice([{ width: pack.size[0], height: pack.size[1], data: new Uint8ClampedArray(pack.size[0] * pack.size[1] * 4) }], pack.size); let i = 0; dev.state = async () => states[Math.min(i++, states.length - 1)]; return dev; };

// ---- plausibility --------------------------------------------------------------------------------------------
const SPEC = [
  { read: "board", sticky: ["X", "O"] },
  { read: "board", max_changes: 2 },
  { read: "board", count: ["X", "O"], diff: [0, 1] },
  { when: { read: "status", equals: "our_turn" }, read: "board", count: ["X", "O"], diff: [0, 0] },
  { when: { line: "board", symbols: ["X", "O"], length: 3 }, require: { read: "status", in: ["we_won", "we_lost"] } },
];
const READS = { board: { otherwise: "." }, status: {} };

test("plausible: a move that follows passes every check", () => {
  const prev = { board: ["...", ".X.", "O.."], status: "our_turn" };
  const now = { board: ["...", "XXO", "O.."], status: "our_turn" };
  assert.deepEqual(violations(SPEC, now, prev, READS), []);
  assert.deepEqual(violations(SPEC, now, null, READS), []);
});

test("plausible: each kind of impossible reading is named, a cleared board is a restart, the raw grid form is read too", () => {
  const prev = { board: ["...", "XXO", "O.."], status: "our_turn" };
  assert.ok(violations(SPEC, { board: ["...", "OXO", "O.."], status: "our_turn" }, prev, READS).some((v) => v.includes("placed") && v.includes("c1r2 X→O")));
  assert.ok(violations(SPEC, { board: ["XOX", "XXO", "O.."], status: "our_turn" }, prev, READS).some((v) => v.includes("3 cells changed")));
  assert.ok(violations(SPEC, { board: ["...", "XXO", "OO."], status: "our_turn" }, prev, READS).some((v) => v.includes("count(X) - count(O) is -1")));
  assert.deepEqual(violations(SPEC, { board: ["...", "XXX", "OO."], status: "their_turn" }, { board: ["...", "XX.", "OO."] }, READS),
    ["status is 'their_turn' but board has 3 in a line (require status in ['we_won', 'we_lost'])"]);
  assert.deepEqual(violations([SPEC[3]], { board: ["...", "XX.", "O.."], status: "their_turn" }, null, READS), []);
  assert.deepEqual(violations(SPEC.slice(0, 2), { board: ["...", "...", "..."] }, { board: ["XO.", "XXO", "O.X"] }, READS), []);
  const rawPrev = { board: { c1r1: "X", c2r1: ".", c1r2: ".", c2r2: "." } }, rawNow = { board: { c1r1: ".", c2r1: "X", c1r2: ".", c2r2: "." } };
  assert.ok(violations([SPEC[0]], rawNow, rawPrev, READS).some((v) => v.includes("c1r1 X→.")));
});

test("plausible: the loader refuses a malformed check", () => {
  const raw = packFromText(BUNDLED_PACKS.tictactoe, "tictactoe").raw;
  assert.ok(raw.plausible.length);
  for (const [bad, why] of [[{ read: "nope", sticky: ["X"] }, "grid read id"], [{ read: "board", count: ["X", "O"] }, "diff"],
    [{ read: "board", sticky: ["X"], max_changes: 1 }, "exactly one"], [{ require: { read: "status" } }, "condition"]]) {
    assert.throws(() => loadPack(dumpPack({ ...raw, plausible: [bad] }), "ttt"), (e) => e instanceof PackError && e.message.includes(why), why);
  }
  assert.equal(checkPlausible(undefined, {}), null);
});

test("plausible: a wrong read is read again and the fresh frame is acted on", async () => {
  const pack = packFromText(BUNDLED_PACKS.tictactoe, "tictactoe");
  const ag = new Agent(pack, new StillDevice([probe(2), glitch(), probe(3)], pack.size), fixed({ mark: 1 }, "mark"));
  assert.equal(ag.observe(glitch()).values.board[1][0], ".");          // the glitch frame really reads wrong
  const r1 = await ag.step();
  assert.equal(r1.choice, "mark"); assert.equal(r1.implausible, undefined);
  const r2 = await ag.step();
  assert.equal(r2.reread, 1); assert.equal(r2.implausible, undefined);
  assert.deepEqual(r2.screen.board, ["...", "XXO", "O.."]); assert.equal(r2.choice, "mark");
  assert.equal(ag.rereads, 1); assert.equal(ag.implausibleTotal, 0);
});

test("plausible: a wrong read that persists is never acted on and ends the episode; a recording is not read again", async () => {
  const raw = packFromText(BUNDLED_PACKS.tictactoe, "tictactoe").raw;
  const pack = loadPack(dumpPack({ ...raw, plausible_ticks: 2 }), "ttt");
  let taps = 0;
  const dev = new StillDevice([probe(2), glitch()], pack.size); dev.tap = async () => { taps++; };
  const ag = new Agent(pack, dev, fixed({ mark: 1 }, "mark"));
  await ag.step();
  const before = taps;
  const r2 = await ag.step();
  assert.equal(r2.action, "wait"); assert.equal(r2.reason, "implausible read: board: count(X) - count(O) is -1, outside [0, 1]"); assert.equal(r2.reread, 2);
  const r3 = await ag.step();
  assert.equal(r3.action, "stop"); assert.ok(r3.reason.startsWith("stalled: implausible read for 2 ticks"));
  assert.equal(taps, before);
  assert.deepEqual(ag.accepted.board, ["...", ".X.", "O.."]);
  const rec = new StillDevice([probe(2), glitch(), probe(3)], pack.size); rec.rereadable = false;
  const ag2 = new Agent(packFromText(BUNDLED_PACKS.tictactoe, "tictactoe"), rec, fixed({ mark: 1 }, "mark"));
  await ag2.step();
  const r = await ag2.step();
  assert.equal(r.reread, undefined); assert.ok(r.implausible.length); assert.equal(rec.i, 2);
});

// ---- reflex and unless ---------------------------------------------------------------------------------------
test("reflex acts on the last answers when a fresh answer would land too late", async () => {
  const pack = packFromText(BUNDLED_PACKS["snake-state"], "snake-state");
  assert.equal(pack.raw.reflex.read, "head_around.ahead_free");
  // moving right along row 6 until the head is against the right wall (x 11 of 12)
  const states = [0, 1, 2, 3].map((i) => ({ snake: [[8 + i, 6], [7 + i, 6], [6 + i, 6]], food: [1, 1], score: 0, over: false }));
  const P = { keep: 0.6, down: 0.25, up: 0.1, left: 0.03, right: 0.02 };
  const slow = fixed(P, "keep");
  const ag = new Agent(pack, stateDevice(states, pack), slow);
  const recs = []; for (let i = 0; i < 4; i++) recs.push(await ag.step());
  const last = recs[3];
  assert.equal(last.screen.head_around.ahead, "wall");
  assert.equal(last.skipped, "reflex"); assert.ok(last.sensor.includes("reflex")); assert.equal(last.choice, "down");
  assert.equal(slow.calls, recs.filter((r) => r.jev_ms !== undefined && !r.skipped).length); assert.equal(ag.skippedReflex, 2); assert.equal(recs[2].skipped, "reflex");
  // without the reflex the same frame waits on the decider
  delete pack.raw.reflex;
  const ag2 = new Agent(pack, stateDevice(states, pack), fixed(P, "keep"));
  const recs2 = []; for (let i = 0; i < 4; i++) recs2.push(await ag2.step());
  assert.equal(recs2[3].skipped, undefined); assert.equal(ag2.skippedReflex, 0);
});

test("rule unless lets the snake eat food in a corner", async () => {
  const pack = packFromText(BUNDLED_PACKS["snake-state"], "snake-state");
  const P = { keep: 0.6, right: 0.25, up: 0.1, down: 0.03, left: 0.02 };
  const states = [0, 1, 2].map((i) => ({ snake: [[0, 3 - i], [0, 4 - i], [0, 5 - i]], food: [0, 0], score: 0, over: false }));
  const ag = new Agent(pack, stateDevice(states, pack), fixed(P, "keep"));
  const recs = []; for (let i = 0; i < 3; i++) recs.push(await ag.step());
  const last = recs[2];
  assert.equal(last.screen.head_around.ahead, "F"); assert.equal(last.screen.head_around.ahead_free, 1);
  assert.equal(last.choice, "keep"); assert.ok(!last.rules.some((r) => r.includes("ahead_free")));
  const ag2 = new Agent(pack, stateDevice(states.map((s) => ({ ...s, food: [5, 5] })), pack), fixed(P, "keep"));
  const recs2 = []; for (let i = 0; i < 3; i++) recs2.push(await ag2.step());
  assert.equal(recs2[2].choice, "right");
});

test("the loader checks reflex, unless and the shape of rule keys", () => {
  const raw = yaml.load(dumpPack(packFromText(BUNDLED_PACKS["snake-state"], "snake-state").raw));
  const load = (r) => loadPack(dumpPack(r), "s");
  assert.throws(() => load({ ...raw, reflex: { read: "head_around.ahead_free" } }), /reflex needs/);
  assert.throws(() => load({ ...raw, rules: [{ if: { read: "status", equals: "x" }, unless: { read: "status" }, exclude: ["up"] }] }), /unless/);
  assert.throws(() => load({ ...raw, rules: [{ if: { read: "status", equals: "x" }, only: ["up"] }] }), /exclude the others/);
  assert.throws(() => load({ ...raw, rules: [{ if: { read: "status", equals: "x" }, exclude: "up" }] }), /must be a list/);
  load({ ...raw, reflex: [{ read: "head_around.ahead_free", lte: 1 }] });
});

test("when the rules leave one action and the answer never offered it, that action is taken", () => {
  const pack = packFromText(BUNDLED_PACKS["snake-state"], "snake-state");
  pack.rules = [{ if: { read: "status", equals: "playing" }, exclude: pack.actions.map((a) => a.id).filter((id) => id !== "down") }];
  const ag = new Agent(pack, null, null);
  const answers = { action: { type: "choice", choice: "keep", probabilities: { keep: 1 } } };
  const applied = ag.applyRules(answers, { status: "playing" });
  assert.equal(answers.action.choice, "down"); assert.ok(applied.at(-1).includes("only action the rules allow"));
});

// ---- Tetris lookahead ----------------------------------------------------------------------------------------
test("tetris lookahead ranks by two pieces", async () => {
  const { TetrisTracker, lookahead, features } = await import("../dist/core.js");
  // a one-wide well and the next piece unknown (mean over all seven): the O never plugs the well
  const board = Array.from({ length: 20 }, () => ".".repeat(10));
  board[0] = ".OO......."; board[1] = ".OO.......";
  for (let r = 16; r < 20; r++) board[r] = "#########.";
  const v = new TetrisTracker({ in: "board", lookahead: true }).read(board, null);
  assert.equal(v.shape, "O"); assert.equal(Object.keys(v.landings).length, 6);
  assert.ok(v.landings.a.includes("holes +0") && !v.landings.a.includes("col10"), v.landings.a);
  const full = new Set(); for (let c = 0; c < 10; c++) for (let r = 0; r < 20; r++) full.add(`${c},${r}`);
  assert.equal(lookahead(features(full, 10, 20), full, 0, "I", 10, 20), null);
});

test("tetris lookahead gives the Python compiler's ranking on 60 random boards", async () => {
  // test/fixtures/tetris-lookahead.json: boards, previews and the landings perceive/tetris.py ranked with lookahead: true
  const { TetrisTracker } = await import("../dist/core.js");
  const cases = JSON.parse(readFileSync(join(process.cwd(), "test", "fixtures", "tetris-lookahead.json"), "utf8"));
  let changed = 0;
  for (const c of cases) {
    assert.deepEqual(new TetrisTracker({ in: "board", lookahead: true }).read(c.board, c.preview).landings, c.landings);
    if (JSON.stringify(new TetrisTracker({ in: "board" }).read(c.board, c.preview).landings) !== JSON.stringify(c.landings)) changed++;
  }
  assert.ok(changed > cases.length / 2, `lookahead should reorder most boards, reordered ${changed}`);
});
