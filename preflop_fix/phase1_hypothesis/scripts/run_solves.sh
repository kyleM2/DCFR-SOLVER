#!/usr/bin/env bash
# Run postflop solves for Phase 1 hypothesis verification.
# Solves BTN vs BB on 6 representative flops at 100bb effective.
#
# Usage:
#   bash run_solves.sh [iterations]
#   bash run_solves.sh 400     # 400 iterations per flop
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$ROOT/../.." && pwd)"
BIN="$REPO/target/release/dcfr-solver"
OUT_DIR="$ROOT/results/solves"
mkdir -p "$OUT_DIR"

BTN=$(cat "$ROOT/data/ranges/btn_open_small.txt")
BB=$(cat "$ROOT/data/ranges/bb_defend_small.txt")

ITER="${1:-400}"

# Representative flops
FLOPS=(
  "Ks7d3c"
  "Jh8c4s"
  "Td9d6h"
  "Ah7s2d"
  "8h5s3c"
  "9c6c4d"
)

for flop in "${FLOPS[@]}"; do
  out="$OUT_DIR/${flop}.json"
  log="$OUT_DIR/${flop}.log"
  if [[ -f "$out" && "${FORCE:-0}" != "1" ]]; then
    echo "[skip] $flop already solved → $out (set FORCE=1 to redo)"
    continue
  fi
  echo "[solve] $flop (iter=$ITER) → $out"
  "$BIN" solve \
    --board "$flop" --street flop \
    --ip-range "$BTN" --oop-range "$BB" \
    --pot 11 --stack 195 \
    --iterations "$ITER" \
    --bet-sizes 50 --raise-sizes 100 --max-raises 2 \
    --skip-cum-strategy \
    --output "$out" > "$log" 2>&1
  echo "[ok]    $flop done"
done

echo "All solves complete. Results in $OUT_DIR"
