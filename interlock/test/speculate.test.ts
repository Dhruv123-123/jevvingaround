import { describe, expect, it, vi } from "vitest";
import { Speculator } from "../src/core/speculate.js";

function make(evaluate: (s: { v: number }) => Promise<string>, debounceMs = 100) {
  const results: Array<[string, boolean]> = [];
  let state: { v: number } | null = { v: 1 };
  const spec = new Speculator<{ v: number }, string>({
    getState: () => state,
    evaluate: (s) => evaluate(s),
    debounceMs,
    onResult: (r, _h, hit) => results.push([r, hit]),
  });
  return { spec, results, setState: (s: { v: number } | null) => (state = s) };
}

describe("Speculator", () => {
  it("debounces keystrokes into one evaluation and serves the click from cache", async () => {
    vi.useFakeTimers();
    const evaluate = vi.fn(async (s: { v: number }) => `r${s.v}`);
    const { spec, results } = make(evaluate);
    spec.onChange(); spec.onChange(); spec.onChange();
    await vi.advanceTimersByTimeAsync(99);
    expect(evaluate).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(evaluate).toHaveBeenCalledTimes(1);
    expect(results).toEqual([["r1", false]]);
    const click = await spec.verdictFor({ v: 1 });
    expect(click).toMatchObject({ result: "r1", cacheHit: true });
    expect(evaluate).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it("evaluates once on a cache miss and dedupes an in-flight identical state", async () => {
    let resolve!: (s: string) => void;
    const evaluate = vi.fn(() => new Promise<string>((r) => (resolve = r)));
    const { spec } = make(evaluate);
    const a = spec.verdictFor({ v: 2 });
    const b = spec.verdictFor({ v: 2 });
    expect(evaluate).toHaveBeenCalledTimes(1);
    resolve("r2");
    expect((await a).cacheHit).toBe(false);
    expect((await b).cacheHit).toBe(true);
  });

  it("cancels a pending speculative timer when the click arrives first", async () => {
    vi.useFakeTimers();
    const evaluate = vi.fn(async (s: { v: number }) => `r${s.v}`);
    const { spec } = make(evaluate);
    spec.onChange();
    const r = await spec.verdictFor({ v: 1 });
    expect(r.cacheHit).toBe(false);
    await vi.advanceTimersByTimeAsync(500);
    expect(evaluate).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it("does not speculate on a null state", async () => {
    vi.useFakeTimers();
    const evaluate = vi.fn(async () => "x");
    const { spec, setState } = make(evaluate);
    setState(null);
    spec.onChange();
    await vi.advanceTimersByTimeAsync(200);
    expect(evaluate).not.toHaveBeenCalled();
    vi.useRealTimers();
  });
});
