#!/usr/bin/env bash
# Phase 2 Shift1 fine-tune: search for sweet spot between 0.10 and 0.15
# where BTN lands in [45,51], hand anomalies stay low, and SB survives.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
BIN="$ROOT/target/release/preflop_fixed"
OUT="$ROOT/preflop_fix/phase2_fork/results"

ITER=2000000
SEED=42

run () {
  local label=$1
  local base=$2
  "$BIN" \
    --stack 100 --players 6 --iterations "$ITER" --seed "$SEED" \
    --tax-mode "shift:1" --base-tax "$base" \
    --output       "$OUT/${label}.bin" \
    --chart-output "$OUT/${label}.json" \
    > "$OUT/${label}.log" 2>&1
  echo "${label} done"
}

run shift1_011 0.11 &
run shift1_012 0.12 &
run shift1_013 0.13 &
run shift1_014 0.14 &

# Also try Shift1+Capped hybrid via PerGap:
# [0, 0, 0.5, 1.0, 1.0, 1.0] — tax flat-capped for gap>=3
"$BIN" \
  --stack 100 --players 6 --iterations "$ITER" --seed "$SEED" \
  --tax-mode "pergap:0,0,0.5,1.0,1.0,1.0" --base-tax 0.15 \
  --output       "$OUT/pergap_c_015.bin" \
  --chart-output "$OUT/pergap_c_015.json" \
  > "$OUT/pergap_c_015.log" 2>&1 &

wait
echo "Fine-tune runs complete."
