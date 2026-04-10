#!/usr/bin/env bash
# Phase 2 flat-tax sweep launcher.
#
# Runs preflop_fixed in parallel at 6 Flat base_tax values plus one Original
# baseline regression, all at seed=42 / 2M iter / 6p / 100bb. Output layout:
#
#   preflop_fix/phase2_fork/results/
#     flat_tax{00,05,08,10,12,15}.{bin,json,log}
#     regression_original_tax20.{bin,json,log}
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
BIN="$ROOT/target/release/preflop_fixed"
OUT="$ROOT/preflop_fix/phase2_fork/results"
mkdir -p "$OUT"

ITER=2000000
SEED=42

run_flat () {
  local label=$1
  local base=$2
  "$BIN" \
    --stack 100 --players 6 --iterations "$ITER" --seed "$SEED" \
    --tax-mode flat --base-tax "$base" \
    --output       "$OUT/flat_tax${label}.bin" \
    --chart-output "$OUT/flat_tax${label}.json" \
    > "$OUT/flat_tax${label}.log" 2>&1
  echo "flat_tax${label} done"
}

run_original () {
  "$BIN" \
    --stack 100 --players 6 --iterations "$ITER" --seed "$SEED" \
    --tax-mode original --base-tax 0.20 \
    --output       "$OUT/regression_original_tax20.bin" \
    --chart-output "$OUT/regression_original_tax20.json" \
    > "$OUT/regression_original_tax20.log" 2>&1
  echo "regression_original_tax20 done"
}

echo "Launching flat tax sweep + regression baseline in parallel..."
run_flat 00 0.00 &
run_flat 05 0.05 &
run_flat 08 0.08 &
run_flat 10 0.10 &
run_flat 12 0.12 &
run_flat 15 0.15 &
run_original &
wait
echo "All runs complete."
