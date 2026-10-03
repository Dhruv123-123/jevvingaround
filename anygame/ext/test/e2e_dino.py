"""The bundled web-dino pack played from the extension panel on chromedino.com, in headless Chromium, the way
scripts/web_trial.py plays it from the CLI: one fresh browser per game, ads and fixed overlays hidden, and the
capture region set to where the pack expects the game (its canvas 137 px from the region's top).

    python ext/test/e2e_dino.py --games 8 --delay 400 --out DIR      # the CLM stand-in at Jev's pace
    python ext/test/e2e_dino.py --games 8 --sensor jev --out DIR     # real Jev on OpenRouter (costs money)

Needs the proxy CA in Chromium's trust store when HTTPS_PROXY is set:
    certutil -d sql:$HOME/.pki/nssdb -A -t "C,," -n proxy -i /root/.ccr/agent-proxy-ca.crt
One JSON line per game on stdout: the page's score at the crash, ticks, decider calls, how often the reflex fired."""
import argparse, json, os, shutil, socket, statistics, subprocess, sys, tempfile, time
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
EXT = os.path.join(HERE, "..", "dist")
ROOT = os.path.join(HERE, "..", "..")
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
URL = "https://chromedino.com/"
GAME_JS = """(() => { const r = Runner.instance_; return {crashed: r.crashed, playing: r.playing, speed: +r.currentSpeed.toFixed(2),
  score: r.distanceMeter.getActualDistance(r.distanceRan)}; })()"""
HIDE_JS = """() => { for (const e of document.querySelectorAll('ins.adsbygoogle, iframe, [id^=google_ads], [id^=aswift], .google-auto-placed'))
    e.style.display = 'none';
  for (const e of document.querySelectorAll('body *')) { const p = getComputedStyle(e).position;
    if ((p === 'fixed' || p === 'sticky') && !e.querySelector('canvas')) e.style.display = 'none'; } }"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def game(p, n, args, clm_base):
    profile = tempfile.mkdtemp(prefix="anygame-dino-")
    proxy = None
    if os.environ.get("HTTPS_PROXY"):
        u = urlparse(os.environ["HTTPS_PROXY"])
        proxy = {"server": f"{u.scheme}://{u.hostname}:{u.port}", "bypass": "127.0.0.1,localhost"}     # the stand-in is local
    ctx = p.chromium.launch_persistent_context(profile, headless=False, proxy=proxy, executable_path=CHROME if os.path.exists(CHROME) else None,
        args=["--headless=new", "--no-sandbox", f"--disable-extensions-except={EXT}", f"--load-extension={EXT}", "--window-size=540,900", "--hide-scrollbars"], no_viewport=True)
    try:
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
        ext_id = sw.url.split("/")[2]
        g = ctx.pages[0] if ctx.pages else ctx.new_page()
        g.goto(URL, wait_until="load", timeout=60000)
        g.wait_for_function("window.Runner && Runner.instance_", timeout=30000)
        g.wait_for_timeout(1500)
        tab_id = None
        for _ in range(50):
            tab_id = sw.evaluate("async () => { if (!globalThis.chrome || !chrome.tabs) return null; const [t] = await chrome.tabs.query({}); return t ? t.id : null; }")
            if tab_id is not None:
                break
            time.sleep(0.2)
        panel = ctx.new_page()
        panel.goto(f"chrome-extension://{ext_id}/panel.html?tab={tab_id}")
        panel.wait_for_function("document.getElementById('log').textContent.includes('ready')", timeout=15000)
        keys = {"clmBase": clm_base} if clm_base else {"openrouter": os.environ.get("OPENROUTER_API_KEY") or "proxy"}
        panel.evaluate("async (s) => { await chrome.storage.local.set(s); }", {"keys": keys})
        panel.reload()
        panel.wait_for_function("document.getElementById('log').textContent.includes('ready')", timeout=15000)
        panel.wait_for_function("() => !document.getElementById('poolinfo').textContent.includes('checking')", timeout=15000)
        panel.select_option("#pack", "web-dino"); panel.select_option("#sensor", args.sensor)
        # start the game, hide what covers it, and point the capture region at it (the pack's zones assume the
        # canvas 137 px from the top of a 540 px wide frame, as in the CLI's 540x560 viewport)
        g.bring_to_front()
        g.evaluate("window.scrollTo(0, 0)")
        g.keyboard.press("Space")
        g.wait_for_function("Runner.instance_.activated && !Runner.instance_.crashed && Runner.instance_.tRex.yPos >= 90", timeout=15000)
        g.evaluate(HIDE_JS)
        g.wait_for_timeout(100)
        x, y, w = g.evaluate("(() => { window.scrollTo(0, 0); const r = document.querySelector('canvas').getBoundingClientRect(); return [r.x, r.y, r.width]; })()")
        k = w / 540
        region = {"x": round(x), "y": round(y - 137 * k), "w": round(540 * k), "h": round(560 * k)}
        panel.evaluate("async (r) => { const s = await chrome.storage.local.get('regions'); await chrome.storage.local.set({regions: {...(s.regions || {}), [r.key]: r.region}}); }",
                       {"key": URL, "region": region})
        panel.click("#play")
        g.bring_to_front()
        t0 = time.time()
        end = None
        while time.time() - t0 < args.seconds:
            st = g.evaluate(GAME_JS)
            if st["crashed"]:
                end = st
                break
            time.sleep(0.1)
        time.sleep(1.0)
        recs = panel.evaluate("window.__anygameRecords || []")
        panel.evaluate("() => { const b = document.getElementById('stop'); if (!b.disabled) b.click(); }")
        if args.out:
            os.makedirs(args.out, exist_ok=True)
            with open(os.path.join(args.out, f"dino-{n}.jsonl"), "w") as f:
                f.writelines(json.dumps(r) + "\n" for r in recs)
        return summarize(n, recs, end, region, time.time() - t0)
    finally:
        ctx.close()
        shutil.rmtree(profile, ignore_errors=True)


def summarize(n, recs, end, region, secs):
    last = recs[-1] if recs else {}
    costs = [r["total_cost_usd"] for r in recs if r.get("total_cost_usd") is not None]
    jumps = [r for r in recs if r.get("choice") and r.get("choice") not in ("keep", "wait")]
    return {"game": n, "score": end and end["score"], "crashed": bool(end), "speed": end and end["speed"], "seconds": round(secs, 1),
            "ticks": len(recs), "fps": round((len(recs) - 1) / ((recs[-1]["t_ms"] - recs[0]["t_ms"]) / 1000), 1) if len(recs) > 1 and recs[-1].get("t_ms") else None, "end": last.get("action"), "reason": last.get("reason"),
            "decider_calls": sum(1 for r in recs if r.get("jev_ms") is not None and not r.get("skipped")),
            "asked_async": sum(1 for r in recs if r.get("asked") == "async"),
            "reflex": sum(1 for r in recs if r.get("skipped") == "reflex"),
            "moves": sum(1 for r in jumps), "choices": sorted({r["choice"] for r in jumps}),
            "perception_ms_median": statistics.median([r["perception_ms"] for r in recs]) if recs else None,
            "cost_usd": max(costs) if costs else 0, "region": region}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=8)
    ap.add_argument("--seconds", type=float, default=300)
    ap.add_argument("--sensor", default="clm", choices=["clm", "jev"])
    ap.add_argument("--delay", type=int, default=400, help="CLM_STUB_DELAY_MS for the stand-in")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    stub = clm_base = None
    if args.sensor == "clm":
        port = free_port()
        stub = subprocess.Popen([sys.executable, os.path.join(ROOT, "test", "clm_stub.py"), str(port)], env={**os.environ, "CLM_STUB_DELAY_MS": str(args.delay)}, stdout=subprocess.DEVNULL)
        clm_base = f"http://127.0.0.1:{port}"
        time.sleep(0.8)
    try:
        with sync_playwright() as p:
            for n in range(1, args.games + 1):
                for attempt in (1, 2):
                    try:
                        print(json.dumps(game(p, n, args, clm_base)), flush=True)
                        break
                    except Exception as e:  # noqa: BLE001
                        print(f"game {n} attempt {attempt}: {e}", file=sys.stderr)
    finally:
        if stub:
            stub.terminate()


if __name__ == "__main__":
    main()
