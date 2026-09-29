// Content script: the user drags a box around the game once; the panel stores it per site.
(() => {
  if ((window as any).__anygameRegion) return;
  (window as any).__anygameRegion = true;
  const ov = document.createElement("div");
  ov.style.cssText = "position:fixed;inset:0;z-index:2147483647;cursor:crosshair;background:rgba(0,0,0,.25)";
  const box = document.createElement("div");
  box.style.cssText = "position:fixed;border:2px solid #4ade80;background:rgba(74,222,128,.15);display:none;pointer-events:none;z-index:2147483647";
  const hint = document.createElement("div");
  hint.textContent = "anygame: drag a box around the game (Esc = whole page)";
  hint.style.cssText = "position:fixed;top:12px;left:50%;transform:translateX(-50%);background:#111;color:#eee;padding:8px 14px;border-radius:8px;font:14px system-ui;z-index:2147483647";
  document.body.append(ov, box, hint);
  let x0 = 0, y0 = 0, drag = false;
  const done = (r: { x: number; y: number; w: number; h: number } | null) => {
    ov.remove(); box.remove(); hint.remove(); delete (window as any).__anygameRegion;
    chrome.runtime.sendMessage({ type: "anygame:region", region: r, dpr: window.devicePixelRatio, vw: window.innerWidth, vh: window.innerHeight });
  };
  ov.addEventListener("mousedown", (e) => { drag = true; x0 = e.clientX; y0 = e.clientY; box.style.display = "block"; });
  ov.addEventListener("mousemove", (e) => {
    if (!drag) return;
    const x = Math.min(x0, e.clientX), y = Math.min(y0, e.clientY), w = Math.abs(e.clientX - x0), h = Math.abs(e.clientY - y0);
    Object.assign(box.style, { left: x + "px", top: y + "px", width: w + "px", height: h + "px" });
  });
  ov.addEventListener("mouseup", (e) => {
    if (!drag) return;
    drag = false;
    const x = Math.min(x0, e.clientX), y = Math.min(y0, e.clientY), w = Math.abs(e.clientX - x0), h = Math.abs(e.clientY - y0);
    done(w > 20 && h > 20 ? { x, y, w, h } : null);
  });
  window.addEventListener("keydown", (e) => { if (e.key === "Escape") done(null); }, { once: true });
})();
