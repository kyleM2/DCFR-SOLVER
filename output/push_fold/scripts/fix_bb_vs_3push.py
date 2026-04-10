#!/usr/bin/env python3
"""
fix_bb_vs_3push.py

Fixes BB's calling range when facing CO+BTN+SB all-in in the 4-max 8bb push/fold game.
Uses Monte Carlo equity calculation vs the 3 opponents' (well-converged) push ranges.

Breakeven: BB must call 14 chips into a 64-chip pot => 14/64 = 21.875%

Usage:
    python3 fix_bb_vs_3push.py [--trials N] [--seed S]
"""

import json
import copy
import argparse
import sys
import numpy as np

try:
    import eval7
except ImportError:
    print("ERROR: eval7 not installed. Run: pip install eval7")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RANKS = "23456789TJQKA"
SUITS = "cdhs"

BREAKEVEN = 14.0 / 64.0  # 0.21875

# For interpolation zone: ±0.5% around breakeven
INTERP_LOW  = BREAKEVEN - 0.005
INTERP_HIGH = BREAKEVEN + 0.005

# Pre-create all 52 eval7.Card objects (index = rank*4 + suit)
CARD_TABLE = [eval7.Card(RANKS[r] + SUITS[s]) for r in range(13) for s in range(4)]

# ---------------------------------------------------------------------------
# Canonical hand → list of (card_int, card_int) combos
# ---------------------------------------------------------------------------

def combos_for_hand(hand_str: str) -> list:
    combos = []
    if len(hand_str) == 2:
        r = hand_str[0]
        ri = RANKS.index(r)
        cards = [ri * 4 + s for s in range(4)]
        for i in range(4):
            for j in range(i + 1, 4):
                combos.append((cards[i], cards[j]))
    elif hand_str[2] == 's':
        r1i, r2i = RANKS.index(hand_str[0]), RANKS.index(hand_str[1])
        for s in range(4):
            c1, c2 = r1i * 4 + s, r2i * 4 + s
            combos.append((min(c1, c2), max(c1, c2)))
    elif hand_str[2] == 'o':
        r1i, r2i = RANKS.index(hand_str[0]), RANKS.index(hand_str[1])
        for s1 in range(4):
            for s2 in range(4):
                if s1 != s2:
                    c1, c2 = r1i * 4 + s1, r2i * 4 + s2
                    combos.append((min(c1, c2), max(c1, c2)))
    else:
        raise ValueError(f"Unknown hand format: {hand_str}")
    return combos


def num_combos(hand_str: str) -> int:
    if len(hand_str) == 2:
        return 6
    elif hand_str[2] == 's':
        return 4
    else:
        return 12


# ---------------------------------------------------------------------------
# Range → numpy arrays for fast sampling
# ---------------------------------------------------------------------------

def build_range_arrays(range_dict: dict):
    """
    Returns (combos_c1, combos_c2, weights) as numpy arrays.
    combos_c1[i], combos_c2[i] = the two cards of combo i.
    weights[i] = push frequency for that combo.
    """
    c1_list, c2_list, w_list = [], [], []
    for hand_str, freq in range_dict.items():
        if freq <= 0.0001:
            continue
        for combo in combos_for_hand(hand_str):
            c1_list.append(combo[0])
            c2_list.append(combo[1])
            w_list.append(freq)
    return np.array(c1_list, dtype=np.int32), np.array(c2_list, dtype=np.int32), np.array(w_list, dtype=np.float64)


def sample_from_range(c1s, c2s, weights, blocked_mask, rng_np):
    """
    Sample a combo from range arrays, excluding blocked cards.
    blocked_mask: numpy bool array of size 52, True = blocked.
    Returns (card1, card2) or None.
    """
    valid = ~blocked_mask[c1s] & ~blocked_mask[c2s]
    if not np.any(valid):
        return None
    w = weights * valid
    total = w.sum()
    if total <= 0:
        return None
    w /= total
    idx = rng_np.choice(len(w), p=w)
    return int(c1s[idx]), int(c2s[idx])


# ---------------------------------------------------------------------------
# Equity calculation (optimized)
# ---------------------------------------------------------------------------

def compute_equity(
    bb_hand_str: str,
    co_arrays: tuple,
    btn_arrays: tuple,
    sb_arrays: tuple,
    num_trials: int,
    rng_np: np.random.Generator,
) -> float:
    co_c1, co_c2, co_w = co_arrays
    btn_c1, btn_c2, btn_w = btn_arrays
    sb_c1, sb_c2, sb_w = sb_arrays

    bb_all_combos = combos_for_hand(bb_hand_str)
    bb_n = len(bb_all_combos)
    deck = np.arange(52, dtype=np.int32)

    wins = 0.0
    valid_trials = 0
    blocked_mask = np.zeros(52, dtype=bool)

    for _ in range(num_trials):
        # 1. BB combo
        bb_combo = bb_all_combos[rng_np.integers(bb_n)]
        blocked_mask[:] = False
        blocked_mask[bb_combo[0]] = True
        blocked_mask[bb_combo[1]] = True

        # 2. CO
        co_combo = sample_from_range(co_c1, co_c2, co_w, blocked_mask, rng_np)
        if co_combo is None:
            continue
        blocked_mask[co_combo[0]] = True
        blocked_mask[co_combo[1]] = True

        # 3. BTN
        btn_combo = sample_from_range(btn_c1, btn_c2, btn_w, blocked_mask, rng_np)
        if btn_combo is None:
            continue
        blocked_mask[btn_combo[0]] = True
        blocked_mask[btn_combo[1]] = True

        # 4. SB
        sb_combo = sample_from_range(sb_c1, sb_c2, sb_w, blocked_mask, rng_np)
        if sb_combo is None:
            continue
        blocked_mask[sb_combo[0]] = True
        blocked_mask[sb_combo[1]] = True

        # 5. Deal board from remaining cards
        remaining = deck[~blocked_mask]
        board_idx = rng_np.choice(len(remaining), 5, replace=False)
        board_cards = remaining[board_idx]

        # 6. Evaluate with pre-built Card table
        b0, b1, b2, b3, b4 = CARD_TABLE[board_cards[0]], CARD_TABLE[board_cards[1]], \
                              CARD_TABLE[board_cards[2]], CARD_TABLE[board_cards[3]], \
                              CARD_TABLE[board_cards[4]]

        bb_val  = eval7.evaluate([CARD_TABLE[bb_combo[0]],  CARD_TABLE[bb_combo[1]],  b0,b1,b2,b3,b4])
        co_val  = eval7.evaluate([CARD_TABLE[co_combo[0]],  CARD_TABLE[co_combo[1]],  b0,b1,b2,b3,b4])
        btn_val = eval7.evaluate([CARD_TABLE[btn_combo[0]], CARD_TABLE[btn_combo[1]], b0,b1,b2,b3,b4])
        sb_val  = eval7.evaluate([CARD_TABLE[sb_combo[0]],  CARD_TABLE[sb_combo[1]],  b0,b1,b2,b3,b4])

        best = max(bb_val, co_val, btn_val, sb_val)
        if bb_val == best:
            winners = (1 + (co_val == best) + (btn_val == best) + (sb_val == best))
            wins += 1.0 / winners

        valid_trials += 1

    if valid_trials == 0:
        return 0.0
    return wins / valid_trials


# ---------------------------------------------------------------------------
# Corrected frequency from equity
# ---------------------------------------------------------------------------

def equity_to_freq(equity: float) -> float:
    if equity > INTERP_HIGH:
        return 1.0
    elif equity < INTERP_LOW:
        return 0.0
    else:
        # Linear interpolation over 1% band
        return (equity - INTERP_LOW) / (INTERP_HIGH - INTERP_LOW)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fix BB calling range vs CO+BTN+SB push")
    parser.add_argument("--trials", type=int, default=100_000,
                        help="Monte Carlo trials per hand (default: 100000)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed (default: 42)")
    parser.add_argument("--input", type=str,
                        default="/Users/kyle/BP/solver/DCFR-SOLVER/output/push_fold/4p_8bb_1b.json",
                        help="Input JSON path")
    parser.add_argument("--output", type=str,
                        default="/Users/kyle/BP/solver/DCFR-SOLVER/output/push_fold/4p_8bb_1b_fixed.json",
                        help="Output JSON path")
    args = parser.parse_args()

    rng_np = np.random.default_rng(args.seed)

    print(f"Loading {args.input} ...")
    with open(args.input) as f:
        data = json.load(f)

    # -----------------------------------------------------------------------
    # Extract push ranges
    # -----------------------------------------------------------------------

    def get_situation(position_name: str, facing: str) -> dict:
        for pos in data["positions"]:
            if pos["name"] == position_name:
                for sit in pos["situations"]:
                    if sit["facing"] == facing:
                        return {h["hand"]: h["push"] for h in sit["hands"]}
        raise KeyError(f"Not found: {position_name} / {facing}")

    co_range  = get_situation("CO",  "no action")
    btn_range = get_situation("BTN", "CO push")
    sb_range  = get_situation("SB",  "CO+BTN push")

    # Pre-build numpy arrays for fast sampling
    co_arrays  = build_range_arrays(co_range)
    btn_arrays = build_range_arrays(btn_range)
    sb_arrays  = build_range_arrays(sb_range)

    print(f"CO  'no action'    combos: {len(co_arrays[0])}, "
          f"mean push: {sum(co_range.values())/len(co_range):.3f}")
    print(f"BTN 'CO push'      combos: {len(btn_arrays[0])}, "
          f"mean push: {sum(btn_range.values())/len(btn_range):.3f}")
    print(f"SB  'CO+BTN push'  combos: {len(sb_arrays[0])}, "
          f"mean push: {sum(sb_range.values())/len(sb_range):.3f}")

    # -----------------------------------------------------------------------
    # Get BB's current CO+BTN+SB push situation
    # -----------------------------------------------------------------------

    bb_situation_hands = None
    bb_sit_obj = None
    for pos in data["positions"]:
        if pos["name"] == "BB":
            for sit in pos["situations"]:
                if sit["facing"] == "CO+BTN+SB push":
                    bb_situation_hands = {h["hand"]: h["push"] for h in sit["hands"]}
                    bb_sit_obj = sit
                    break

    if bb_situation_hands is None:
        print("ERROR: Could not find BB 'CO+BTN+SB push' situation")
        sys.exit(1)

    hand_order = [h["hand"] for h in bb_sit_obj["hands"]]

    print(f"\nBreakeven equity: {BREAKEVEN*100:.3f}%")
    print(f"Trials per hand: {args.trials:,}")
    print(f"Seed: {args.seed}")
    print(f"\nRunning Monte Carlo for {len(hand_order)} hands...\n")

    # -----------------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------------
    print(f"{'Hand':<8} | {'Solver%':>8} | {'Equity%':>8} | {'EV(chips)':>10} | {'Corrected%':>10} | Change")
    print("-" * 72)

    corrected_hands = []
    num_changed = 0

    for hand_str in hand_order:
        solver_freq = bb_situation_hands[hand_str]

        equity = compute_equity(
            hand_str, co_arrays, btn_arrays, sb_arrays,
            num_trials=args.trials, rng_np=rng_np
        )

        # EV = equity * 64 - 14  (chips gained by calling vs folding 0)
        ev_chips = equity * 64.0 - 14.0

        corrected_freq = equity_to_freq(equity)

        changed = abs(corrected_freq - solver_freq) > 0.01
        if changed:
            num_changed += 1

        change_str = "FIXED" if changed else "ok"

        print(f"{hand_str:<8} | {solver_freq*100:>8.2f} | {equity*100:>8.2f} | "
              f"{ev_chips:>+10.2f} | {corrected_freq*100:>10.2f} | {change_str}")

        corrected_hands.append({"hand": hand_str, "push": round(corrected_freq, 6)})

    print("-" * 72)
    print(f"\nTotal hands changed: {num_changed} / {len(hand_order)}")

    # -----------------------------------------------------------------------
    # Write fixed JSON
    # -----------------------------------------------------------------------
    fixed_data = copy.deepcopy(data)

    for pos in fixed_data["positions"]:
        if pos["name"] == "BB":
            for sit in pos["situations"]:
                if sit["facing"] == "CO+BTN+SB push":
                    # Recompute push_pct from corrected hands (weighted by combos)
                    total_w = 0.0
                    total_push = 0.0
                    for h in corrected_hands:
                        nc = num_combos(h["hand"])
                        total_w += nc
                        total_push += nc * h["push"]
                    new_push_pct = round(total_push / total_w * 100, 1) if total_w > 0 else 0.0
                    sit["hands"] = corrected_hands
                    sit["push_pct"] = new_push_pct
                    print(f"\nUpdated BB 'CO+BTN+SB push' push_pct: {sit['push_pct']:.1f}% "
                          f"(was {bb_sit_obj['push_pct']:.1f}%)")
                    break

    with open(args.output, "w") as f:
        json.dump(fixed_data, f, indent=2)

    print(f"Written: {args.output}")


if __name__ == "__main__":
    main()
