#!/usr/bin/env bash
# From scratch, with the bundled pack held out: the explorer plays, the author writes a pack from that demonstration,
# then episodes of play with a revision after every loss. Nothing from the pool, not even lessons.
# Usage: scripts/from_scratch.sh <name> <device url> "<game in a sentence>" [episodes] [max ticks] [out dir]
set -uo pipefail
NAME="$1"; URL="$2"; GAME="$3"; EPISODES="${4:-6}"; MAX="${5:-400}"; OUT="${6:-/tmp/anygame-scratch}"
cd "$(dirname "$0")/.."
mkdir -p "$OUT/$NAME"
anygame go "$URL" --game "$GAME" --fresh --explore "${EXPLORE_SECONDS:-60}" --learn "$EPISODES" --max-ticks "$MAX" --packs "$OUT/$NAME/packs" --hud 0 --sensor jev 2>&1 | grep --line-buffered -vE "^\s*(-|[0-9]+ ×)|Warning" | tee "$OUT/$NAME/log.txt"
# a clip with whatever the loop ended with
LEARNED=$(ls "$OUT/$NAME"/packs/*/pack.learned.yaml 2>/dev/null | head -1); PACK="${LEARNED:-$(ls "$OUT/$NAME"/packs/*/pack.yaml 2>/dev/null | head -1)}"
if [ -n "$PACK" ]; then
  anygame play "$PACK" --device "$URL" --sensor jev --no-hud --max-ticks 300 --record "$OUT/$NAME/rec" --log "$OUT/$NAME/clip.jsonl" 2>&1 | grep -vE "^\s*(-|[0-9]+ ×)|Warning" | tail -3
  anygame render "$OUT/$NAME/rec" --log "$OUT/$NAME/clip.jsonl" --out "$OUT/$NAME/clip.mp4" --fps 4 2>&1 | tail -1
fi
echo "done $NAME"
