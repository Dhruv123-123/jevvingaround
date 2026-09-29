// Content script: "record me". Reports every key and click on the page (with page coordinates) to the panel
// while a recording is on; the panel captures frames alongside and builds the demonstration.
(() => {
  const w = window as any;
  if (w.__anygameRecord) { w.__anygameRecord.stop(); delete w.__anygameRecord; chrome.runtime.sendMessage({ type: "anygame:record", state: "stopped" }); return; }
  const t0 = performance.now();
  const onKey = (e: KeyboardEvent) => chrome.runtime.sendMessage({ type: "anygame:record", event: { t: performance.now() - t0, type: "key", key: e.key === " " ? "Space" : e.key } });
  const onClick = (e: MouseEvent) => chrome.runtime.sendMessage({ type: "anygame:record", event: { t: performance.now() - t0, type: "click", x: e.clientX, y: e.clientY } });
  window.addEventListener("keydown", onKey, true);
  window.addEventListener("mousedown", onClick, true);
  const badge = document.createElement("div");
  badge.textContent = "● anygame is recording you — click the extension's stop button when done";
  badge.style.cssText = "position:fixed;top:8px;left:50%;transform:translateX(-50%);background:#dc2626;color:#fff;padding:6px 12px;border-radius:8px;font:13px system-ui;z-index:2147483647;pointer-events:none";
  document.body.append(badge);
  w.__anygameRecord = { stop: () => { window.removeEventListener("keydown", onKey, true); window.removeEventListener("mousedown", onClick, true); badge.remove(); } };
  chrome.runtime.sendMessage({ type: "anygame:record", state: "started", t0: 0, vw: window.innerWidth, vh: window.innerHeight });
})();
