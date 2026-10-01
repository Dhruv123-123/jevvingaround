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
