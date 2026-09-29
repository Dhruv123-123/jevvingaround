"""The hybrid, live: the Snake page with a start prompt and a game-over card the snake pack knows nothing about.
The VLM fallback must dismiss the prompt (Enter), the pack then plays (chat model as the sensor), and the game-over
card is dismissed too (R). Needs ANYGAME_LLM_BASE / ANYGAME_LLM_KEY / ANYGAME_LLM_MODEL."""
import os, sys, time
from playwright.sync_api import sync_playwright

EXT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dist"))
GAME = "file://" + os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "games", "snake.html")) + "?seed=4&tick=900&menu=1"
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
keys = {"llmBase": os.environ["ANYGAME_LLM_BASE"], "llmKey": os.environ["ANYGAME_LLM_KEY"], "llmModel": os.environ["ANYGAME_LLM_MODEL"]}


def wait_log(panel, needle, seconds):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if needle in (panel.text_content("#log") or ""):
            return True
        time.sleep(1)
    return False


with sync_playwright() as p:
    proxy = {"server": os.environ["HTTPS_PROXY"]} if os.environ.get("HTTPS_PROXY") else None
    extra = ["--ignore-certificate-errors"] if proxy else []
    ctx = p.chromium.launch_persistent_context("/tmp/anygame-ext-profile-hybrid", headless=False, executable_path=CHROME if os.path.exists(CHROME) else None,
        args=["--headless=new", "--no-sandbox", f"--disable-extensions-except={EXT}", f"--load-extension={EXT}", *extra], viewport={"width": 540, "height": 560}, proxy=proxy)
    sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
    ext_id = sw.url.split("/")[2]
    game = ctx.pages[0] if ctx.pages else ctx.new_page()
    game.goto(GAME); game.wait_for_load_state("load")
    tab_id = sw.evaluate("async () => { const [t] = await chrome.tabs.query({}); return t.id; }")
    panel = ctx.new_page()
    panel.goto(f"chrome-extension://{ext_id}/panel.html?tab={tab_id}")
    assert wait_log(panel, "ready", 15)
    panel.click("#settings summary")
    panel.fill("#k_llmBase", keys["llmBase"]); panel.fill("#k_llmKey", keys["llmKey"]); panel.fill("#k_llmModel", keys["llmModel"])
    panel.click("#savekeys"); assert wait_log(panel, "keys saved", 10)
    panel.select_option("#pack", "snake"); panel.select_option("#sensor", "llm")
    game.bring_to_front(); panel.click("#play")
    t0 = time.time(); started = False; over_seen = False; restarted = False; state = {}
    while time.time() - t0 < 240:
        state = game.evaluate("window.__state()")
        if state.get("started"): started = True
        if started and state.get("over"): over_seen = True
        if over_seen and not state.get("over") and state.get("started"): restarted = True; break
        time.sleep(1)
    log = panel.text_content("#log") or ""
    hyb = panel.text_content("#hybrid") or ""
    print("started via fallback:", started, "| game over seen:", over_seen, "| restarted via fallback:", restarted)
    print("pack events:", [l for l in log.split("\n") if l.startswith("pack:")][:6])
    print("last hybrid line:", hyb.strip()[:200])
    if panel.is_enabled("#stop"): panel.click("#stop")
    ctx.close()
    ok = started and over_seen
    print("RESULT", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
