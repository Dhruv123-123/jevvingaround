import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { loadPack, PackError } from "../src/pack/loader.js";
import { evalPack } from "../src/cli/eval.js";
import { noneSensor } from "../src/sensors/none.js";
import type { Sensor } from "../src/sensors/types.js";

const dir = mkdtempSync(join(tmpdir(), "packs-"));
const write = (name: string, body: string) => { const p = join(dir, name); writeFileSync(p, body); return p; };

describe("pack loader", () => {
  it("loads all six built-in packs", () => {
    for (const n of ["agent", "shell", "git-push", "email", "slack", "payment"]) {
      const p = loadPack(`packs/${n}.pack.yaml`);
      expect(p.name).toBe(n);
      expect(p.questions.length).toBeGreaterThan(3);
      expect(p.tests.length).toBeGreaterThanOrEqual(4);
    }
  });
  it("refuses a pack without tests, bad ids, thresholds on a choice, and > 255 options", () => {
    const base = `pack: t\nversion: 1\nsurface: x\nquestions:\n  - { id: ok, type: noul, instructions: i, criteria: { true: t, false: f } }\n`;
    expect(() => loadPack(write("a.pack.yaml", base))).toThrow(/without tests/);
    expect(() => loadPack(write("b.pack.yaml", `pack: t\nversion: 1\nsurface: x\nquestions:\n  - { id: Bad-Id, type: noul, instructions: i, criteria: { true: t, false: f } }\ntests: [{ name: n, state: {}, expect: { level: proceed } }]\n`))).toThrow(PackError);
    expect(() => loadPack(write("c.pack.yaml", `pack: t\nversion: 1\nsurface: x\nquestions:\n  - { id: c, type: choice, instructions: i, criteria: { a: null, b: null }, thresholds: { confirm: 0.5 } }\ntests: [{ name: n, state: {}, expect: { level: proceed } }]\n`))).toThrow(/thresholds apply to nouls/);
    const many = Object.fromEntries(Array.from({ length: 256 }, (_, i) => [`o${i}`, null]));
    expect(() => loadPack(write("d.pack.yaml", `pack: t\nversion: 1\nsurface: x\nquestions:\n  - { id: c, type: choice, instructions: i, criteria: ${JSON.stringify(many)} }\ntests: [{ name: n, state: {}, expect: { level: proceed } }]\n`))).toThrow(/2–255 options/);
  });
  it("extends merges parent questions and lets the child override thresholds and add rules", () => {
    write("parent.pack.yaml", `pack: parent\nversion: 1\nsurface: x\nl0: [{ flag: boom, level: block }]\nquestions:\n  - { id: p1, type: noul, instructions: i, criteria: { true: t, false: f }, thresholds: { confirm: 0.7 } }\ntests: [{ name: n, state: {}, expect: { level: proceed } }]\n`);
    const child = loadPack(write("child.pack.yaml", `pack: child\nversion: 2\nsurface: x\nextends: [parent]\nl0: [{ flag: careful, level: confirm }]\nthresholds:\n  p1: { confirm: 0.5 }\nquestions:\n  - { id: c1, type: noul, instructions: i, criteria: { true: t, false: f } }\n`));
    expect(child.questions.map((q) => q.id)).toEqual(["p1", "c1"]);
    expect(child.questions[0]!.thresholds).toEqual({ confirm: 0.5 });
    expect(child.questions[0]!.origin).toBe("org");
    expect(child.l0).toEqual({ boom: "block", careful: "confirm" });
    expect(() => loadPack(write("dup.pack.yaml", `pack: dup\nversion: 1\nsurface: x\nextends: [parent]\nquestions:\n  - { id: p1, type: noul, instructions: i, criteria: { true: t, false: f } }\n`))).toThrow(/already defined/);
  });
  it("resolves test states from files relative to the pack", () => {
    writeFileSync(join(dir, "s.json"), JSON.stringify({ l0_flags: ["boom"] }));
    const p = loadPack(write("f.pack.yaml", `pack: f\nversion: 1\nsurface: x\nl0: [{ flag: boom, level: block }]\nquestions:\n  - { id: q, type: noul, instructions: i, criteria: { true: t, false: f } }\ntests: [{ name: n, state: s.json, expect: { level: block } }]\n`));
    expect((p.tests[0]!.state as { l0_flags: string[] }).l0_flags).toEqual(["boom"]);
  });
});

describe("eval", () => {
  const p = loadPack("packs/shell.pack.yaml");
  it("under none: L0 cases pass, model cases are skipped, nothing fails", async () => {
    const r = await evalPack(p, noneSensor);
    expect(r.failed).toBe(0);
    expect(r.skipped).toBe(p.tests.filter((t) => t.requires_sensor).length);
    expect(r.cases.find((c) => c.name.startsWith("rm -rf"))!.level).toBe("block");
    expect(r.cases.find((c) => c.name.startsWith("force push"))!.level).toBe("confirm");
  });
  it("with a perfect oracle sensor every case passes and calibration is populated", async () => {
    const oracle: Sensor = {
      name: "oracle",
      async evaluate(state, questions) {
        const t = p.tests.find((x) => x.state === state)!;
        const answers: Record<string, any> = {};
        for (const [id, q] of Object.entries(questions)) {
          if (q.type === "noul") answers[id] = { type: "noul", noul: (t.expect.fires ?? []).includes(id) ? 0.9 : 0.05 };
          else if (q.type === "score") answers[id] = { type: "score", score: 1, legend: {}, probabilities: {}, confidence: 1 };
          else answers[id] = { type: "choice", choice: Object.keys(q.criteria as object)[0], probabilities: {}, confidence: 1 };
        }
        return { answers, latencyMs: 42, inputTokens: 500, costUsd: 0.000021, model: "oracle" };
      },
    };
    const r = await evalPack(p, oracle);
    expect(r.failed).toBe(0);
    expect(r.skipped).toBe(0);
    expect(r.latency.p50).toBe(42);
    const row = r.calibration.find((x) => x.id === "destructive_on_shared_resource")!;
    expect(row.buckets[4]!.positives).toBe(p.tests.filter((t) => t.expect.fires?.includes("destructive_on_shared_resource")).length);
    expect(row.buckets[0]!.n).toBe(p.tests.filter((t) => t.expect.not_fires?.includes("destructive_on_shared_resource")).length);
  });
});
