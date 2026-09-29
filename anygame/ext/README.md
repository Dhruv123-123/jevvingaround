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
   the paragraph (editable while it plays), and a hybrid line: which mode, the support score, whether the screen is
   known. With *VLM fallback* on, screens the pack cannot read go to the chat model, which acts and teaches the
   pack (transients are memoised, modes are merged after verification); learned packs are saved as "<name>-learned".
   *Keep improving* tunes the pack in the background while it plays.
5. **record me** / **let the model explore**: a demonstration for the author, instead of the blind probe.

How it works: frames come from `Page.captureScreenshot` and input goes through `Input.dispatch*` on the
`chrome.debugger` API, so canvas games get trusted events and the tab does not have to be the active one for
capture (it does for the game's own timers). Perception, the compiler (locate, runs, around, tetris), rules, the
loop and the sensors are a TypeScript port of the Python runtime; `npm test` runs every bundled pack's fixture
tests through it. OCR, template and detector reads are not available in the extension; the bundled web packs do
not need them to play.

`test/e2e_extension.py`, `test/e2e_tetris.py` and `test/e2e_snake.py` load the built extension into headless
Chromium with Playwright and have it play the bundled games with the random sensor (taps, macro keys, swipes).
`test/e2e_azure.py` does it with a real model: with `ANYGAME_LLM_BASE/KEY/MODEL` set it enters the keys through
the panel's form, plays Connect Four with the chat model as the sensor (GPT-5.6 on Azure: red wins in 14 s), then
authors a tic-tac-toe pack from the panel (perception passed in one round, a tune round, the pack cached and
selected). In a container whose only route out is a proxy, the test browser is pointed at `HTTPS_PROXY`.
