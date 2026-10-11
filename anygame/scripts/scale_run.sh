#!/usr/bin/env bash
# Many episodes across the bundled games, one bench per game and decider, games in parallel; every log carries the
# page's own state so scripts/check_truth.py can grade perception afterwards.
#   scripts/scale_run.sh <out dir> [deciders] [seeds]
#   deciders: comma-separated sensor specs (default jev); "clm" starts test/clm_stub.py when nothing serves :8700
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=${1:?out dir}; DECIDERS=${2:-jev}; SEEDS=${3:-1,2,3,4,5,6,7,8}
mkdir -p "$OUT"
export ANYGAME_LOG_TRUTH=1
if [[ ",$DECIDERS," == *",clm,"* ]] && ! curl -s -m 1 http://127.0.0.1:8700/health >/dev/null; then
  python3 test/clm_stub.py 8700 >/dev/null 2>&1 & STUB=$!; trap 'kill $STUB' EXIT; sleep 1
fi
GAMES=(
  "snake|web://games/snake.html?seed={seed}&tick=700#state=window.__state()|400"
  "connect4|web://games/connect4.html?seed={seed}#state=window.__state()|60"
  "2048|web://games/2048.html?seed={seed}#state=window.__state()|300"
  "tetris|web://games/tetris.html?seed={seed}&level=5#state=window.__state()|400"
)
for spec in "${GAMES[@]}"; do
  IFS='|' read -r pack device cap <<<"$spec"
  (
    for d in ${DECIDERS//,/ }; do
      anygame bench "$pack" --device "$device" --sensor "$d" --seeds "$SEEDS" --max-ticks "$cap" \
        --out "$OUT/logs" --append "$OUT/summary.jsonl" >"$OUT/$pack-${d//[:\/]/_}.json" 2>"$OUT/$pack-${d//[:\/]/_}.err" \
        || echo "bench $pack $d exited $?" >>"$OUT/crashes.txt"
    done
  ) &
done
wait
python3 scripts/check_truth.py --settled --json "$OUT"/logs/*.jsonl >"$OUT/perception.json"
echo "done: $OUT"
