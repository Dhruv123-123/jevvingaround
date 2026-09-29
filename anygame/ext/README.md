# anygame for Chrome

The whole runtime in a side panel. A game tab in, Jev decisions out, nothing else to install.

```bash
cd anygame/ext && npm ci && npm run build      # → dist/
```

Then `chrome://extensions` → Developer mode → Load unpacked → `anygame/ext/dist`. Open a game tab, click the
anygame button, and the side panel opens for that tab:

1. **keys and models**: your OpenRouter key (Jev) and, for authoring, a chat model endpoint (Azure or any
   OpenAI-compatible URL), key and deployment name. They live in the extension's storage and go only to those endpoints.
2. **region**: drag a box around the game once per site (the frames and the input are clipped to it). Without
   one, a bundled pack uses the box its game renders in (top-left, the pack's frame size); an authored pack uses
   the whole viewport, which is what it was authored on.
3. **pack**: pick a bundled pack, or open *no pack for this game? write one*, describe the game in a sentence and
   let the chat model author a pack against this tab (probe, write, check, play, tune). Authored packs are cached.
4. **play**. The panel shows the action, its probabilities, the beliefs, the rules that fired, latency and cost,
   and the paragraph, editable while it plays.

How it works: frames come from `Page.captureScreenshot` and input goes through `Input.dispatch*` on the
`chrome.debugger` API, so canvas games get trusted events and the tab does not have to be the active one for
capture (it does for the game's own timers). Perception, the compiler (locate, runs, around, tetris), rules, the
loop and the sensors are a TypeScript port of the Python runtime; `npm test` runs every bundled pack's fixture
tests through it. OCR, template and detector reads are not available in the extension; the bundled web packs do
not need them to play.

`test/e2e_extension.py` and `test/e2e_tetris.py` load the built extension into headless Chromium with Playwright
and have it play the bundled games with the random sensor.
