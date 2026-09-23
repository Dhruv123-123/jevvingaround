# jevvingaround

Experiments with [TypeSafe Jev](https://typesafe.ai), the non-autoregressive "System One" decision model:
one state, many typed questions, one ~100 ms forward pass, no generated text.

- [`interlock/`](interlock/) — **Interlock.** A sub-perceptual failsafe before irreversible actions, on one engine:
  Gmail and Slack (browser extension, scores the draft while you type so the click costs 0 ms), AI-agent tool
  calls (an MCP proxy that wraps any server), the shell (zsh/bash), `git push` (pre-push hook), and payments
  (an HTTP gate that fails closed).
