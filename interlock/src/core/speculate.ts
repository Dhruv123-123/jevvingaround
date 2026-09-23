import { hashState } from "./hash.js";

/**
 * Speculative evaluation: score the draft on every typing pause so the verdict for
 * the exact draft being sent is already cached when the user reaches for Send.
 *
 * Generic over the state and result so the same class serves every surface.
 */
export interface SpeculatorOptions<S, R> {
  getState: () => S | null;
  evaluate: (state: S, hash: string) => Promise<R>;
  debounceMs: number;
  onResult?: (r: R, hash: string, cacheHit: boolean) => void;
  onError?: (e: unknown) => void;
  /** injectable for tests */
  setTimeoutImpl?: typeof setTimeout;
  clearTimeoutImpl?: typeof clearTimeout;
}

export class Speculator<S, R> {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private cache = new Map<string, R>();
  private inflight = new Map<string, Promise<R>>();
  private seq = 0;
  private latestHash: string | null = null;
  private readonly st: typeof setTimeout;
  private readonly ct: typeof clearTimeout;

  constructor(private opts: SpeculatorOptions<S, R>) {
    // wrapped, not referenced: browsers throw "Illegal invocation" when a timer fn is called as a method
    this.st = opts.setTimeoutImpl ?? ((fn: () => void, ms?: number) => setTimeout(fn, ms));
    this.ct = opts.clearTimeoutImpl ?? ((t: ReturnType<typeof setTimeout> | undefined) => clearTimeout(t));
  }

  /** Call on every keystroke / recipient change. */
  onChange(): void {
    if (this.timer) this.ct(this.timer);
    this.timer = this.st(() => {
      this.timer = null;
      void this.speculate();
    }, this.opts.debounceMs);
  }

  private async speculate(): Promise<void> {
    const s = this.opts.getState();
    if (s === null) return;
    const h = hashState(s);
    this.latestHash = h;
    if (this.cache.has(h) || this.inflight.has(h)) return;
    const mySeq = ++this.seq;
    try {
      const r = await this.run(s, h);
      // Only report if this is still the newest thing we know about; stale results are dropped silently.
      if (mySeq === this.seq || h === this.latestHash) this.opts.onResult?.(r, h, false);
    } catch (e) {
      this.opts.onError?.(e);
    }
  }

  private run(s: S, h: string): Promise<R> {
    const p = this.opts.evaluate(s, h)
      .then((r) => { this.cache.set(h, r); return r; })
      .finally(() => this.inflight.delete(h));
    this.inflight.set(h, p);
    return p;
  }

  /** At click time: 0 ms on a hash hit, one call on a miss. */
  async verdictFor(s: S): Promise<{ result: R; hash: string; cacheHit: boolean }> {
    if (this.timer) { this.ct(this.timer); this.timer = null; }
    const h = hashState(s);
    this.latestHash = h;
    const hit = this.cache.get(h);
    if (hit !== undefined) return { result: hit, hash: h, cacheHit: true };
    const inflight = this.inflight.get(h);
    if (inflight) return { result: await inflight, hash: h, cacheHit: true };
    this.seq++;
    return { result: await this.run(s, h), hash: h, cacheHit: false };
  }

  invalidate(): void { this.cache.clear(); }
  get size(): number { return this.cache.size; }
}
