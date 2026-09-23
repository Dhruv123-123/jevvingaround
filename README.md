# jevvingaround

Experiments with [TypeSafe Jev](https://typesafe.ai), the non-autoregressive "System One" decision model:
one state, many typed questions, one ~100 ms forward pass, no generated text.

- [`interlock/`](interlock/) — **Interlock for Gmail.** A sub-perceptual pre-send gate: Jev scores the draft
  while you type; the verdict for the exact draft you send is already cached when you click. Surface-agnostic
  engine underneath (git / shell / agent tool-call gates are the same code with a different state compiler).
