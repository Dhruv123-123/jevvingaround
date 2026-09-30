"""Footage of the extension in use, for the demo video: the game tab and the side panel screenshotted together
while it plays. Scenes: (1) Jev plays Snake with a start prompt and game-over card the pack has never seen,
the VLM fallback learns both; (2) 'record me' on tic-tac-toe, then the author writes a pack from the recording.
Writes <out>/<scene>/NNNNN.png composites (game left, panel right) plus a JSON of panel log lines with timestamps."""
import json, os, sys, time
from playwright.sync_api import sync_playwright

EXT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dist"))
GAMES = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "games"))
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
OUT = sys.argv[1] if len(sys.argv) > 1 else "capture"
keys = {"openrouter": os.environ.get("OPENROUTER_API_KEY", ""), "llmBase": os.environ["ANYGAME_LLM_BASE"], "llmKey": os.environ["ANYGAME_LLM_KEY"], "llmModel": os.environ["ANYGAME_LLM_MODEL"]}


def wait_text(page, sel, needle, seconds):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if needle in (page.text_content(sel) or ""):
            return True
        time.sleep(0.5)
    return False


class Shooter:
    """Screenshots both pages on a cadence into a scene directory, with the panel's log lines for captions."""
    def __init__(self, game, panel, scene):
        self.game, self.panel, self.dir = game, panel, os.path.join(OUT, scene)
        os.makedirs(self.dir, exist_ok=True); self.n = 0; self.t0 = time.time(); self.meta = []

    def shot(self, note=""):
        self.n += 1
        try:
            self.game.screenshot(path=os.path.join(self.dir, f"g{self.n:05d}.png"))
            self.panel.screenshot(path=os.path.join(self.dir, f"p{self.n:05d}.png"), full_page=False)
            self.meta.append({"n": self.n, "t": round(time.time() - self.t0, 2), "hybrid": (self.panel.text_content("#hybrid") or "").strip(),
                              "action": (self.panel.text_content("#action") or "").strip(), "note": note,
                              "log_tail": (self.panel.text_content("#log") or "").strip().split("\n")[-1]})
        except Exception as e:  # noqa: BLE001
            self.meta.append({"n": self.n, "t": round(time.time() - self.t0, 2), "error": str(e)[:80]})

    def run_until(self, predicate, seconds, period=0.45, note=""):
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
    ctx = p.chromium.launch_persistent_context("/tmp/anygame-ext-profile-capture", headless=False, executable_path=CHROME if os.path.exists(CHROME) else None,
        args=["--headless=new", "--no-sandbox", f"--disable-extensions-except={EXT}", f"--load-extension={EXT}", *extra], viewport={"width": 540, "height": 560}, proxy=proxy)
    sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
    ext_id = sw.url.split("/")[2]
    game = ctx.pages[0] if ctx.pages else ctx.new_page()
    game.goto("file://" + os.path.join(GAMES, "snake.html") + "?seed=4&tick=900&menu=1"); game.wait_for_load_state("load")
    tab_id = sw.evaluate("async () => { const [t] = await chrome.tabs.query({}); return t.id; }")
    panel = ctx.new_page()
    panel.set_viewport_size({"width": 420, "height": 900})
    panel.goto(f"chrome-extension://{ext_id}/panel.html?tab={tab_id}")
    assert wait_text(panel, "#log", "ready", 15)
    panel.click("#settings summary")
    panel.fill("#k_openrouter", keys["openrouter"]); panel.fill("#k_llmBase", keys["llmBase"]); panel.fill("#k_llmKey", keys["llmKey"]); panel.fill("#k_llmModel", keys["llmModel"])
    panel.click("#savekeys"); assert wait_text(panel, "#log", "keys saved", 10)
    panel.click("#settings summary")

    # ---- scene 1: Jev plays Snake; the start prompt and the game-over card go to the VLM fallback ----
    sh = Shooter(game, panel, "hybrid")
    panel.select_option("#pack", "snake"); panel.select_option("#sensor", "jev")
    sh.shot("setup"); time.sleep(0.5); sh.shot("setup")
    game.bring_to_front(); panel.click("#play")
    started = {"v": False}; over = {"v": False}; restarted = {"v": False}
    def prog():
        s = game.evaluate("window.__state()")
        if s.get("started"): started["v"] = True
        if started["v"] and s.get("over"): over["v"] = True
        if over["v"] and s.get("started") and not s.get("over"): restarted["v"] = True
        return restarted["v"]
    sh.run_until(prog, 200, note="playing")
    sh.run_until(lambda: False, 12, note="after restart")
    if panel.is_enabled("#stop"): panel.click("#stop")
    sh.shot("stopped"); sh.save()
    print("scene hybrid:", {"started": started["v"], "over": over["v"], "restarted": restarted["v"], "frames": sh.n})

    # ---- scene 2: record me on tic-tac-toe, then author from the recording ----
    game.goto("file://" + os.path.join(GAMES, "tictactoe.html") + "?seed=8"); game.wait_for_load_state("load")
    panel.reload(); assert wait_text(panel, "#log", "ready", 15)
    sh2 = Shooter(game, panel, "author")
    panel.click("#authorbox summary")
    panel.fill("#game", "Tic-tac-toe. We are X and move first by tapping a cell; the page plays O.")
    sh2.shot("describe")
    game.bring_to_front(); panel.click("#record"); assert wait_text(panel, "#demoinfo", "recording", 15)
    sh2.shot("recording")
    for cell in ((270, 310), (105, 145), (435, 475), (270, 145), (105, 475)):
        game.mouse.click(*cell); time.sleep(0.6); sh2.shot("recording"); time.sleep(0.6)
    panel.click("#record"); assert wait_text(panel, "#demoinfo", "recorded", 15); sh2.shot("recorded")
    game.goto("file://" + os.path.join(GAMES, "tictactoe.html") + "?seed=9"); game.wait_for_load_state("load"); game.bring_to_front()
    panel.select_option("#sensor", "jev"); panel.click("#author")
    sh2.run_until(lambda: "author done" in (panel.text_content("#log") or ""), 1500, period=1.0, note="authoring")
    sh2.shot("authored"); time.sleep(0.5); sh2.shot("authored")
    # play the authored pack with Jev for a few seconds
    game.goto("file://" + os.path.join(GAMES, "tictactoe.html") + "?seed=11"); game.wait_for_load_state("load"); game.bring_to_front()
    panel.click("#play"); sh2.run_until(lambda: game.evaluate("window.__state().over"), 60, note="playing authored")
    sh2.run_until(lambda: False, 3, note="playing authored")
    if panel.is_enabled("#stop"): panel.click("#stop")
    sh2.save()
    print("scene author:", {"frames": sh2.n, "info": (panel.text_content("#authorinfo") or "").strip()})
    ctx.close()
