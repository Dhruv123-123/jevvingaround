# jevvingaround

Experiments with [TypeSafe Jev](https://typesafe.ai), the non-autoregressive "System One" decision model:
one state, many typed questions, one ~100 ms forward pass, no generated text.

- [`interlock/`](interlock/) — **Interlock.** A sub-perceptual failsafe before irreversible actions, on one engine:
  Gmail and Slack (browser extension, scores the draft while you type so the click costs 0 ms), AI-agent tool
  calls (an MCP proxy that wraps any server), the shell (zsh/bash), `git push` (pre-push hook), and payments
  (an HTTP gate that fails closed).
- [`anygame/`](anygame/) — **One paragraph, any game.** A pack (zones, reads, actions, a paragraph on how to play,
  tests) describes a game; Jev plays it live at ~4 ticks/s with no model trained. Layered perception (colours,
  bars, templates, OCR, open-vocab), a typed action set, a HUD with belief bars. `docker compose up` plays 2048
  in the container; `DEVICE=adb://<phone>` plays your phone.
