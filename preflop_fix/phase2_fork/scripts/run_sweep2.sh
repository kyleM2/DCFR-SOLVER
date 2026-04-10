#!/usr/bin/env bash
# Phase 2 extended sweep: Capped / Shift / Quadratic / PerGap modes.
#
# Rationale (see AUDIT.md for first sweep):
#   - Flat tax at any base fails because it tax-penalizes SB (OOP every
#     hand) too much, collapsing SB RFI.
#   - Shift(N) zeros tax for low gaps and preserves SB-vs-BB (gap=1) at 0.
#   - Capped(N) clamps the high end so BTN doesn't get double-rewarded.
#   - PerGap allows explicit sculpting of per-position tax.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
BIN="$ROOT/target/release/preflop_fixed"
OUT="$ROOT/preflop_fix/phase2_fork/results"
mkdir -p "$OUT"

ITER=2000000
SEED=42

run () {
  local label=$1
  local mode=$2
  local base=$3
  "$BIN" \
    --stack 100 --players 6 --iterations "$ITER" --seed "$SEED" \
    --tax-mode "$mode" --base-tax "$base" \
    --output       "$OUT/${label}.bin" \
    --chart-output "$OUT/${label}.json" \
    > "$OUT/${label}.log" 2>&1
  echo "${label} done"
}

echo "Extended sweep launching..."

# Shift(1): zero SB-vs-BB tax, preserve linear BTN bonus
run shift1_010  "shift:1"  0.10 &
run shift1_015  "shift:1"  0.15 &
run shift1_020  "shift:1"  0.20 &

# Shift(2): more aggressive — also zero HJ-vs-UTG
run shift2_015  "shift:2"  0.15 &
run shift2_020  "shift:2"  0.20 &

# Capped(2): clamps gap>=2 at base, only gap=1 halved.
# Equivalent to Flat but with SB-vs-BB at base/2.
run capped2_010 "capped:2" 0.10 &

# Capped(3): gap>=3 at base, gap=1,2 linearly reduced
run capped3_015 "capped:3" 0.15 &

wait
echo "Shift/Capped batch done."

# Quadratic: sublinear in gap
run quad_020 "quadratic" 0.20 &
run quad_025 "quadratic" 0.25 &

# PerGap tuned: custom shape to let BTN get more than CO
# but protect SB-vs-BB and keep HJ-vs-UTG mild
#   gap=0: 0, gap=1: 0 (protect SB vs BB, HJ vs UTG),
#   gap=2: 0.3, gap=3: 0.6, gap=4: 0.85, gap=5: 1.0
run pergap_a_015 "pergap:0,0,0.3,0.6,0.85,1.0" 0.15 &
run pergap_a_020 "pergap:0,0,0.3,0.6,0.85,1.0" 0.20 &

# PerGap variant: protect SB vs BB only (gap=1 = 0),
#   gap=2: 0.4, gap=3: 0.7, gap=4: 0.9, gap=5: 1.0
run pergap_b_015 "pergap:0,0,0.4,0.7,0.9,1.0" 0.15 &
run pergap_b_020 "pergap:0,0,0.4,0.7,0.9,1.0" 0.20 &

wait
echo "All extended sweep runs complete."
