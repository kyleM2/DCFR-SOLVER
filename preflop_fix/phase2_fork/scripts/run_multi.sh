#!/usr/bin/env bash
# Multi-player / multi-stack validation for Phase 2 winner (Shift1 0.15).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
BIN="$ROOT/target/release/preflop_fixed"
OUT="$ROOT/preflop_fix/phase2_fork/results"

ITER=2000000
SEED=42
MODE="shift:1"
BASE=0.15

run () {
  local label=$1
  local players=$2
  local stack=$3
  "$BIN" \
    --stack "$stack" --players "$players" --iterations "$ITER" --seed "$SEED" \
    --tax-mode "$MODE" --base-tax "$BASE" \
    --output       "$OUT/${label}.bin" \
    --chart-output "$OUT/${label}.json" \
    > "$OUT/${label}.log" 2>&1
  echo "${label} done"
}

echo "Multi-validation launch (Shift1 base_tax=0.15)..."

# 6p × multi-stack (chart extraction works)
run multi_6p_15bb  6  15 &
run multi_6p_25bb  6  25 &
run multi_6p_50bb  6  50 &
# 6p 100bb already exists as shift1_015

# Multi-player × 100bb
run multi_5p_100bb 5 100 &
run multi_4p_100bb 4 100 &
run multi_3p_100bb 3 100 &
wait
echo "Multi-validation complete."
