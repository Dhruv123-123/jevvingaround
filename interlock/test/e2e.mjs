// End-to-end: real extension in real Chromium against the Gmail lookalike and the mock Jev.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "playwright";
import { startMock } from "../scripts/mock-jev.mjs";

const EXT = resolve("dist-test");
const CHROME = process.env.CHROMIUM_PATH ?? (existsSync(chromium.executablePath()) ? chromium.executablePath() : "/opt/pw-browsers/chromium-1194/chrome-linux/chrome");

let mock, ctx, extId;

before(async () => {
  mock = await startMock();
  ctx = await chromium.launchPersistentContext("", {
    headless: true,
    executablePath: CHROME,
    args: [`--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`, "--no-sandbox"],
  });
  let sw = ctx.serviceWorkers()[0] ?? (await ctx.waitForEvent("serviceworker"));
  extId = new URL(sw.url()).host;
  // the fresh install opens the options page itself; wait for it rather than racing it with our own navigation
  await ctx.waitForEvent("page", { timeout: 3000 }).catch(() => null);
  let opt = ctx.pages().find((p) => p.url().includes("options.html"));
  if (!opt) { opt = await ctx.newPage(); await opt.goto(`chrome-extension://${extId}/options.html`); }
  await opt.waitForLoadState();
  await opt.fill("#apiKey", "test-key");
  await opt.selectOption("#baseUrl", "custom");
  await opt.fill("#baseUrlCustom", mock.url);
  await opt.fill("#debounceMs", "200");
  await opt.fill("#holdSeconds", "3");
  await opt.fill("#qId", "falcon");
  await opt.fill("#qInstr", "The message reveals Project Falcon to an outsider.");
  await opt.fill("#qTrue", "Falcon is named and a recipient is external.");
  await opt.fill("#qFalse", "Falcon is not mentioned or everyone is internal.");
  await opt.fill("#qReason", "Mentions Project Falcon to an outsider ({p}%)");
  await opt.click("#addQ");
  await opt.click("#save");
  await opt.click("#test");
  await opt.waitForFunction(() => document.getElementById("testOut").textContent.startsWith("ok"));
  await opt.close();
});

after(async () => { await ctx?.close(); mock?.server.close(); });

async function openCompose() {
  const page = await ctx.newPage();
  await page.goto(`${mock.url}/fixtures/gmail.html`);
  const pill = page.getByTestId("interlock-pill");
  await pill.waitFor();
  return { page, pill, body: page.locator('[aria-label="Message Body"]'), send: page.locator("#send") };
}

async function lastRequest() { return (await (await fetch(`${mock.url}/__requests`)).json()).at(-1)?.body; }
async function requestCount() { return (await (await fetch(`${mock.url}/__requests`)).json()).length; }

test("speculative evaluation runs on a typing pause and the compiled state is what we designed", async () => {
  const { page, pill, body } = await openCompose();
  const n0 = await requestCount();
  await body.click();
  await page.keyboard.type("Hi Sam, attached is the pricing schedule. Ring me on 415-555-0199.");
  await page.waitForFunction(() => document.querySelector('[data-interlock="host"]')?.shadowRoot?.querySelector(".pill")?.getAttribute("data-level"), null, { timeout: 5000 });
  assert.ok((await requestCount()) > n0, "a speculative request was made without clicking Send");
  const req = await lastRequest();
  const s = req.state;
  assert.equal(s.action, "email.send");
  assert.equal(s.draft.subject, "Re: Q3 pricing");
  assert.deepEqual(s.draft.attachments, ["Q3_pricing_FINAL_v3.xlsx"]);
  assert.equal(s.draft.mentions_attachment_in_text, true);
  assert.match(s.draft.body_head, /<PHONE>/, "phone number redacted before leaving the browser");
  assert.doesNotMatch(s.draft.body_head, /415-555/);
  const sam = s.recipients.find((r) => r.addr === "sam@acme.com");
  assert.equal(sam.external, true);
  assert.equal(sam.first_time_ever, true);
  assert.equal(sam.in_original_thread, false);
  assert.deepEqual(s.thread.participants_not_in_recipients, ["legal@ourco.com"]);
  assert.match(s.thread.last_msg_head, /don't share the discount schedule/);
  assert.ok(s.l0_flags.includes("sensitive_attachment_name"));
  assert.ok(s.l0_flags.includes("external_recipient_present"));
  assert.ok("wrong_recipient" in req.questions && "falcon" in req.questions, "builtin + org question in the same call");
  assert.ok("most_suspicious_recipient" in req.questions, "dynamic choice over recipients");
  assert.equal(req.questions.wrong_recipient.thresholds, undefined, "policy metadata never leaves the browser");
  assert.equal(await page.evaluate(() => window.__sent), 0);
  await page.close();
});

test("proceed: a quiet draft sends straight through, served from the speculative cache", async () => {
  const { page, body, send } = await openCompose();
  await body.click();
  await page.keyboard.type("Thanks, will do.");
  await page.waitForTimeout(700);
  const n = await requestCount();
  await send.click();
  await page.waitForFunction(() => window.__sent === 1);
  assert.equal(await requestCount(), n, "click was a cache hit: no new request");
  assert.equal(await page.getByTestId("interlock-card").count(), 0);
  await page.close();
});

test("confirm: an external leak stops the send until the user says 'send anyway', and is logged", async () => {
  const { page, body, send } = await openCompose();
  await body.click();
  await page.keyboard.type("Here is the discount schedule [[confirm]]");
  await page.waitForTimeout(700);
  await send.click();
  const card = page.getByTestId("interlock-card");
  await card.waitFor();
  assert.equal(await card.getAttribute("data-kind"), "confirm");
  assert.match(await card.innerText(), /Restricted content is going outside the org \(80%\)/);
  assert.equal(await page.evaluate(() => window.__sent), 0, "send was intercepted");
  await card.getByRole("button", { name: "Send anyway" }).click();
  await page.waitForFunction(() => window.__sent === 1);
  await page.close();

  const opt = await ctx.newPage();
  await opt.goto(`chrome-extension://${extId}/options.html`);
  await opt.waitForFunction(() => document.querySelectorAll("#log tbody tr").length >= 2);
  const rows = await opt.$$eval("#log tbody tr", (trs) => trs.map((tr) => tr.innerText));
  assert.ok(rows.some((r) => /confirm\t0\.\d+\toverrode_confirm\texternal_leak 80%/.test(r)), rows.join("\n"));
  assert.ok(rows.some((r) => /proceed\t.*\tsent\t/.test(r)));
  await opt.close();
});

test("hold: a medium-risk draft gets a countdown; 'Send now' releases it", async () => {
  const { page, body, send } = await openCompose();
  await body.click();
  await page.keyboard.type("Frankly this is unacceptable [[hold]]");
  await page.waitForTimeout(700);
  await send.click();
  const card = page.getByTestId("interlock-card");
  await card.waitFor();
  assert.equal(await card.getAttribute("data-kind"), "hold");
  assert.match(await card.innerText(), /Sending in 3s/);
  await card.getByRole("button", { name: "Send now" }).click();
  await page.waitForFunction(() => window.__sent === 1);
  await page.close();
});

test("hold: the countdown sends by itself", async () => {
  const { page, body, send } = await openCompose();
  await body.click();
  await page.keyboard.type("[[hold]] again");
  await page.waitForTimeout(700);
  await send.click();
  await page.getByTestId("interlock-card").waitFor();
  await page.waitForFunction(() => window.__sent === 1, null, { timeout: 6000 });
  await page.close();
});

test("block: an L0 secret pattern blocks without the model and needs a written override", async () => {
  const { page, body, send } = await openCompose();
  await body.click();
  await page.keyboard.type("creds: AKIAIOSFODNN7EXAMPLE");
  await page.waitForTimeout(700);
  await send.click();
  const card = page.getByTestId("interlock-card");
  await card.waitFor();
  assert.equal(await card.getAttribute("data-kind"), "block");
  assert.match(await card.innerText(), /Blocked by rule: secret pattern in body/);
  const over = card.getByRole("button", { name: "Override & send" });
  assert.equal(await over.isDisabled(), true);
  await card.locator('input[data-role="why"]').fill("rotated already");
  await over.click();
  await page.waitForFunction(() => window.__sent === 1);
  await page.close();
});

test("org question fires in the same call and produces its own reason", async () => {
  const { page, body, send } = await openCompose();
  await body.click();
  await page.keyboard.type("Quick update on Project Falcon for you");
  await page.waitForTimeout(700);
  await send.click();
  const card = page.getByTestId("interlock-card");
  await card.waitFor();
  assert.match(await card.innerText(), /Mentions Project Falcon to an outsider \(85%\)/);
  await card.getByRole("button", { name: "Go back" }).click();
  assert.equal(await page.evaluate(() => window.__sent), 0);
  await page.close();
});

test("Ctrl+Enter is intercepted too", async () => {
  const { page, body } = await openCompose();
  await body.click();
  await page.keyboard.type("[[confirm]] via keyboard");
  await page.waitForTimeout(700);
  await page.keyboard.press("Control+Enter");
  await page.getByTestId("interlock-card").waitFor();
  assert.equal(await page.evaluate(() => window.__sent), 0);
  await page.close();
});

test("fail-open: when Jev is down the pill goes offline and the send still goes through", async () => {
  const { page, body, send, pill } = await openCompose();
  await fetch(`${mock.url}/__fail`, { method: "POST", body: "4" });
  await body.click();
  await page.keyboard.type("hello while offline");
  await page.waitForTimeout(700);
  await send.click();
  await page.waitForFunction(() => window.__sent === 1);
  assert.equal(await pill.getAttribute("data-offline"), "true");
  await page.close();
});
