// A browser tab as a device, through chrome.debugger: Page.captureScreenshot for frames (works on background
// tabs and canvases), Input.dispatch* for taps, swipes and keys (trusted events, unlike synthetic DOM events).
// A region (CSS px) restricts frames and input to the game's box on the page.
import type { Frame } from "../core/geometry.js";
import type { Device } from "../core/loop.js";

export interface Region { x: number; y: number; w: number; h: number }

const KEYS: Record<string, { key: string; code: string; vk: number; text?: string }> = {
  ArrowUp: { key: "ArrowUp", code: "ArrowUp", vk: 38 }, ArrowDown: { key: "ArrowDown", code: "ArrowDown", vk: 40 },
  ArrowLeft: { key: "ArrowLeft", code: "ArrowLeft", vk: 37 }, ArrowRight: { key: "ArrowRight", code: "ArrowRight", vk: 39 },
  Space: { key: " ", code: "Space", vk: 32, text: " " }, " ": { key: " ", code: "Space", vk: 32, text: " " },
  Enter: { key: "Enter", code: "Enter", vk: 13, text: "\r" }, Escape: { key: "Escape", code: "Escape", vk: 27 },
  Shift: { key: "Shift", code: "ShiftLeft", vk: 16 }, Tab: { key: "Tab", code: "Tab", vk: 9 },
};
function keyInfo(name: string) {
  if (KEYS[name]) return KEYS[name];
  if (name.length === 1) { const up = name.toUpperCase(); return { key: name, code: /[a-z]/i.test(name) ? `Key${up}` : /[0-9]/.test(name) ? `Digit${name}` : name, vk: up.charCodeAt(0), text: name }; }
  return { key: name, code: name, vk: 0 };
}

export class TabDevice implements Device {
  private attached = false;
  private scale = 1;             // captured px per CSS px inside the region
  private sz: [number, number] = [0, 0];
  onError?: (e: Error) => void;

  constructor(public tabId: number, public region: Region | null, public captureScale = 1, public jpegQuality = 80, public stateExpr: string | null = null) {}

  private send<T = any>(method: string, params: any = {}): Promise<T> {
    return new Promise((resolve, reject) => {
      chrome.debugger.sendCommand({ tabId: this.tabId }, method, params, (res) => {
        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message)); else resolve(res as T);
      });
    });
  }

  async attach(): Promise<void> {
    if (this.attached) return;
    await new Promise<void>((resolve, reject) => chrome.debugger.attach({ tabId: this.tabId }, "1.3", () => (chrome.runtime.lastError ? reject(new Error(chrome.runtime.lastError.message)) : resolve())));
    this.attached = true;
    await this.send("Page.enable");
    const m = await this.send("Page.getLayoutMetrics");
    const vw = m.cssVisualViewport?.clientWidth ?? m.layoutViewport.clientWidth, vh = m.cssVisualViewport?.clientHeight ?? m.layoutViewport.clientHeight;
    if (!this.region) this.region = { x: 0, y: 0, w: vw, h: vh };
    this.scale = this.captureScale;
    this.sz = [Math.round(this.region.w * this.scale), Math.round(this.region.h * this.scale)];
  }

  size(): [number, number] { return this.sz; }

  async frame(): Promise<Frame> {
    await this.attach();
    const r = this.region!;
    const res = await this.send("Page.captureScreenshot", { format: "jpeg", quality: this.jpegQuality, clip: { x: r.x, y: r.y, width: r.w, height: r.h, scale: this.scale }, fromSurface: true });
    const bytes = Uint8Array.from(atob(res.data), (c) => c.charCodeAt(0));
    const bmp = await createImageBitmap(new Blob([bytes], { type: "image/jpeg" }));
    const canvas = new OffscreenCanvas(this.sz[0], this.sz[1]);
    const ctx = canvas.getContext("2d")!;
    ctx.drawImage(bmp, 0, 0, this.sz[0], this.sz[1]);
    bmp.close();
    const img = ctx.getImageData(0, 0, this.sz[0], this.sz[1]);
    return { width: img.width, height: img.height, data: img.data };
  }

  private css(x: number, y: number): [number, number] {
    const r = this.region!;
    return [r.x + x / this.scale, r.y + y / this.scale];
  }

  async tap(x: number, y: number): Promise<void> {
    await this.attach();
    const [cx, cy] = this.css(x, y);
    await this.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: cx, y: cy });
    await this.send("Input.dispatchMouseEvent", { type: "mousePressed", x: cx, y: cy, button: "left", clickCount: 1 });
    await this.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: cx, y: cy, button: "left", clickCount: 1 });
  }

  async swipe(x0: number, y0: number, x1: number, y1: number, ms = 120): Promise<void> {
    await this.attach();
    const [ax, ay] = this.css(x0, y0), [bx, by] = this.css(x1, y1);
    const steps = Math.max(4, Math.floor(ms / 15));
    await this.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: ax, y: ay });
    await this.send("Input.dispatchMouseEvent", { type: "mousePressed", x: ax, y: ay, button: "left", clickCount: 1 });
    for (let i = 1; i <= steps; i++) {
      await this.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: ax + ((bx - ax) * i) / steps, y: ay + ((by - ay) * i) / steps, button: "left" });
    }
    await this.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: bx, y: by, button: "left", clickCount: 1 });
  }

  async key(name: string, holdMs = 0): Promise<void> {
    await this.attach();
    const k = keyInfo(name);
    const base = { key: k.key, code: k.code, windowsVirtualKeyCode: k.vk, nativeVirtualKeyCode: k.vk };
    await this.send("Input.dispatchKeyEvent", { type: k.text ? "keyDown" : "rawKeyDown", ...base, text: k.text, unmodifiedText: k.text });
    if (holdMs > 0) await new Promise((r) => setTimeout(r, holdMs));     // a held key: a run, a charge, a camera turn
    await this.send("Input.dispatchKeyEvent", { type: "keyUp", ...base });
  }

  private mx = -1; private my = -1;
  /** Relative mouse motion from the last pointer position (the page sees mousemove with the movement). */
  async mouseMove(dx: number, dy: number): Promise<void> {
    await this.attach();
    const [w, h] = this.size();
    if (this.mx < 0) { this.mx = w / 2; this.my = h / 2; }
    this.mx = Math.max(0, Math.min(w - 1, this.mx + dx)); this.my = Math.max(0, Math.min(h - 1, this.my + dy));
    const [cx, cy] = this.css(this.mx, this.my);
    await this.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: cx, y: cy });
  }

  /** The page's own state, when an expression was given (e.g. `window.__state()`): what the json reads consume. */
  async state(): Promise<any> {
    if (!this.stateExpr) return undefined;
    await this.attach();
    try {
      const res = await this.send("Runtime.evaluate", { expression: this.stateExpr, returnByValue: true, awaitPromise: true });
      return res?.result?.value;
    } catch { return undefined; }
  }

  /** Reload the page: the cheapest restart for a browser game between episodes. */
  async reload(): Promise<void> {
    await this.attach();
    await this.send("Page.reload", { ignoreCache: false });
    await new Promise((r) => setTimeout(r, 2500));
  }

  async close(): Promise<void> {
    if (!this.attached) return;
    this.attached = false;
    await new Promise<void>((resolve) => chrome.debugger.detach({ tabId: this.tabId }, () => resolve()));
  }
}
