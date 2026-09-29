// The side panel is the whole runtime: it captures the game tab, runs the pack, calls the sensor, sends input,
// and shows the decision panel. Packs are bundled or authored here and cached in extension storage.
import yaml from "js-yaml";
import { Agent, BUNDLED_PACKS, loadPack, openSensor, Chat, VLMFallback, explore, digest as demoDigest, type Demo, type DemoEvent, type Keys, type Pack, type Rec, type Sensor } from "../core/index.js";
import { author, checkPack, extractYaml, withFingerprints, frameToDataUrl } from "../core/author.js";
import { TabDevice, type Region } from "../device/tab.js";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const log = (m: string) => { const el = $("log"); el.textContent = (el.textContent + "\n" + m).split("\n").slice(-200).join("\n"); el.scrollTop = el.scrollHeight; };

interface Store { keys?: Keys; sensor?: string; regions?: Record<string, Region>; packs?: Record<string, string>; packFor?: Record<string, string> }
async function load(): Promise<Store> { return (await chrome.storage.local.get(null)) as Store; }
async function save(patch: Partial<Store>) { await chrome.storage.local.set(patch); }

const params = new URLSearchParams(location.search);
let tabId: number | null = params.get("tab") ? Number(params.get("tab")) : null;
let tabUrl = "";
let agent: Agent | null = null;
let device: TabDevice | null = null;
let stopping = false;
let demo: Demo | null = null;               // the last recording or exploration, for the author
let recording: { t0: number; events: DemoEvent[]; frames: Demo["frames"]; timer: number; dev: TabDevice } | null = null;
let currentPackName = "";

async function currentTab(): Promise<chrome.tabs.Tab> {
  if (tabId !== null) return chrome.tabs.get(tabId);
  const [t] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!t?.id) throw new Error("no active tab");
  tabId = t.id;
  return t;
}
const originOf = (url: string) => { try { const u = new URL(url); return u.protocol === "file:" ? u.pathname : u.origin + u.pathname.split("?")[0]; } catch { return url; } };

async function refreshPacks(store: Store) {
  const sel = $<HTMLSelectElement>("pack");
  sel.innerHTML = "";
  const names = [...Object.keys(store.packs ?? {}).map((n) => `${n} (authored)`), ...Object.keys(BUNDLED_PACKS)];
  for (const n of names) { const o = document.createElement("option"); o.value = n; o.textContent = n; sel.append(o); }
  const remembered = store.packFor?.[originOf(tabUrl)];
  if (remembered && names.includes(remembered)) sel.value = remembered;
  else { const guess = names.find((n) => tabUrl.toLowerCase().includes(n.split(" ")[0].replace(/-.*/, ""))); if (guess) sel.value = guess; }
}

function packText(store: Store, name: string): string {
  return name.endsWith(" (authored)") ? store.packs![name.replace(" (authored)", "")] : BUNDLED_PACKS[name];
}

function bars(el: HTMLElement, o: Record<string, number> | undefined, title: string, chosen?: string, belief = false) {
  let h = o && Object.keys(o).length ? `<div class=dim>${title}</div>` : "";
  for (const [k, v] of Object.entries(o ?? {}).sort((a, b) => b[1] - a[1]).slice(0, 8)) {
    h += `<div class=lbl><span>${k}${k === chosen ? " ◀" : ""}</span><span>${Math.round(v * 100)}%</span></div><div class="bar${belief ? " belief" : ""}"><div style="width:${Math.round(v * 100)}%"></div></div>`;
  }
  el.innerHTML = h;
}

function showRec(rec: Rec) {
  $("live").hidden = false;
  $("hybrid").textContent = `mode ${rec.mode ?? "main"} · support ${rec.support ?? "–"} · ${rec.known ? "known: " + rec.known : "unknown screen"}${rec.fallback ? " · " + rec.fallback : ""}`;
  $("action").textContent = rec.action;
  bars($("probs"), rec.action_probs, "action", rec.choice);
  bars($("nouls"), rec.nouls, "beliefs", undefined, true);
  $("rules").textContent = (rec.rules ?? []).join("  ·  ");
  $("meta").textContent = `tick ${rec.tick} · perception ${rec.perception_ms} ms · sensor ${rec.jev_ms ?? "–"} ms · $${(rec.total_cost_usd ?? 0).toFixed(4)}${rec.reason ? " · " + rec.reason : ""}`;
  $("screen").textContent = JSON.stringify(rec.screen, null, 1);
}

async function pickRegion() {
  const t = await currentTab();
  await chrome.scripting.executeScript({ target: { tabId: t.id! }, files: ["region.js"] });
  $("regioninfo").textContent = "drag on the page…";
}

chrome.runtime.onMessage.addListener(async (msg) => {
  if (msg?.type !== "anygame:region") return;
  const store = await load();
  const regions = { ...(store.regions ?? {}) };
  const key = originOf(tabUrl);
  if (msg.region) regions[key] = msg.region; else delete regions[key];
  await save({ regions });
  $("regioninfo").textContent = msg.region ? `${msg.region.w}×${msg.region.h} at (${msg.region.x},${msg.region.y})` : "whole page";
});

async function makeDevice(store: Store, pack: Pack | null, name_is_authored = false): Promise<TabDevice> {
  const t = await currentTab();
  let region = store.regions?.[originOf(tabUrl)] ?? null;
  // no region drawn: a bundled pack was authored on a fixed-size page at the top-left, so use that box;
  // otherwise capture at the scale that makes the region match the pack's authored frame size, so its rects line up
  if (!region && pack && !name_is_authored) region = { x: 0, y: 0, w: pack.size[0], h: pack.size[1] };
  const scale = region && pack ? pack.size[0] / region.w : 1;
  const d = new TabDevice(t.id!, region, Math.max(0.25, Math.min(3, scale)));
  await d.attach();
  return d;
}

async function play() {
  const store = await load();
  const name = $<HTMLSelectElement>("pack").value;
  const text = packText(store, name);
  if (!text) { log("pick a pack, or author one"); return; }
  let pack: Pack;
  try { pack = loadPack(text, name); } catch (e) { log(String(e)); return; }
  const sensorSpec = $<HTMLSelectElement>("sensor").value;
  let sensor: Sensor | null;
  try { sensor = await openSensor(sensorSpec === "llm" ? "llm" : sensorSpec, store.keys ?? {}, Number(pack.raw.sensor_timeout_s ?? 4) * 1000); }
  catch (e) { log(`sensor: ${(e as Error).message} (open "keys and models")`); return; }
  await save({ packFor: { ...(store.packFor ?? {}), [originOf(tabUrl)]: name }, sensor: sensorSpec });
  device = await makeDevice(store, pack, name.endsWith(" (authored)"));
  agent = new Agent(pack, device, sensor, null);
  currentPackName = name;
  agent.goal = ($("game") as HTMLInputElement).value.trim() || pack.play.slice(0, 300);
  if (($("fallback") as HTMLInputElement).checked) {
    try { agent.fallback = new VLMFallback(new Chat(store.keys ?? {})); } catch (e) { log(`fallback off: ${(e as Error).message} (set a chat model in "keys and models")`); }
  }
  // every learned screen or mode is written back to the pack: authored packs update in place, bundled ones fork to "<name> (authored)"
  agent.onPackChange = async (y, why) => {
    log(`pack: ${why}`);
    if (!/learned|tuned/.test(why)) return;
    const s = await load();
    const key = name.endsWith(" (authored)") ? name.replace(" (authored)", "") : `${name}-learned`;
    await save({ packs: { ...(s.packs ?? {}), [key]: y }, packFor: { ...(s.packFor ?? {}), [originOf(tabUrl)]: `${key} (authored)` } });
    if (!name.endsWith(" (authored)")) { currentPackName = `${key} (authored)`; await refreshPacks(await load()); $<HTMLSelectElement>("pack").value = currentPackName; }
  };
  const records: Rec[] = [];
  const shots: import("../core/geometry.js").Frame[] = [];
  let sinceTune = 0, tuning = false;
  agent.onRecord = (rec, frame) => {
    showRec(rec);
    records.push(rec); if (records.length > 400) records.shift();
    if (rec.choice) { shots.push(frame); if (shots.length > 30) shots.shift(); sinceTune++; }
    const lost = /lost|dead|over/.test(String(rec.reason ?? ""));
    if (($("improve") as HTMLInputElement).checked && !tuning && (sinceTune >= 40 || (lost && sinceTune > 5))) { sinceTune = 0; tuning = true; improveOnce(records.slice(), shots.slice()).finally(() => { tuning = false; }); }
  };
  $("playtext").textContent = pack.play; ($("playtext") as HTMLTextAreaElement).value = pack.play;
  ($("rulestext") as HTMLTextAreaElement).value = pack.rules.length ? yaml.dump(pack.rules) : "";
  $<HTMLButtonElement>("play").disabled = true; $<HTMLButtonElement>("stop").disabled = false; $<HTMLButtonElement>("author").disabled = true;
  stopping = false;
  log(`playing ${pack.name} on tab ${device.tabId} with ${sensorSpec} · frame ${device.size().join("x")}`);
  try {
    const last = await agent.run(() => stopping);
    log(`done: ${last.action}${last.reason ? " · " + last.reason : ""} after ${agent.tick} ticks, $${agent.totalCost.toFixed(4)}`);
  } catch (e) { log(`error: ${(e as Error).message}`); }
  await stop();
}

/** One tune round in the background while the game keeps going: digest → the chat model → a pack that must still
 *  pass the fixtures the current pack carries (its fingerprinted screens) → hot swap. */
async function improveOnce(records: Rec[], shots: import("../core/geometry.js").Frame[]) {
  if (!agent) return;
  const store = await load();
  let chat: Chat;
  try { chat = new Chat(store.keys ?? {}); } catch { return; }
  const dec = records.filter((r) => r.jev_ms !== undefined);
  const count = (xs: string[]) => { const c: Record<string, number> = {}; for (const x of xs) c[x] = (c[x] ?? 0) + 1; return c; };
  const dg = [
    `ticks ${records.length}, decisions ${dec.length}, last reason: ${records[records.length - 1]?.reason ?? "none"}`,
    `actions: ${JSON.stringify(count(dec.map((r) => String(r.action).split(" (")[0])))}`,
    `rules fired: ${JSON.stringify(count(dec.flatMap((r) => (r.rules ?? []).map((x) => x.split(" → ")[0]))))}`,
    ...dec.filter((_, i) => i % Math.max(1, Math.floor(dec.length / 10)) === 0).slice(0, 10).map((r) => `tick ${r.tick}: screen=${JSON.stringify(r.screen).slice(0, 300)} → ${r.action} probs=${JSON.stringify(r.action_probs)} beliefs=${JSON.stringify(r.nouls)}`),
  ].join("\n");
  const parts: any[] = [{ type: "text", text: "This pack is playing right now. Here is how it has PLAYED recently. Revise the play paragraph, the questions and the rules so it plays better (move counting into derived reads, make fatal moves impossible with rules). Keep zones and reads unless the frames show a read is wrong. Return the whole pack.yaml in one fenced yaml block.\n\n" + dg + "\n\n```yaml\n" + (await import("../core/pack.js")).dumpPack(agent.base.raw) + "\n```" }];
  for (const f of shots.length > 2 ? [shots[Math.floor(shots.length / 2)], shots[shots.length - 1]] : shots) parts.push({ type: "image_url", image_url: { url: await frameToDataUrl(f) } });
  log("improve: asking the chat model …");
  try {
    const { text } = await chat.complete([{ role: "user", content: parts }], 12000, 0.2);
    const y = extractYaml(text);
    if (!y || !agent) { log("improve: no pack returned"); return; }
    const cand = loadPack(y, "improved");
    // the candidate must still read the screens the current pack knows: check on the last frames we have
    const probe = new Agent(cand, agent.device, null);
    let ok = true;
    for (const f of shots.slice(-3)) { const { values, conf } = probe.observe(f, cand); if (probe.support(conf, values, cand) < 0.5) ok = false; }
    if (!ok) { log("improve: the revised pack reads the current screens worse; kept the old one"); return; }
    cand.raw.fingerprints = { ...(agent.base.raw.fingerprints ?? {}), ...(cand.raw.fingerprints ?? {}) };
    agent.swapPack(loadPack((await import("../core/pack.js")).dumpPack(cand.raw), "improved"));
    ($("playtext") as HTMLTextAreaElement).value = agent.base.play;
    ($("rulestext") as HTMLTextAreaElement).value = agent.base.rules.length ? yaml.dump(agent.base.rules) : "";
    agent.onPackChange?.((await import("../core/pack.js")).dumpPack(agent.base.raw), "tuned while playing");
    log("improve: swapped in the revised pack");
  } catch (e) { log(`improve: ${(e as Error).message.slice(0, 120)}`); }
}

// ---- demonstrations: record the human, or let the model explore ----
chrome.runtime.onMessage.addListener(async (msg) => {
  if (msg?.type !== "anygame:record") return;
  if (msg.state === "started") {
    const store = await load();
    const dev = await makeDevice(store, null);
    recording = { t0: performance.now(), events: [], frames: [], dev, timer: 0 };
    recording.timer = window.setInterval(async () => { if (!recording) return; try { recording.frames.push({ t: performance.now() - recording.t0, frame: await recording.dev.frame() }); } catch { /* tab gone */ } }, 250);
    $("record").textContent = "stop recording"; $("demoinfo").textContent = "recording… play the game for a minute";
  } else if (msg.state === "stopped") {
    if (recording) {
      window.clearInterval(recording.timer);
      const r = recording; recording = null;
      await r.dev.close().catch(() => {});
      // click coordinates arrive in CSS px of the page; frames are region px: map them
      const reg = r.dev.region!, sc = r.dev.captureScale;
      const events = r.events.map((e) => e.type === "click" && e.x !== undefined && e.y !== undefined ? { ...e, x: (e.x - reg.x) * sc, y: (e.y - reg.y) * sc } : e);
      demo = { frames: r.frames, events, source: "human" };
      const dg = demoDigest(demo);
      $("demoinfo").textContent = `recorded ${dg.seconds}s, ${events.length} inputs, keys ${Object.keys(dg.keys).join(" ") || "none"}: the author will use it`;
      $("record").textContent = "record me";
    }
  } else if (msg.event && recording) {
    recording.events.push({ ...msg.event, t: performance.now() - recording.t0 });
  }
});

async function toggleRecord() {
  const t = await currentTab();
  await chrome.scripting.executeScript({ target: { tabId: t.id! }, files: ["record.js"] });
}

async function runExplore() {
  const store = await load();
  let chat: Chat;
  try { chat = new Chat(store.keys ?? {}); } catch (e) { log(`explore needs a chat model: ${(e as Error).message}`); return; }
  $<HTMLButtonElement>("explore").disabled = true; $<HTMLButtonElement>("stop").disabled = false; stopping = false;
  device = await makeDevice(store, null);
  try {
    demo = await explore({ device, chat, seconds: 90, game: ($("game") as HTMLInputElement).value.trim() || tabUrl, log, shouldStop: () => stopping });
    const dg = demoDigest(demo);
    $("demoinfo").textContent = `explored ${dg.seconds}s, ${demo.events.length} inputs, keys ${Object.keys(dg.keys).join(" ") || "none"}: the author will use it`;
  } catch (e) { log(`explore: ${(e as Error).message}`); }
  await stop();
  $<HTMLButtonElement>("explore").disabled = false;
}

async function stop() {
  stopping = true;
  await device?.close().catch(() => {});
  device = null; agent = null;
  $<HTMLButtonElement>("play").disabled = false; $<HTMLButtonElement>("stop").disabled = true; $<HTMLButtonElement>("author").disabled = false;
}

function applyEdits() {
  if (!agent) { $("applymsg").textContent = "not playing"; return; }
  try {
    const rules = yaml.load(($("rulestext") as HTMLTextAreaElement).value || "[]");
    if (!Array.isArray(rules)) throw new Error("rules must be a YAML list");
    agent.pack.play = ($("playtext") as HTMLTextAreaElement).value.trim() || agent.pack.play;
    agent.pack.rules = rules as any[];
    agent.lastAnswers = null;
    $("applymsg").textContent = "applied: the next tick uses the new paragraph and rules";
  } catch (e) { $("applymsg").textContent = `not applied: ${(e as Error).message}`; }
}

async function runAuthor() {
  const store = await load();
  const game = ($("game") as HTMLInputElement).value.trim();
  if (!game) { log("describe the game in a sentence first"); return; }
  if (!store.keys?.llmBase && !store.keys?.openrouter) { log("the author needs a chat model: open \"keys and models\""); return; }
  const sensorSpec = $<HTMLSelectElement>("sensor").value;
  let sensor: Sensor | null = null;
  try { sensor = await openSensor(sensorSpec === "llm" ? "llm" : sensorSpec, store.keys ?? {}); } catch { sensor = null; }
  $<HTMLButtonElement>("author").disabled = true; $<HTMLButtonElement>("play").disabled = true; $<HTMLButtonElement>("stop").disabled = false;
  stopping = false;
  device = await makeDevice(store, null);
  const slug = (game.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 30) || "game") + "-" + originOf(tabUrl).replace(/[^a-z0-9]+/gi, "").slice(-8);
  try {
    const res = await author({
      game, play: ($("playhint") as HTMLInputElement).value.trim() || undefined, rounds: 3, framesN: 6, playTicks: sensor ? 30 : 0, tune: sensor ? 1 : 0,
      keys: store.keys ?? {}, sensor, device, log, shouldStop: () => stopping, demo: demo ?? undefined,
      onPack: async (y) => { const s = await load(); await save({ packs: { ...(s.packs ?? {}), [slug]: y } }); },
    });
    if (res.yaml) {
      const s = await load();
      await save({ packs: { ...(s.packs ?? {}), [slug]: res.yaml }, packFor: { ...(s.packFor ?? {}), [originOf(tabUrl)]: `${slug} (authored)` } });
      await refreshPacks(await load());
      $<HTMLSelectElement>("pack").value = `${slug} (authored)`;
      $("authorinfo").textContent = res.ok ? "pack passes its tests: press play" : "pack saved but its tests do not pass; edit it or try again";
    }
  } catch (e) { log(`author: ${(e as Error).message}`); }
  await stop();
}

async function main() {
  const store = await load();
  const t = await currentTab();
  tabUrl = t.url ?? "";
  $("tabinfo").textContent = (t.title ?? tabUrl).slice(0, 40);
  await refreshPacks(store);
  const region = store.regions?.[originOf(tabUrl)];
  $("regioninfo").textContent = region ? `${region.w}×${region.h} at (${region.x},${region.y})` : "whole page";
  if (store.sensor) $<HTMLSelectElement>("sensor").value = store.sensor;
  for (const k of ["openrouter", "llmBase", "llmKey", "llmModel"] as const) ($(`k_${k}`) as HTMLInputElement).value = (store.keys as any)?.[k] ?? "";
  $("savekeys").onclick = async () => {
    const keys: Keys = {};
    for (const k of ["openrouter", "llmBase", "llmKey", "llmModel"] as const) { const v = ($(`k_${k}`) as HTMLInputElement).value.trim(); if (v) (keys as any)[k] = v; }
    await save({ keys }); log("keys saved");
  };
  $("region").onclick = () => pickRegion().catch((e) => log(String(e)));
  $("play").onclick = () => play().catch((e) => log(String(e)));
  $("stop").onclick = () => stop();
  $("apply").onclick = applyEdits;
  $("author").onclick = () => runAuthor().catch((e) => log(String(e)));
  $("record").onclick = () => toggleRecord().catch((e) => log(String(e)));
  $("explore").onclick = () => runExplore().catch((e) => log(String(e)));
  chrome.debugger.onDetach.addListener((src) => { if (src.tabId === tabId && agent) { log("debugger detached (tab closed or banner cancelled)"); stop(); } });
  log("ready");
}
main().catch((e) => log(String(e)));
