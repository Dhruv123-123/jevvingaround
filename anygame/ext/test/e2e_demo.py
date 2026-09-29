"""Demonstrations through the extension: 'record me' with real (Playwright-dispatched, trusted) inputs on the
tic-tac-toe page, then the author using that recording; then the explorer (the VLM plays for a short while) on
Connect Four. Needs ANYGAME_LLM_BASE / ANYGAME_LLM_KEY / ANYGAME_LLM_MODEL."""
import os, sys, time
from playwright.sync_api import sync_playwright

EXT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dist"))
GAMES = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "games"))
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
keys = {"llmBase": os.environ["ANYGAME_LLM_BASE"], "llmKey": os.environ["ANYGAME_LLM_KEY"], "llmModel": os.environ["ANYGAME_LLM_MODEL"]}


def wait_text(panel, sel, needle, seconds):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if needle in (panel.text_content(sel) or ""):
            return True
        time.sleep(1)
    return False


with sync_playwright() as p:
    proxy = {"server": os.environ["HTTPS_PROXY"]} if os.environ.get("HTTPS_PROXY") else None
    extra = ["--ignore-certificate-errors"] if proxy else []
    ctx = p.chromium.launch_persistent_context("/tmp/anygame-ext-profile-demo", headless=False, executable_path=CHROME if os.path.exists(CHROME) else None,
        args=["--headless=new", "--no-sandbox", f"--disable-extensions-except={EXT}", f"--load-extension={EXT}", *extra], viewport={"width": 540, "height": 560}, proxy=proxy)
    sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
    ext_id = sw.url.split("/")[2]
    game = ctx.pages[0] if ctx.pages else ctx.new_page()
    game.goto("file://" + os.path.join(GAMES, "tictactoe.html") + "?seed=8"); game.wait_for_load_state("load")
    tab_id = sw.evaluate("async () => { const [t] = await chrome.tabs.query({}); return t.id; }")
    panel = ctx.new_page()
    panel.goto(f"chrome-extension://{ext_id}/panel.html?tab={tab_id}")
    assert wait_text(panel, "#log", "ready", 15)
    panel.click("#settings summary")
    panel.fill("#k_llmBase", keys["llmBase"]); panel.fill("#k_llmKey", keys["llmKey"]); panel.fill("#k_llmModel", keys["llmModel"])
    panel.click("#savekeys"); assert wait_text(panel, "#log", "keys saved", 10)
    panel.click("#authorbox summary")
    panel.fill("#game", "Tic-tac-toe. We are X and move first by tapping a cell; the page plays O.")
    # --- record me: the human (Playwright) plays a game with trusted clicks while the panel records ---
    game.bring_to_front(); panel.click("#record")
    assert wait_text(panel, "#demoinfo", "recording", 15)
    for cell in ((270, 310), (105, 145), (435, 475), (270, 145), (105, 475)):
        game.mouse.click(*cell); time.sleep(1.2)
    game.keyboard.press("ArrowLeft"); time.sleep(0.5)
    panel.click("#record")
    assert wait_text(panel, "#demoinfo", "recorded", 15), panel.text_content("#demoinfo")
    print("demo:", (panel.text_content("#demoinfo") or "").strip())
    rec_ok = "inputs" in (panel.text_content("#demoinfo") or "")
    # --- author from the recording ---
    game.goto("file://" + os.path.join(GAMES, "tictactoe.html") + "?seed=9"); game.wait_for_load_state("load"); game.bring_to_front()
    panel.select_option("#sensor", "llm"); panel.click("#author")
    assert wait_text(panel, "#log", "author done", 1500)
    log = panel.text_content("#log") or ""
    print("author:", [l for l in log.split("\n") if l.startswith(("using a", "round", "play", "tune", "author done"))])
    au_ok = "passes its tests" in (panel.text_content("#authorinfo") or "") and "demonstration" in log
    # --- the explorer on Connect Four ---
    game.goto("file://" + os.path.join(GAMES, "connect4.html") + "?seed=3"); game.wait_for_load_state("load"); game.bring_to_front()
    panel.reload(); assert wait_text(panel, "#log", "ready", 15)
    panel.click("#authorbox summary"); panel.fill("#game", "Connect Four, we are red, click a column to drop")
    panel.click("#explore")
    assert wait_text(panel, "#demoinfo", "explored", 400), (panel.text_content("#log") or "")[-400:]
    print("explore:", (panel.text_content("#demoinfo") or "").strip())
    ex_lines = [l for l in (panel.text_content("#log") or "").split("\n") if l.startswith("explore ")]
    print("explore steps:", len(ex_lines), ex_lines[:3])
    ex_ok = len(ex_lines) >= 3
    state = game.evaluate("window.__state()")
    print("connect4 grid after exploring:", sum(1 for v in state["grid"] if v), "pieces")
    ctx.close()
    ok = rec_ok and au_ok and ex_ok
    print("RESULT", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
