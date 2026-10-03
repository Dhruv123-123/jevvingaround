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

test("the calibrator learns from the trial record; lessons and hints; the bank keeps the record", async () => {
  const { Calibrator, revisionFeatures, lessonsOf, hintsText, Bank, verifyRevision } = await import("../dist/core.js");
  const hist = [];
  for (let k = 0; k < 5; k++) {
    hist.push({ version: k, features: { guarded: 1, distinguished: 0, overblocked: 0.25 + 0.02 * k, support: 1, rules_added: 1, reads_added: 0, questions_added: 0, play_changed: 0 }, kept: false, at: "" });
    hist.push({ version: 10 + k, features: { guarded: 1, distinguished: 1, overblocked: 0, support: 1, rules_added: 1, reads_added: 1, questions_added: 0, play_changed: 0 }, kept: true, at: "" });
  }
  assert.ok(!new Calibrator(hist.slice(0, 3)).active);
  const cal = new Calibrator(hist);
  assert.ok(cal.active);
  const loose = { ...hist[0].features, overblocked: 0.3 }, tight = { ...hist[1].features };
  assert.ok(cal.pKeep(tight) > 0.6 && cal.pKeep(loose) < 0.35, `${cal.pKeep(tight)} ${cal.pKeep(loose)}`);
  assert.ok(cal.judge(tight)[0] && !cal.judge(loose)[0]);
  const inc = snakeIncident(); const incumbent = stripped(); const fullPack = packFromText(BUNDLED_PACKS.snake, "snake");
  const v = verifyRevision(fullPack, incumbent, inc);
  const f = revisionFeatures(v, fullPack, incumbent);
  assert.equal(f.guarded, 1); assert.ok(f.rules_added >= 10); assert.equal(f.reads_added, 1); assert.equal(f.play_changed, 1);
  const ls = lessonsOf(fullPack, incumbent, "status is dead");
  assert.ok(ls.some((l) => l.kind === "rule") && ls.some((l) => l.kind === "read" && l.yaml.includes("head_around")));
  const txt = hintsText(ls, new Set(["color", "locate", "around"]));
  assert.match(txt, /PATTERNS THAT SURVIVED/); assert.ok(txt.includes("around"));
  assert.ok(!hintsText(ls, new Set(["bar", "ocr"])).includes('"kind":"around"'));
  assert.equal(hintsText([]), "");
  const bank = new Bank();
  bank.addRevision(2, f, "rule now excludes right");
  assert.equal(bank.revisions[0].kept, null); assert.ok(!bank.calibrator().active);
  const fresh = bank.recordTrial(2, true, fullPack, incumbent, "status is dead");
  assert.equal(bank.revisions[0].kept, true); assert.ok(fresh.length >= 2 && bank.lessons.length === fresh.length);
});

test("counterfactual return: identical owns the loss, guarded leaves it, an earlier turn truncates the walk", async () => {
  const { counterfactual, counterfactualSummary, loggedPolicy } = await import("../dist/core.js");
  const inc = snakeIncident();
  const lp = loggedPolicy(rec(5, "left", { right: 0.5, left: 0.3, up: 0.2 }, { rules: ["head_around.right=wall → not right", "→ left"] }));
  assert.ok(!("right" in lp) && Math.abs(lp.left - 0.6) < 1e-9);
  const same = [{ right: 0.8, up: 0.1, down: 0.1 }, { right: 0.8, up: 0.1, down: 0.1 }, { right: 0.6, up: 0.3, down: 0.1 }];
  const c1 = counterfactual(inc, same); assert.ok(c1.lost && c1.diverged_at === null && Math.abs(c1.loss_weight - 1) < 1e-6);
  const c2 = counterfactual(inc, same.slice(0, 2).concat([{ up: 0.75, down: 0.25 }])); assert.equal(c2.loss_weight, 0); assert.ok(c2.reached_end);
  const c3 = counterfactual(inc, [same[0], { up: 0.9, right: 0.02, down: 0.08 }, same[2]]); assert.equal(c3.diverged_at, 12); assert.equal(c3.loss_weight, 0); assert.equal(c3.ratios.length, 2);
  assert.equal(counterfactual(inc, [{ right: 1 }, { right: 1 }, { right: 1 }], 2).loss_weight, 2);
  assert.equal(counterfactual(inc, [null, null, null]).loss_weight, 1);
  const s = counterfactualSummary([c1, c2, c3]);
  assert.equal(s.n, 3); assert.equal(s.incumbent_loss, 1); assert.ok(Math.abs(s.candidate_loss - 1 / 3) < 1e-3); assert.equal(s.walks_into, 1); assert.equal(s.diverged, 1); assert.equal(s.ess, 1);
});

test("re-ask, holdout, order A/B and the gates against a scripted sensor; an order-only revision needs a sensor", async () => {
  const { reask, holdoutCheck, auditOrder, actionOrders, orderText, counterfactualReturn, Bank, verifyRevision, revisionFeatures, Calibrator } = await import("../dist/core.js");
  // a sensor that always wants the first option listed (pure position bias), 0.7 on it
  const first = { model: "first", async ask(_s, qs) { const a = {}; for (const [k, q] of Object.entries(qs)) { if (q.type === "noul") a[k] = { type: "noul", noul: 0.5 }; else if (q.type === "choice") { const c = Object.keys(q.criteria); a[k] = { type: "choice", choice: c[0], probabilities: Object.fromEntries(c.map((x, i) => [x, i ? 0.3 / (c.length - 1) : 0.7])) }; } } return { answers: a, latency_ms: 10, input_tokens: 1, cost_usd: 0.00001 }; } };
  const inc = snakeIncident(); const fullPack = packFromText(BUNDLED_PACKS.snake, "snake");
  const r = await reask(first, fullPack, inc.decisions);
  assert.equal(r.raw.length, 3); assert.ok(r.raw.every((x) => x === "up")); assert.ok(r.probs.every((p) => Math.abs(Object.values(p).reduce((a, b) => a + b, 0) - 1) < 1e-9));
  const bank = new Bank(); bank.addHoldout(inc.decisions.slice(0, 2), 3); bank.addHoldout(inc.decisions.slice(0, 2), 3);
  assert.equal(bank.holdout.length, 3); assert.equal(bank.holdout[2].rec.tick, 12);
  const h = await holdoutCheck(first, fullPack, bank.holdout); assert.equal(h.n, 3); assert.ok(h.agreement >= 0 && h.agreement <= 1);
  assert.equal((await holdoutCheck(first, fullPack, [])).n, 0);
  const orders = actionOrders(fullPack); assert.equal(orders.length, 4);
  const res = await auditOrder(first, fullPack, inc.decisions, () => {}, undefined, new Set([20]));
  assert.equal(res.length, 4); assert.ok(res.every((o) => o.first_pick === 1 && o.n === 3 && o.fatal_repeated !== null));
  // listing 'right' first makes the biased decider pick the excluded move at the wall: that order sorts last
  const rightFirst = res.find((o) => o.order[0] === "right"); if (rightFirst) assert.ok(rightFirst.unsafe > 0 && res[res.length - 1].unsafe >= rightFirst.unsafe);
  assert.equal(typeof orderText(res), "string");
  const cf = await counterfactualReturn(first, fullPack, [inc, incidentOf(inc.decisions, "status is dead", 40)], () => {}, { 0: [{ right: 1 }, { right: 1 }, { right: 1 }] });
  assert.equal(cf.n, 2); assert.ok(cf.per_incident[0].loss_weight >= 1); assert.ok(cf.cost_usd > 0);
  // an order-only revision: rejected by replay alone, accepted for re-query when a sensor will judge it
  const raw = yaml.load(dumpPack(fullPack.raw)); raw.act = [...raw.act].reverse();
  const reordered = packFromText(dumpPack(raw), "snake");
  assert.ok(!verifyRevision(reordered, fullPack, inc).ok);
  const v = verifyRevision(reordered, fullPack, inc, 0.7, 0.34, [], true); assert.ok(v.ok && v.order_changed && !v.guarded);
  assert.equal(revisionFeatures(v, reordered, fullPack).order_changed, 1); assert.equal(revisionFeatures(v, fullPack, fullPack).order_changed, 0);
  // the conformal floor: five kept and five reverted rows; the floor is the smallest leave-one-out score among the kept (capped at 0.9)
  const good = (i) => ({ guarded: 1, distinguished: 2, overblocked: 0, support: 1, rules_added: 1, reads_added: 1, requery_avoided: 1, requery_agreement: 0.9, holdout_agreement: 0.9 - i * 0.01 });
  const bad = (i) => ({ guarded: 0, distinguished: 0, overblocked: 0.3 + i * 0.02, support: 0.8, rules_added: 3, reads_added: 0, requery_avoided: 0, requery_agreement: 0.5, holdout_agreement: 0.5 });
  const rows = [...[0, 1, 2, 3, 4].map((i) => ({ version: i, features: good(i), kept: true, at: "" })), ...[0, 1, 2, 3, 4].map((i) => ({ version: 10 + i, features: bad(i), kept: false, at: "" }))];
  const c = new Calibrator(rows);
  assert.ok(c.active && c.conformal !== null && c.nKept === 5 && c.floor > 0 && c.floor <= 0.9);
  assert.ok(c.judge(good(9))[0] && c.judge(good(9))[1].includes("conformal floor")); assert.ok(!c.judge(bad(9))[0]);
  const c2 = new Calibrator([...rows.slice(0, 2), ...rows.slice(5)]);
  assert.ok(c2.active && c2.floor === 0 && c2.judge(bad(9))[0] && c2.judge(bad(9))[1].includes("no floor yet"));
  assert.equal(new Calibrator(rows, 6, 0.35, null).floor, 0.35);
});

test("margin read and the per-tick budget", async () => {
  const { marginOf, marginNum, Agent, StillDevice } = await import("../dist/core.js");
  const cells = {}; for (let c = 1; c <= 6; c++) for (let r = 1; r <= 6; r++) cells[`c${c}r${r}`] = ".";
  for (const k of ["c1r2", "c2r2", "c3r2", "c3r1"]) cells[k] = "s";
  cells.c2r1 = "H";
  const m = marginOf("c2r1", cells, { free: [".", "F"], lag: 0 });
  assert.equal(m.left, 1); assert.equal(m.right, 0); assert.equal(m.now, 1); assert.deepEqual(m.safe, ["left"]); assert.equal(m.best, "left");
  const open = {}; for (let c = 1; c <= 6; c++) for (let r = 1; r <= 6; r++) open[`c${c}r${r}`] = "."; open.c3r3 = "H";
  const m2 = marginOf("c3r3", open, { free: ["."], lag: 1 });
  assert.equal(m2.now, 35); assert.equal(m2.right, 34); assert.ok(m2.right_ok); assert.equal(m2.safe.length, 4);
  const m3 = marginOf("c3r3", open, { free: ["."], lag: 2 }); assert.equal(m3.up, 0); assert.ok(!m3.up_ok && m3.down > 0);
  assert.equal(marginOf(null, open, {}), null); assert.equal(marginNum(7, { lower: 0, upper: 10 }), 3); assert.equal(marginNum("x", { lower: 0 }), null);
  // in a pack: a rule on the margin excludes the move into the wall at replay time
  const { replay } = await import("../dist/core.js");
  const raw = yaml.load(dumpPack(packFromText(BUNDLED_PACKS.snake, "snake").raw));
  raw.read.room = { kind: "margin", of: "head", in: "cells", free: [".", "F"], lag: 1 }; raw.rules.push({ if: { read: "room.right_ok", equals: false }, exclude: ["right"] });
  const r = replay(packFromText(dumpPack(raw), "snake"), snakeIncident());
  assert.equal(r.values[2].room.right, 0); assert.notEqual(r.choices[2], "right");
  assert.throws(() => { const bad = yaml.load(dumpPack(raw)); bad.read.bad = { kind: "margin", of: "head" }; packFromText(dumpPack(bad), "x"); });
  // the budget: a sensor that reports 500 ms is skipped when perception + expected latency exceeds budget_ms, at most budget_skip_max in a row
  let calls = 0;
  const slow = { model: "slow", async ask(_s, qs) { calls++; const c = Object.keys(qs.action.criteria); return { answers: { action: { type: "choice", choice: "right", probabilities: Object.fromEntries(c.map((x) => [x, x === "right" ? 0.9 : 0.1 / (c.length - 1)])) } }, latency_ms: 500, input_tokens: 1, cost_usd: 0 }; } };
  const pack = packFromText(BUNDLED_PACKS["snake-state"], "snake-state"); pack.raw.budget_ms = 100; pack.raw.budget_skip_max = 2;
  const states = [0, 1, 2, 3, 4, 5].map((i) => ({ snake: [[3 + i, 6], [2 + i, 6], [1 + i, 6]], food: [9, 2], score: 0, over: false }));
  const dev = new StillDevice([{ width: W, height: H, data: new Uint8ClampedArray(W * H * 4) }], [W, H]); let si = 0; dev.state = async () => states[Math.min(si++, 5)];
  const ag = new Agent(pack, dev, slow);
  const recs = []; for (let i = 0; i < 6; i++) recs.push(await ag.step());
  assert.equal(calls, 2); assert.deepEqual(recs.map((r) => r.skipped === "budget"), [false, true, true, false, true, true]); assert.equal(ag.skippedBudget, 4);
  assert.ok(recs.every((r) => r.choice) && recs.filter((r) => r.skipped).every((r) => r.sensor.includes("rules on last answers")));
});

test("tasks: the pack validates them, the loop tracks them, successes are kept allowed, the setter validates proposals", async () => {
  const { checkTasks, Agent, StillDevice, RandomSensor, outcome, betterEpisode, Bank, taskStats, chooseOrder, tasksText, verifyRevision, proposeTasks } = await import("../dist/core.js");
  const reads = { score: { kind: "json", path: "score" }, head: { kind: "locate", in: "x", symbol: "H" } };
  const t = checkTasks([{ id: "ten", instruction: "reach 10", done: { read: "score", gte: 10 } }], reads)[0];
  assert.deepEqual(t.done, [{ read: "score", gte: 10 }]); assert.equal(t.limit_ticks, 150); assert.equal(t.category, "other");
  assert.throws(() => checkTasks([{ id: "x", instruction: "?", done: { read: "nope", equals: 1 } }], reads));
  assert.throws(() => checkTasks([{ id: "x", instruction: "?" }], reads));
  const raw = yaml.load(BUNDLED_PACKS["snake-state"]);
  raw.tasks = [{ id: "score_ten", instruction: "eat until the score reaches 10", done: { read: "score", gte: 10 }, category: "score", limit_ticks: 20 },
               { id: "go_right", instruction: "move the head to column 12", done: { read: "head", equals: "c12r7" }, category: "navigate", limit_ticks: 2 }];
  const pack = packFromText(dumpPack(raw), "snake-state");
  assert.deepEqual(pack.tasks.map((x) => x.id), ["score_ten", "go_right"]);
  const states = [0, 1, 2, 3, 4, 5].map((i) => ({ snake: [[3 + i, 6], [2 + i, 6], [1 + i, 6]], food: [9, 2], score: i < 2 ? 0 : 10, over: false }));
  const dev = new StillDevice([{ width: W, height: H, data: new Uint8ClampedArray(W * H * 4) }], [W, H]); let si = 0; dev.state = async () => states[Math.min(si++, 5)];
  const seen = []; const spy = { model: "spy", async ask(s, qs) { seen.push(s.task); return new RandomSensor(1).ask(s, qs); } };
  const ag = new Agent(pack, dev, spy); const events = []; ag.onTask = (e) => events.push(e);
  const recs = []; for (let i = 0; i < 6; i++) recs.push(await ag.step());
  assert.equal(recs[0].task_started, "score_ten"); assert.equal(recs[2].task_done, "score_ten"); assert.equal(events[0].outcome, "done"); assert.equal(events[0].ticks, 2);
  assert.equal(recs[3].task_started, "go_right"); assert.equal(recs[5].task_failed, "go_right"); assert.equal(events[1].outcome, "failed");
  assert.equal(seen[0], "eat until the score reaches 10");
  const ep = outcome(recs, 1, 1, "score"); assert.equal(ep.tasks_done, 1); assert.equal(ep.tasks_failed, 1);
  assert.ok(betterEpisode({ won: false, lost: false, ticks: 400, score: 0, tasks_done: 0 }, { won: false, lost: true, ticks: 50, score: 0, tasks_done: 1 }));
  const bank = new Bank(); for (const e of events) bank.addTaskResult(e, 1, 1); bank.addTaskResult({ ...events[1] }, 1, 2);
  const st = taskStats(bank.taskResults); assert.equal(st.tasks.score_ten.rate, 1); assert.equal(st.categories.navigate.rate, 0); assert.equal(st.tasks.go_right.attempts, 2);
  assert.equal(chooseOrder(pack.tasks, bank.taskResults)[0], "go_right"); assert.match(tasksText(pack.tasks, bank.taskResults), /score_ten \[score\] 1\/1/);
  // positive incidents: a revision that blocks a choice in a success span is refused; the per-kind cap keeps both kinds
  const inc = snakeIncident(); const good = { reason: "done: eat_three", tick: 30, decisions: inc.decisions.slice(0, 2), at: "", kind: "success" };
  const fullPack = packFromText(BUNDLED_PACKS.snake, "snake"), incumbent = stripped();
  const r2 = yaml.load(dumpPack(fullPack.raw)); r2.rules.push({ if: { read: "head_moving", equals: "right" }, exclude: ["right"] });
  const v = verifyRevision(packFromText(dumpPack(r2), "snake"), incumbent, inc, 0.7, 0.34, [], false, [good]);
  assert.ok(!v.ok && v.why.includes("completed a task")); assert.ok(verifyRevision(fullPack, incumbent, inc, 0.7, 0.34, [], false, [good]).ok);
  const b2 = new Bank(1); b2.addIncident(inc); b2.addIncident(good); b2.addIncident({ ...incidentOf(inc.decisions, "status is dead", 99) });
  assert.equal(b2.losses().length, 1); assert.equal(b2.losses()[0].tick, 99); assert.equal(b2.successes().length, 1);
  // the setter: ids normalised, unknown reads and already-true conditions rejected, categories outside the taxonomy become other
  const chat = { model: "fake", async complete() { return { text: '[{"id": "Score Five!", "instruction": "reach 5", "done": {"read": "score", "gte": 5}, "category": "score", "limit_ticks": 40}, {"id": "bogus", "instruction": "?", "done": {"read": "nothing", "equals": 1}}, {"id": "already", "instruction": "be playing", "done": {"read": "status", "equals": "playing"}}, {"id": "list", "instruction": "two", "done": [{"read": "score", "gte": 1}, {"read": "head", "not": "c3r7"}], "category": "weird"}, {"id": "go_there", "instruction": "reach the food", "done": {"read": "head", "equals": "c9r3"}}]', usage: {}, ms: 0 }; } };
  const log = [];
  const fresh = packFromText(BUNDLED_PACKS["snake-state"], "snake-state");
  const newTasks = await proposeTasks(chat, fresh, { width: W, height: H, data: new Uint8ClampedArray(W * H * 4) }, { score: 0, head: "c3r7", status: "playing" }, [], 5, (m) => log.push(m));
  assert.deepEqual(newTasks.map((x) => x.id), ["score_five", "list"]); assert.equal(newTasks[1].category, "other"); assert.equal(newTasks[1].done.length, 2);
  assert.ok(log.some((m) => m.includes("bogus")) && log.some((m) => m.includes("already done")) && log.some((m) => m.includes("exact cell")));
  for (let i = 0; i < 4; i++) await ag.step();
  assert.equal(ag.taskLog.filter((e) => e.id === "go_right" && e.outcome === "failed").length, 2); assert.equal(ag.task, null);
});

test("held keys, relative mouse and chunks reach the device; the digest finds recurring key runs", async () => {
  const { Agent, packFromText: pft, keyRuns } = await import("../dist/core.js");
  const raw = yaml.load(BUNDLED_PACKS["snake-state"]);
  raw.act = [{ id: "run", kind: "key", key: "ShiftLeft", hold_ms: 120 }, { id: "combo", kind: "chunk", keys: ["ArrowLeft", "ArrowLeft", "Space"], key_ms: 1 }, { id: "look", kind: "mouse_move", dx: 40, dy: -8 }, { id: "keep", kind: "wait" }];
  raw.rules = []; raw.tasks = [];
  const pack = pft(dumpPack(raw), "inputs");
  const got = [];
  const dev = { size: () => [W, H], frame: async () => ({ width: W, height: H, data: new Uint8ClampedArray(W * H * 4) }), tap: async () => {}, swipe: async () => {}, key: async (k, hold) => got.push(hold ? ["key", k, hold] : ["key", k]), mouseMove: async (dx, dy) => got.push(["mouse_move", dx, dy]), close: async () => {} };
  const ag = new Agent(pack, dev, null);
  assert.equal(await ag.act(pack.actions[0], {}), "key ShiftLeft held 120 ms"); assert.deepEqual(got.at(-1), ["key", "ShiftLeft", 120]);
  assert.equal(await ag.act(pack.actions[1], {}), "chunk ArrowLeft ArrowLeft Space"); assert.deepEqual(got.slice(-3), [["key", "ArrowLeft"], ["key", "ArrowLeft"], ["key", "Space"]]);
  assert.equal(await ag.act(pack.actions[2], {}), "mouse_move 40,-8"); assert.deepEqual(got.at(-1), ["mouse_move", 40, -8]);
  delete dev.mouseMove; assert.match(await ag.act(pack.actions[2], {}), /unsupported/);
  for (const bad of [{ id: "c", kind: "chunk" }, { id: "m", kind: "mouse_move" }, { id: "k", kind: "key" }]) assert.throws(() => { const r = yaml.load(dumpPack(raw)); r.act = [bad]; pft(dumpPack(r), "x"); });
  const ev = []; let t = 0;
  for (let rep = 0; rep < 3; rep++) { for (const k of ["ArrowLeft", "ArrowLeft", "Space"]) { ev.push({ t, type: "key", key: k }); t += 150; } t += 2000; }
  ev.push({ t, type: "key", key: "ArrowUp" });
  const runs = keyRuns(ev); assert.deepEqual(runs[0], [["ArrowLeft", "ArrowLeft", "Space"], 3]); assert.deepEqual(keyRuns([]), []);
});

test("task bounds: tasks that can never be done are refused, the setter's limits are clamped; the rater samples, clamps and calibrates", async () => {
  const { checkTasks, proposeTasks, SETTER_LIMIT_MIN, SETTER_LIMIT_MAX, sampleFrames, actionsSummary, rateEpisode, calibrateRater } = await import("../dist/core.js");
  const reads = { score: { kind: "json", path: "score" }, status: { kind: "color", rect: [0, 0, 1, 1], options: { playing: "#000000", over: "#ffffff" }, otherwise: "menu" }, board: { kind: "color", zone: "b", options: { x: "#000000" }, otherwise: "." } };
  const one = (kw) => checkTasks([{ id: "t", instruction: "?", done: { read: "score", gte: 5 }, ...kw }], reads)[0];
  assert.equal(one({ limit_ticks: 2 }).limit_ticks, 2); assert.equal(one({ limit_ticks: 60, hold_ticks: 60 }).hold_ticks, 60);
  for (const bad of [{ limit_ticks: 0 }, { limit_ticks: -5 }, { limit_ticks: 2.5 }, { limit_ticks: "60" }, { limit_ticks: true }, { limit_ticks: 1e6 }, { hold_ticks: 0 }, { limit_ticks: 50, hold_ticks: 51 }]) assert.throws(() => one(bad), undefined, JSON.stringify(bad));
  for (const d of [{ read: "score", gte: "ten" }, { read: "score", in: [] }, { read: "status", equals: "won" }, { read: "status", in: ["won", "lost"] }, { read: "status", gte: 1 }, [{ read: "score", gte: 10 }, { read: "score", lte: 5 }]])
    assert.throws(() => checkTasks([{ id: "t", instruction: "?", done: d }], reads), /can never be done/, JSON.stringify(d));
  assert.throws(() => checkTasks([{ id: "t", instruction: "?", done: { read: "score", gte: 1 }, when: { read: "status", equals: "paused" } }], reads), /can never be done/);
  for (const d of [{ read: "status", equals: "over" }, { read: "status", equals: "menu" }, { read: "status", in: ["over", "won"] }, { read: "board", equals: "anything" }, { read: "score.total", gte: 1 }, [{ read: "score", gte: 5 }, { read: "score", lte: 5 }]])
    checkTasks([{ id: "t", instruction: "?", done: d }], reads);
  const snake = packFromText(BUNDLED_PACKS.snake, "snake");
  checkTasks([{ id: "t", instruction: "?", done: { read: "status", equals: "won" } }], snake.reads, "pack", undefined, snake.zones);
  assert.throws(() => checkTasks([{ id: "t", instruction: "?", done: { read: "status", equals: "paused" } }], snake.reads, "pack", undefined, snake.zones), /never reads "paused"/);
  // the setter: 5 and 9000 ticks are clamped into its range, 0 ticks and a hold past the limit are refused
  const chat = { model: "fake", async complete(messages) { assert.ok(messages[0].content.includes(`${SETTER_LIMIT_MIN} to ${SETTER_LIMIT_MAX}`)); return { text: '[{"id": "quick", "instruction": "score 1", "done": {"read": "score", "gte": 1}, "limit_ticks": 5}, {"id": "forever", "instruction": "score 9", "done": {"read": "score", "gte": 9}, "limit_ticks": 9000}, {"id": "zero", "instruction": "score 2", "done": {"read": "score", "gte": 2}, "limit_ticks": 0}, {"id": "held", "instruction": "score 3", "done": {"read": "score", "gte": 3}, "hold_ticks": 500, "limit_ticks": 300}]', usage: {}, ms: 0 }; } };
  const log = [];
  const got = await proposeTasks(chat, packFromText(BUNDLED_PACKS["snake-state"], "snake-state"), { width: W, height: H, data: new Uint8ClampedArray(W * H * 4) }, { score: 0, head: "c3r7", status: "playing" }, [], 5, (m) => log.push(m));
  assert.deepEqual(got.map((t) => [t.id, t.limit_ticks]), [["quick", SETTER_LIMIT_MIN], ["forever", SETTER_LIMIT_MAX]]);
  assert.ok(log.some((m) => m.includes("quick") && m.includes("clamped")) && log.some((m) => m.includes("zero") && m.includes("rejected")) && log.some((m) => m.includes("held") && m.includes("rejected")));
  // the rater, as rater.py: first and last frames kept, scores clamped to 0..100, failures give nulls, calibration over strict pairs
  const tiny = { width: 4, height: 4, data: new Uint8ClampedArray(64) };
  const frames = Array.from({ length: 100 }, (_, i) => [i + 1, tiny]);
  const picked = sampleFrames(frames, 10); assert.equal(picked.length, 10); assert.equal(picked[0][0], 1); assert.equal(picked.at(-1)[0], 100);
  const recs = [0, 1, 2, 3, 4].map((t) => ({ tick: t, choice: "right", action: "swipe right" })).concat([{ tick: 6, choice: "up", action: "swipe up" }]);
  assert.match(actionsSummary(recs), /6 actions/); assert.match(actionsSummary(recs), /swipe right×5/);
  const rc = { model: "fake", cost: 0, async complete(messages) { assert.equal(messages[1].content.filter((p) => p.type === "image_url").length, 3); this.cost += 0.001; return { text: '{"completion": 72.4, "directedness": 140, "note": "ate two, then turned into the wall"}', usage: {}, ms: 0 }; } };
  const r = await rateEpisode(rc, frames.slice(0, 3), recs, "snake", "first_food", "status is dead");
  assert.equal(r.completion, 72); assert.equal(r.directedness, 100); assert.match(r.note, /^ate two/); assert.equal(r.cost_usd, 0.001);
  assert.equal((await rateEpisode({ model: "x", async complete() { throw new Error("down"); } }, frames.slice(0, 2), recs)).completion, null);
  const eps = [{ won: false, lost: true, ticks: 50, score: null, tasks_done: 0, rating: { completion: 10 } }, { won: false, lost: true, ticks: 300, score: null, tasks_done: 0, rating: { completion: 60 } },
               { won: false, lost: false, ticks: 400, score: null, tasks_done: 0, rating: { completion: 40 } }, { won: false, lost: false, ticks: 400, score: 999, tasks_done: 0 }];
  assert.deepEqual(calibrateRater(eps), { rated: 3, pairs: 3, agreement: 0.667 });
});
