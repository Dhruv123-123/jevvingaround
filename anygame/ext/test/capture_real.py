"""A game nobody wrote a pack for, reached like a user would: flappybird.io in a tab. The explorer plays it for a
while, the VLM authors a pack from that demonstration, Jev plays it with the fallback on. Screenshots of the tab
and the panel are written for the demo video; the authored pack is exported into packs/ for the pool.
Needs OPENROUTER_API_KEY and ANYGAME_LLM_BASE / ANYGAME_LLM_KEY / ANYGAME_LLM_MODEL."""
import json, os, sys, time
from playwright.sync_api import sync_playwright

EXT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dist"))
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
OUT = sys.argv[1] if len(sys.argv) > 1 else "capture"
URL = sys.argv[2] if len(sys.argv) > 2 else "https://flappybird.io/"
GAME = sys.argv[3] if len(sys.argv) > 3 else "Flappy Bird. Click (or press Space) to flap; the bird falls otherwise. Fly through the gaps between the green pipes; touching a pipe or the ground ends the game. The first click starts the game."
REGION = sys.argv[4] if len(sys.argv) > 4 else "188,0,525,650"
EXPLORE_SECONDS = int(os.environ.get("EXPLORE_SECONDS", "75"))
PLAY_SECONDS = int(os.environ.get("PLAY_SECONDS", "150"))
keys = {"openrouter": os.environ.get("OPENROUTER_API_KEY", ""), "llmBase": os.environ["ANYGAME_LLM_BASE"], "llmKey": os.environ["ANYGAME_LLM_KEY"], "llmModel": os.environ["ANYGAME_LLM_MODEL"]}


def wait_text(page, sel, needle, seconds):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if needle in (page.text_content(sel) or ""):
            return True
        time.sleep(0.5)
    return False


class Shooter:
    def __init__(self, game, panel, scene):
        self.game, self.panel, self.dir = game, panel, os.path.join(OUT, scene)
        os.makedirs(self.dir, exist_ok=True); self.n = 0; self.t0 = time.time(); self.meta = []

    def shot(self, note=""):
        self.n += 1
        try:
            self.game.screenshot(path=os.path.join(self.dir, f"g{self.n:05d}.png"))
            self.panel.screenshot(path=os.path.join(self.dir, f"p{self.n:05d}.png"))
            self.meta.append({"n": self.n, "t": round(time.time() - self.t0, 2), "hybrid": (self.panel.text_content("#hybrid") or "").strip(),
                              "action": (self.panel.text_content("#action") or "").strip(), "note": note,
                              "log_tail": (self.panel.text_content("#log") or "").strip().split("\n")[-1],
                              "meta": (self.panel.text_content("#meta") or "").strip()})
        except Exception as e:  # noqa: BLE001
            self.meta.append({"n": self.n, "t": round(time.time() - self.t0, 2), "error": str(e)[:80]})

    def run_until(self, predicate, seconds, period=0.5, note=""):
        t0 = time.time()
        while time.time() - t0 < seconds:
            self.shot(note)
            if predicate():
                return True
            time.sleep(period)
        return False

    def save(self):
        json.dump(self.meta, open(os.path.join(self.dir, "meta.json"), "w"), indent=1)


with sync_playwright() as p:
    proxy = {"server": os.environ["HTTPS_PROXY"]} if os.environ.get("HTTPS_PROXY") else None
    extra = ["--ignore-certificate-errors"] if proxy else []
    ctx = p.chromium.launch_persistent_context("/tmp/anygame-ext-profile-real", headless=False, executable_path=CHROME if os.path.exists(CHROME) else None,
        args=["--headless=new", "--no-sandbox", f"--disable-extensions-except={EXT}", f"--load-extension={EXT}", *extra], viewport={"width": 900, "height": 700}, proxy=proxy)
    sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
    ext_id = sw.url.split("/")[2]
    game = ctx.pages[0] if ctx.pages else ctx.new_page()
    game.goto(URL, wait_until="domcontentloaded"); time.sleep(4)
    tab_id = sw.evaluate("async () => { const [t] = await chrome.tabs.query({}); return t.id; }")
    panel = ctx.new_page(); panel.set_viewport_size({"width": 480, "height": 680})
    panel.goto(f"chrome-extension://{ext_id}/panel.html?tab={tab_id}")
    assert wait_text(panel, "#log", "ready", 15)
    panel.click("#settings summary")
    panel.fill("#k_openrouter", keys["openrouter"]); panel.fill("#k_llmBase", keys["llmBase"]); panel.fill("#k_llmKey", keys["llmKey"]); panel.fill("#k_llmModel", keys["llmModel"])
    panel.click("#savekeys"); assert wait_text(panel, "#log", "keys saved", 10); panel.click("#settings summary")
    panel.fill("#regiontext", REGION); panel.click("#regionset"); time.sleep(0.5)
    sh = Shooter(game, panel, "real")
    sh.shot("open")
    print("pool:", (panel.text_content("#poolinfo") or "").strip())
    panel.click("#authorbox summary"); panel.fill("#game", GAME); sh.shot("describe")
    # --- the explorer plays first: that is the demonstration ---
    game.bring_to_front(); panel.click("#explore")
    sh.run_until(lambda: "explored" in (panel.text_content("#demoinfo") or "") or "explore:" in (panel.text_content("#log") or "").split("\n")[-1], EXPLORE_SECONDS + 60, period=1.0, note="exploring")
    print("explore:", (panel.text_content("#demoinfo") or "").strip())
    # --- author from it ---
    game.reload(); time.sleep(4); game.bring_to_front()
    panel.select_option("#sensor", "jev"); panel.click("#author")
    sh.run_until(lambda: "author done" in (panel.text_content("#log") or ""), 1800, period=1.5, note="authoring")
    info = (panel.text_content("#authorinfo") or "").strip()
    print("author:", info, [l for l in (panel.text_content("#log") or "").split("\n") if l.startswith(("using a", "round", "play", "tune"))])
    # --- Jev plays it, fallback on ---
    game.reload(); time.sleep(4); game.bring_to_front()
    panel.click("#play")
    sh.run_until(lambda: False, PLAY_SECONDS, period=0.4, note="playing")
    if panel.is_enabled("#stop"): panel.click("#stop")
    sh.shot("stopped"); sh.save()
    # --- export the authored pack for the pool ---
    sel = panel.locator("#pack").input_value()
    yaml_text = panel.evaluate if False else None
    with panel.expect_download() as dl:
        panel.click("#export")
    path = os.path.join(OUT, "real", "authored.pack.yaml"); dl.value.save_as(path)
    print("exported", sel, "→", path, "| passes:", "passes its tests" in info)
    print("log tail:", (panel.text_content("#log") or "").strip().split("\n")[-6:])
    ctx.close()
