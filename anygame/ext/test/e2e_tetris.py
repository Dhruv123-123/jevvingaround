"""End to end in headless Chromium: load the unpacked extension, open the tic-tac-toe page, open the panel for
that tab with the random sensor, press play, and check the page's own state shows moves were made."""
import json, os, sys, time
from playwright.sync_api import sync_playwright

EXT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dist"))
GAME = "file://" + os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "games", "tetris.html")) + "?seed=7&level=1"
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context("/tmp/anygame-ext-profile", headless=False, executable_path=CHROME if os.path.exists(CHROME) else None,
        args=["--headless=new", "--no-sandbox", f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"], viewport={"width": 540, "height": 560})
    sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
    ext_id = sw.url.split("/")[2]
    game = ctx.pages[0] if ctx.pages else ctx.new_page()
    game.goto(GAME); game.wait_for_load_state("load")
    # the panel page needs the game tab's id: ask the extension for it
    tab_id = sw.evaluate("async () => { const [t] = await chrome.tabs.query({}); return t.id; }")
    panel = ctx.new_page()
    panel.goto(f"chrome-extension://{ext_id}/panel.html?tab={tab_id}")
    panel.wait_for_function("document.getElementById('log').textContent.includes('ready')", timeout=15000)
    # the pool lookup runs after 'ready' and may select a pack itself: let it finish before choosing ours
    panel.wait_for_function("() => !document.getElementById('poolinfo').textContent.includes('checking')", timeout=15000)
    panel.select_option("#pack", "tetris"); panel.select_option("#sensor", "random")
    game.bring_to_front()
    panel.click("#play")
    deadline = time.time() + 60
    state = {}
    while time.time() < deadline:
        state = game.evaluate("window.__state()")
        if state.get("over") or sum(len(r) for r in state["grid"]) >= 12:
            break
        time.sleep(1)
    log = panel.text_content("#log")
    print("panel log tail:", log.strip().split("\n")[-3:])
    print("game state:", json.dumps(state))
    ok = sum(len(r) for r in state["grid"]) >= 8
    print("RESULT", "PASS" if ok else "FAIL")
    ctx.close()
    sys.exit(0 if ok else 1)
