import { createServer } from "node:http";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { llmSensor } from "../src/sensors/llm.js";
import { noneSensor } from "../src/sensors/none.js";
import { toWire } from "../src/core/jev.js";
import { loadPack } from "../src/pack/loader.js";
import { mboxRegrets, slackRegrets } from "../src/cli/exports.js";
import { runRecall } from "../src/cli/recall.js";

let url = "";
let lastBody: any = null;
let srv: ReturnType<typeof createServer>;
beforeAll(async () => {
  // a fake OpenAI-compatible endpoint that answers from the question ids it is asked
  srv = createServer((req, res) => {
    let raw = ""; req.on("data", (c) => (raw += c)); req.on("end", () => {
      lastBody = JSON.parse(raw);
      const props = Object.keys(lastBody.response_format.json_schema.schema.properties);
      const out: Record<string, unknown> = {};
      for (const id of props) out[id] = id === "irreversible" ? 0.93 : id === "blast_radius" ? 3 : id.endsWith("__which") ? "none" : 0.02;
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ choices: [{ message: { content: "```json\n" + JSON.stringify(out) + "\n```" } }], usage: { prompt_tokens: 640 } }));
    });
  });
  await new Promise<void>((r) => srv.listen(0, "127.0.0.1", r));
  url = `http://127.0.0.1:${(srv.address() as { port: number }).port}/v1`;
});
afterAll(() => srv.close());

describe("llm sensor", () => {
  it("asks an OpenAI-compatible endpoint for strict JSON and maps it to typed answers", async () => {
    const pack = loadPack("packs/agent.pack.yaml");
    const s = llmSensor({ apiKey: "k", baseUrl: url, model: "fake-4" });
    const r = await s.evaluate({ tool: { name: "delete_repo" } }, toWire(pack.questions));
    expect(lastBody.model).toBe("fake-4");
    expect(lastBody.response_format.type).toBe("json_schema");
    expect(lastBody.messages[1].content).toMatch(/QUESTIONS:/);
    expect(r.answers["irreversible"]).toEqual({ type: "noul", noul: 0.93 });
    expect(r.answers["blast_radius"]).toMatchObject({ type: "score", score: 3 });
    expect(r.inputTokens).toBe(640);
    expect(r.model).toBe("fake-4");
    expect(s.name).toBe("llm:fake-4");
  });
  it("none answers instantly with zeros", async () => {
    const r = await noneSensor.evaluate({}, { q: { type: "noul", instructions: "x", criteria: { true: "t", false: "f" } }, c: { type: "choice", instructions: "x", criteria: { a: null, b: null } } });
    expect(r.answers["q"]).toEqual({ type: "noul", noul: 0 });
    expect(r.answers["c"]).toMatchObject({ type: "choice", choice: "a" });
    expect(r.latencyMs).toBe(0);
  });
});

describe("recall over exports", () => {
  const since = Date.parse("2026-09-01");
  it("finds the sorry-follow-up within 15 minutes in an mbox, not the one 40 minutes later", () => {
    const r = mboxRegrets("test/fixtures/sent.mbox", since, "me@ourco.com");
    expect(r).toHaveLength(1);
    expect(r[0]).toMatchObject({ surface: "email", detector: "sorry_follow_up_15m", ref: "<a1@ourco.com>" });
    expect(r[0]!.detail).toMatch(/Q3 pricing → "Sorry, forgot the attachment/);
  });
  it("finds a 20 s edit and a 'wrong channel' follow-up in a Slack export, not a much later edit", () => {
    const r = slackRegrets("test/fixtures/slack-export", since, "U1");
    expect(r.map((x) => x.detector).sort()).toEqual(["edited_within_60s", "sorry_follow_up_60s"]);
    expect(r.find((x) => x.detector === "edited_within_60s")!.detail).toBe("deploying to prod now");
  });
  it("runRecall wires the export detectors in and writes regret records once", async () => {
    process.env.INTERLOCK_HOME = mkdtempSync(join(tmpdir(), "il-recall-"));
    const r1 = await runRecall({ cwd: tmpdir(), since: "400d", home: tmpdir(), mbox: "test/fixtures/sent.mbox", slackExport: "test/fixtures/slack-export", self: undefined });
    expect(r1.regrets.length).toBeGreaterThanOrEqual(3);
    expect(r1.notes).toEqual([]);
    const r2 = await runRecall({ cwd: tmpdir(), since: "400d", home: tmpdir(), mbox: "test/fixtures/sent.mbox", slackExport: "test/fixtures/slack-export" });
    const { readRegrets } = await import("../src/node/audit.js");
    expect(readRegrets().length).toBe(r2.regrets.length); // second run did not duplicate
  });
});
