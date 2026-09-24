import { describe, expect, it, vi } from "vitest";
import { JevClient, JevError, toWire } from "../src/core/jev.js";
import { loadPack } from "../src/pack/loader.js";
const EMAIL_BANK = loadPack("packs/email.pack.yaml").questions;

const ok = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

describe("JevClient", () => {
  it("posts {model,state,questions} to /v1/systemone with a bearer token and parses answers", async () => {
    const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      expect(String(url)).toBe("https://api.typesafe.ai/v1/systemone");
      expect((init!.headers as Record<string, string>).authorization).toBe("Bearer k");
      const body = JSON.parse(init!.body as string);
      expect(body.model).toBe("jev-latest");
      expect(Object.keys(body.questions)).toContain("wrong_recipient");
      expect(body.questions.wrong_recipient).not.toHaveProperty("thresholds");
      return ok({ model: "jev-1.13", answers: { wrong_recipient: { type: "noul", noul: 0.12 } }, usage: { input_tokens: 812, output_tokens: 0 } });
    });
    const c = new JevClient({ apiKey: "k", baseUrl: "https://api.typesafe.ai/", model: "jev-latest", fetchImpl: fetchImpl as unknown as typeof fetch });
    const r = await c.evaluate({ a: 1 }, toWire(EMAIL_BANK));
    expect(r.answers.wrong_recipient).toEqual({ type: "noul", noul: 0.12 });
    expect(r.inputTokens).toBe(812);
    expect(r.model).toBe("jev-1.13");
  });

  it("retries exactly once on 529 then surfaces the error", async () => {
    const fetchImpl = vi.fn(async () => ok({ error: "overloaded" }, 529));
    const c = new JevClient({ apiKey: "k", baseUrl: "x", model: "m", fetchImpl: fetchImpl as unknown as typeof fetch, retryDelayMs: 1 });
    await expect(c.evaluate({}, {})).rejects.toBeInstanceOf(JevError);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("times out", async () => {
    const fetchImpl = vi.fn((_u: unknown, init?: RequestInit) => new Promise<Response>((_, rej) => init!.signal!.addEventListener("abort", () => rej(new Error("aborted")))));
    const c = new JevClient({ apiKey: "k", baseUrl: "x", model: "m", fetchImpl: fetchImpl as unknown as typeof fetch, timeoutMs: 5 });
    await expect(c.evaluate({}, {})).rejects.toThrow(/aborted/);
  });
});
