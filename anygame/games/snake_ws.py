"""A game with an API: Snake published as a WebSocket state stream. The page runs in headless Chromium; every
100 ms its own window.__state() goes out to every client as one JSON message, and any {"key": "ArrowUp"} message
coming back is pressed on the page. This is what a game with a mod hook or telemetry looks like to anygame:
`anygame play snake-state --device stream://ws://127.0.0.1:8765`. Usage: python games/snake_ws.py [port] [seed] [tick_ms]"""
import asyncio, json, os, sys

import websockets
from playwright.async_api import async_playwright

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
SEED = sys.argv[2] if len(sys.argv) > 2 else "4"
TICK = sys.argv[3] if len(sys.argv) > 3 else "700"
CHROME = next((c for c in [os.environ.get("CHROMIUM_PATH", ""), "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"] if c and os.path.exists(c)), None)


async def main():
    clients: set = set()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"], executable_path=CHROME)
        page = await browser.new_page(viewport={"width": 540, "height": 560})
        await page.goto("file://" + os.path.join(os.path.dirname(os.path.abspath(__file__)), "snake.html") + f"?seed={SEED}&tick={TICK}")

        async def handler(ws):
            clients.add(ws)
            try:
                async for msg in ws:
                    try:
                        m = json.loads(msg)
                    except json.JSONDecodeError:
                        continue
                    if m.get("key"):
                        await page.keyboard.press(m["key"])
                    elif m.get("reload"):
                        await page.reload()
            finally:
                clients.discard(ws)

        async def publish():
            while True:
                try:
                    st = await page.evaluate("window.__state()")
                except Exception:  # noqa: BLE001
                    st = None
                if st is not None and clients:
                    msg = json.dumps(st)
                    await asyncio.gather(*(c.send(msg) for c in list(clients)), return_exceptions=True)
                await asyncio.sleep(0.1)

        async with websockets.serve(handler, "127.0.0.1", PORT):
            print(f"snake state on ws://127.0.0.1:{PORT}  (send {{\"key\": \"ArrowUp\"}} to play)", flush=True)
            await publish()


if __name__ == "__main__":
    asyncio.run(main())
