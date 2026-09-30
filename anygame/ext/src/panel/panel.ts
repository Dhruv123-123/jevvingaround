// The side panel is the whole runtime: it captures the game tab, runs the pack, calls the sensor, sends input,
// and shows the decision panel. Packs are bundled or authored here and cached in extension storage.
import yaml from "js-yaml";
import { Agent, BUNDLED_PACKS, loadPack, dumpPack, openSensor, Chat, VLMFallback, explore, digest as demoDigest, fingerprint, fpDistance, fpFromBase64, type Frame, outcome, betterEpisode, medianEpisode, incidentOf, improve, LOST, type Decision, type Episode, type Incident, type Demo, type DemoEvent, type Keys, type Pack, type Rec, type Sensor } from "../core/index.js";
import { author, checkPack, extractYaml, withFingerprints, frameToDataUrl } from "../core/author.js";
import { TabDevice, type Region } from "../device/tab.js";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const log = (m: string) => { const el = $("log"); el.textContent = (el.textContent + "\n" + m).split("\n").slice(-200).join("\n"); el.scrollTop = el.scrollHeight; };

interface StoredIncident { reason: string; tick: number; at: string; recs: Rec[]; frames: string[] }
interface StoredBank { episodes: Episode[]; incidents: StoredIncident[]; version: number }
interface Store { keys?: Keys; sensor?: string; regions?: Record<string, Region>; packs?: Record<string, string>; packFor?: Record<string, string>; bank?: Record<string, StoredBank> }
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

const POOL_URL = "https://raw.githubusercontent.com/Dhruv123-123/jevvingaround/main/anygame/packs/pool.json";

/** A screenshot data URL (from chrome.tabs.captureVisibleTab) as a frame, cropped to the remembered region if any. */
async function dataUrlToFrame(url: string, region: Region | null): Promise<Frame> {
  const bmp = await createImageBitmap(await (await fetch(url)).blob());
  const r = region ?? { x: 0, y: 0, w: bmp.width, h: bmp.height };
  const canvas = new OffscreenCanvas(r.w, r.h);
  const ctx = canvas.getContext("2d")!;
  ctx.drawImage(bmp, r.x, r.y, r.w, r.h, 0, 0, r.w, r.h);
  const img = ctx.getImageData(0, 0, r.w, r.h);
  return { width: r.w, height: r.h, data: img.data };
}

interface PoolEntry { name: string; urls?: string[]; game?: string; yaml_url?: string; fingerprints?: Record<string, string> | number }

/** The pool entry for this tab: by site first, then by what the screen looks like (nearest fingerprint under the threshold). */
function poolMatch(pool: { packs: PoolEntry[] }, url: string, frame: Frame | null, threshold = 40): { hit: PoolEntry; how: string } | null {
  const here = url.toLowerCase();
  const byUrl = pool.packs.find((p) => (p.urls ?? []).some((u) => u && here.includes(u.toLowerCase())));
  if (byUrl) return { hit: byUrl, how: "site" };
  if (!frame) return null;
  const fp = fingerprint(frame);
  let best: { d: number; p: PoolEntry } | null = null;
  for (const p of pool.packs) {
    if (!p.fingerprints || typeof p.fingerprints !== "object") continue;
    for (const b64 of Object.values(p.fingerprints)) {
      try { const d = fpDistance(fp, fpFromBase64(b64)); if (!best || d < best.d) best = { d, p }; } catch { /* a bad entry */ }
    }
  }
  return best && best.d <= threshold ? { hit: best.p, how: `screen, distance ${best.d.toFixed(0)}` } : null;
}

/** The pool: packs the project (and later, everyone) has already learned, matched to this tab by URL or fingerprint. */
async function checkPool(store: Store) {
  const el = $("poolinfo");
  try {
    const r = await fetch(POOL_URL, { cache: "no-store" });
    if (!r.ok) throw new Error(String(r.status));
    const pool: { packs: PoolEntry[] } = await r.json();
    let frame: Frame | null = null;
    try {
      const shot = await new Promise<string>((res, rej) => chrome.tabs.captureVisibleTab({ format: "png" }, (u) => (chrome.runtime.lastError || !u ? rej(new Error(chrome.runtime.lastError?.message ?? "no capture")) : res(u))));
      frame = await dataUrlToFrame(shot, store.regions?.[originOf(tabUrl)] ?? null);
    } catch { /* the tab is not visible: match by site only */ }
    const m = poolMatch(pool, tabUrl, frame);
    if (!m) { el.textContent = `pool: ${pool.packs.length} packs, none for this site or screen`; return; }
    const hit = m.hit;
    if (BUNDLED_PACKS[hit.name] || store.packs?.[hit.name]) { el.textContent = `pool: "${hit.name}" matches this ${m.how}`; $<HTMLSelectElement>("pack").value = BUNDLED_PACKS[hit.name] ? hit.name : `${hit.name} (authored)`; return; }
    if (hit.yaml_url) {
      const y = await (await fetch(hit.yaml_url, { cache: "no-store" })).text();
      loadPack(y, hit.name);
      await save({ packs: { ...(store.packs ?? {}), [hit.name]: y } });
      await refreshPacks(await load());
      $<HTMLSelectElement>("pack").value = `${hit.name} (authored)`;
      el.textContent = `pool: installed "${hit.name}" for this ${m.how}`;
    }
  } catch (e) { el.textContent = `pool: unreachable (${(e as Error).message.slice(0, 40)})`; }
}

async function setRegionText() {
  const v = ($("regiontext") as HTMLInputElement).value.trim();
  const store = await load();
  const regions = { ...(store.regions ?? {}) };
  const key = originOf(tabUrl);
  const m = v.match(/^\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*$/);
  if (m) regions[key] = { x: +m[1], y: +m[2], w: +m[3], h: +m[4] }; else delete regions[key];
  await save({ regions });
  $("regioninfo").textContent = m ? `${m[3]}×${m[4]} at (${m[1]},${m[2]})` : "whole page";
}

function exportPack() {
  load().then((store) => {
    const name = $<HTMLSelectElement>("pack").value;
    const text = packText(store, name);
    if (!text) return;
    const blob = new Blob([text], { type: "text/yaml" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = `${name.replace(" (authored)", "")}.pack.yaml`; a.click();
    log(`exported ${a.download}: add it to packs/pool.json in the repo to share it`);
  });
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
  let ag: Agent = agent;
  const learning = ($("improve") as HTMLInputElement).checked;
  const packKey = name.replace(" (authored)", "");
  const bank: StoredBank = (store.bank ?? {})[packKey] ?? { episodes: [], incidents: [], version: 1 };
  let version = bank.version;
  let incumbent: { yaml: string; version: number } | null = null;     // set while a candidate revision is on trial
  const pastIncidents: Incident[] = [];                                 // this session's incidents with frames: a revision must not break them
  $("playtext").textContent = pack.play; ($("playtext") as HTMLTextAreaElement).value = pack.play;
  ($("rulestext") as HTMLTextAreaElement).value = pack.rules.length ? yaml.dump(pack.rules) : "";
  $<HTMLButtonElement>("play").disabled = true; $<HTMLButtonElement>("stop").disabled = false; $<HTMLButtonElement>("author").disabled = true;
  stopping = false;
  log(`playing ${pack.name} on tab ${device.tabId} with ${sensorSpec} · frame ${device.size().join("x")}${learning ? ` · learning (pack v${version}, ${bank.episodes.length} episodes banked)` : ""}`);
  const persistBank = async () => { const s = await load(); await save({ bank: { ...(s.bank ?? {}), [packKey]: bank } }); };
  const scoreRead = typeof ag.base.raw.score_read === "string" ? ag.base.raw.score_read : (ag.base.reads.score ? "score" : undefined);
  // ---- the episode loop: play until the game ends, bank it, learn from a loss, restart, keep what plays better
  for (let episodeN = bank.episodes.length + 1; ; episodeN++) {
    const records: Rec[] = [];
    const decisions: Decision[] = [];
    ag.onRecord = (rec, frame) => {
      showRec(rec);
      records.push(rec); if (records.length > 2000) records.shift();
      if (rec.choice && rec.choice !== "fallback") { decisions.push({ rec, frame }); if (decisions.length > 12) decisions.shift(); }
    };
    let last: Rec | null = null;
    try { last = await ag.run(() => stopping); }
    catch (e) { log(`error: ${(e as Error).message}`); break; }
    const ep = outcome(records, episodeN, version, scoreRead);
    log(`episode ${episodeN}: ${last.action}${last.reason ? " · " + last.reason : ""} after ${ag.tick} ticks, $${ag.totalCost.toFixed(4)}${ep.score !== null ? `, score ${ep.score}` : ""}`);
    if (stopping || !learning) break;
    bank.episodes.push(ep); if (bank.episodes.length > 60) bank.episodes.shift();
    // ---- a candidate on trial has to beat the incumbent's median episode, or it goes back
    if (incumbent) {
      const ref = medianEpisode(bank.episodes.filter((e) => e.version === incumbent!.version));
      if (ref && !betterEpisode(ref, ep) && betterEpisode(ep, ref)) {
        log(`learn: pack v${version} played worse than v${incumbent.version} (${ep.ticks} vs ${ref.ticks} ticks); reverting`);
        ag.swapPack(loadPack(incumbent.yaml, pack.name)); version = incumbent.version; ep.version = version;
      } else log(`learn: pack v${version} stays (${ep.ticks} ticks vs the incumbent's median ${ref?.ticks ?? "n/a"})`);
      incumbent = null;
    }
    // ---- a loss becomes an incident; the chat model revises the pack; the revision must replay better
    if (ep.lost && decisions.length) {
      const inc: Incident = incidentOf(decisions, ep.reason, ag.tick);
      const stored: StoredIncident = { reason: inc.reason, tick: inc.tick, at: inc.at, recs: inc.decisions.map((d) => d.rec), frames: [] };
      for (const d of inc.decisions.slice(-2)) stored.frames.push(await frameToDataUrl(d.frame));
      bank.incidents.push(stored); if (bank.incidents.length > 4) bank.incidents.shift();
      try {
        const chat = new Chat(store.keys ?? {});
        const res = await improve(chat, ag.base, inc, bank.episodes, log, { others: pastIncidents.slice() });
        pastIncidents.push(inc); if (pastIncidents.length > 4) pastIncidents.shift();
        if (res.pack) {
          incumbent = { yaml: dumpPack(ag.base.raw), version };
          version += 1; bank.version = version;
          ag.swapPack(res.pack);
          ($("playtext") as HTMLTextAreaElement).value = ag.base.play;
          ($("rulestext") as HTMLTextAreaElement).value = ag.base.rules.length ? yaml.dump(ag.base.rules) : "";
          ag.onPackChange?.(dumpPack(ag.base.raw), `tuned while playing: v${version} on trial (${res.verdict?.why})`);
        }
      } catch (e) { log(`learn: ${(e as Error).message.slice(0, 140)}`); }
    }
    await persistBank();
    if (stopping) break;
    // ---- restart: reload the tab and play again with the same device, sensor, fallback memo and pack
    $("hybrid").textContent = `episode ${episodeN} done · pack v${version}${incumbent ? " (on trial)" : ""} · restarting`;
    try { await device.reload(); } catch (e) { log(`restart failed: ${(e as Error).message}`); break; }
    const next: Agent = new Agent(ag.base, device, sensor, null);
    next.goal = ag.goal; next.fallback = ag.fallback; next.onPackChange = ag.onPackChange;
    ag = next; agent = next;
  }
  await stop();
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

let userStopped = false;      // the stop button: ends the whole go sequence, not just the current phase

/** One button. A pack from the pool or the store: play it. None: the explorer plays a minute, the author writes the
 *  pack from that demonstration, then play. The fallback and learning are on, so the loop runs until stop. */
async function go() {
  userStopped = false;
  ($("fallback") as HTMLInputElement).checked = true; ($("improve") as HTMLInputElement).checked = true;
  const store = await load();
  if (!packText(store, $<HTMLSelectElement>("pack").value)) {
    const t = await currentTab();
    if (!($("game") as HTMLInputElement).value.trim()) ($("game") as HTMLInputElement).value = (t.title ?? tabUrl).replace(/[|·—-].*$/, "").trim().slice(0, 80);
    ($("authorbox") as HTMLDetailsElement).open = true;
    log(`go: no pack for this tab: the explorer plays first, then the author writes the pack`);
    await runExplore();
    if (userStopped) return;
    if (!demo || !demo.frames.length) { log("go: no demonstration; nothing to author from"); return; }
    if ($<HTMLSelectElement>("sensor").value === "none") $<HTMLSelectElement>("sensor").value = "jev";
    await runAuthor();
    if (userStopped) return;
    if (!$<HTMLSelectElement>("pack").value.endsWith(" (authored)")) { log("go: the author did not produce a pack"); return; }
  }
  await play();
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
  $("regionset").onclick = () => setRegionText().catch((e) => log(String(e)));
  $("export").onclick = exportPack;
  if (region) ($("regiontext") as HTMLInputElement).value = `${region.x},${region.y},${region.w},${region.h}`;
  checkPool(store);
  $("play").onclick = () => play().catch((e) => log(String(e)));
  $("stop").onclick = () => { userStopped = true; stop(); };
  $("go").onclick = () => go().catch((e) => log(String(e)));
  $("apply").onclick = applyEdits;
  $("author").onclick = () => runAuthor().catch((e) => log(String(e)));
  $("record").onclick = () => toggleRecord().catch((e) => log(String(e)));
  $("explore").onclick = () => runExplore().catch((e) => log(String(e)));
  chrome.debugger.onDetach.addListener((src) => { if (src.tabId === tabId && agent) { log("debugger detached (tab closed or banner cancelled)"); stop(); } });
  log("ready");
}
main().catch((e) => log(String(e)));
