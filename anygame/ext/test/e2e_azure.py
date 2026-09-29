"""Real model calls through the extension: keys set in extension storage, the chat model (Azure) as the sensor
on Connect Four, then the in-panel author on tic-tac-toe. Needs ANYGAME_LLM_BASE / ANYGAME_LLM_KEY / ANYGAME_LLM_MODEL."""
import json, os, sys, time
from playwright.sync_api import sync_playwright

EXT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dist"))
GAMES = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "games"))
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
keys = {"llmBase": os.environ["ANYGAME_LLM_BASE"], "llmKey": os.environ["ANYGAME_LLM_KEY"], "llmModel": os.environ["ANYGAME_LLM_MODEL"]}

def wait_log(panel, needle, seconds):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if needle in (panel.text_content("#log") or ""):
            return
        time.sleep(1)
    raise TimeoutError(f"'{needle}' not seen in the panel log; tail: {(panel.text_content('#log') or '')[-300:]}")


with sync_playwright() as p:
    # this container reaches the internet only through a proxy that Chromium does not pick up from the environment;
    # a user's Chrome has direct access. The certificate flag is for the proxy's CA in the test container only.
    proxy = {"server": os.environ["HTTPS_PROXY"]} if os.environ.get("HTTPS_PROXY") else None
    extra = ["--ignore-certificate-errors"] if proxy else []
    ctx = p.chromium.launch_persistent_context("/tmp/anygame-ext-profile-azure", headless=False, executable_path=CHROME if os.path.exists(CHROME) else None,
        args=["--headless=new", "--no-sandbox", f"--disable-extensions-except={EXT}", f"--load-extension={EXT}", *extra], viewport={"width": 540, "height": 700}, proxy=proxy)
    sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
    ext_id = sw.url.split("/")[2]
    game = ctx.pages[0] if ctx.pages else ctx.new_page()
    game.goto("file://" + os.path.join(GAMES, "connect4.html") + "?seed=9"); game.wait_for_load_state("load")
    tab_id = sw.evaluate("async () => { const [t] = await chrome.tabs.query({}); return t.id; }")
    panel = ctx.new_page()
    panel.goto(f"chrome-extension://{ext_id}/panel.html?tab={tab_id}")
    wait_log(panel, "ready", 15)
    # extension pages have a script-src 'self' CSP, so no evaluate(): keys go in through the panel's own form
    panel.click("#settings summary")
    panel.fill("#k_llmBase", keys["llmBase"]); panel.fill("#k_llmKey", keys["llmKey"]); panel.fill("#k_llmModel", keys["llmModel"])
    panel.click("#savekeys"); wait_log(panel, "keys saved", 10)
    panel.select_option("#pack", "connect4"); panel.select_option("#sensor", "llm")
    game.bring_to_front(); panel.click("#play")
    t0 = time.time(); state = {}
    while time.time() - t0 < 300:
        state = game.evaluate("window.__state()")
        if state.get("over"): break
        time.sleep(2)
    print("connect4:", "red wins" if state.get("over") == 1 else "yellow wins" if state.get("over") == 2 else "draw" if state.get("over") == 3 else "unfinished", f"in {time.time()-t0:.0f}s")
    print("panel:", (panel.text_content("#meta") or "").strip())
    if panel.is_enabled("#stop"): panel.click("#stop")     # a finished game already stopped itself
    time.sleep(1)
    c4_ok = state.get("over") in (1, 3)

    # --- the author, on tic-tac-toe, from the panel ---
    game.goto("file://" + os.path.join(GAMES, "tictactoe.html") + "?seed=5"); game.wait_for_load_state("load")
    panel.reload(); wait_log(panel, "ready", 15)
    panel.click("#authorbox summary")
    panel.fill("#game", "Tic-tac-toe. We are X and move first by tapping a cell; the page plays O.")
    panel.select_option("#sensor", "llm")
    game.bring_to_front(); panel.click("#author")
    wait_log(panel, "author done", 1500)
    log = panel.text_content("#log") or ""
    print("author log:", [l for l in log.split("\n") if l.startswith(("round", "play", "tune", "author", "probed"))])
    info = panel.text_content("#authorinfo") or ""
    packs = [o.strip() for o in (panel.locator("#pack").all_inner_texts()[0] if panel.locator("#pack").count() else "").split("\n") if "(authored)" in o]
    print("authored packs in storage:", packs, "|", info)
    au_ok = "passes its tests" in info
    ctx.close()
    print("RESULT", "PASS" if (c4_ok and au_ok) else "FAIL")
    sys.exit(0 if (c4_ok and au_ok) else 1)
