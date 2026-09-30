#!/usr/bin/env bash
# Prove the image: unit tests, fixture evals, a pixel play, a state-stream play and a desktop play, all inside the
# container. Usage: scripts/test-image.sh [image]   (OPENROUTER_API_KEY in the environment adds a Jev run)
set -euo pipefail
IMG="${1:-anygame:test}"
run() { docker run --rm --entrypoint "" -e OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}" -e HTTPS_PROXY="${HTTPS_PROXY:-}" -e REQUESTS_CA_BUNDLE="${REQUESTS_CA_BUNDLE:-}" "$IMG" "$@"; }
echo "== unit tests";            run python -m pytest test -x -q --ignore=test/e2e_screen.py --ignore=test/e2e_stream.py
echo "== fixture evals";         for p in snake connect4 tetris snake-state; do run anygame eval "$p" | tail -1; done
echo "== pixels: web://";        run anygame play snake --device "web://games/snake.html?seed=4&tick=700" --sensor random:3 --no-hud --max-ticks 30 | grep -E '"ticks"|"reason"'
echo "== a state stream";        run python test/e2e_stream.py random:3 30 | tail -1
echo "== the desktop device";    run xvfb-run -a -s "-screen 0 1024x768x24" python test/e2e_screen.py random:3 30 | tail -1
if [ -n "${OPENROUTER_API_KEY:-}" ]; then
  echo "== Jev through the desktop device"; run xvfb-run -a -s "-screen 0 1024x768x24" env SNAKE_TICK=700 python test/e2e_screen.py jev 120 | tail -2
fi
echo "image ok: $IMG"
