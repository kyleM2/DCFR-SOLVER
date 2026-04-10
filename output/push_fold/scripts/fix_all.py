#!/usr/bin/env python3
"""
fix_all.py

Fixes 5 situations in the 4-max 8bb push/fold game:

  Group A (BB terminal decisions — pure equity calculation):
    1. BB vs CO+BTN push (SB folded)        breakeven = 14/49 = 28.571%
    2. BB vs CO+SB push  (BTN folded)       breakeven = 14/48 = 29.167%
    3. BB vs BTN+SB push (CO folded)        breakeven = 14/48 = 29.167%
    4. BB vs CO+BTN+SB push                 COPY from existing fixed file

  Group B (SB non-terminal decision):
    5. SB vs CO+BTN push                    EV comparison (push vs fold=-1)

Usage:
    python3 fix_all.py [--trials N] [--seed S]
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

# Pre-create all 52 eval7.Card objects (index = rank*4 + suit)
CARD_TABLE = [eval7.Card(RANKS[r] + SUITS[s]) for r in range(13) for s in range(4)]

INPUT_ORIG  = "/Users/kyle/BP/solver/DCFR-SOLVER/output/push_fold/4p_8bb_1b.json"
INPUT_FIXED = "/Users/kyle/BP/solver/DCFR-SOLVER/output/push_fold/4p_8bb_1b_fixed.json"
OUTPUT      = "/Users/kyle/BP/solver/DCFR-SOLVER/output/push_fold/4p_8bb_1b_fixed.json"

# ---------------------------------------------------------------------------
# Canonical hand helpers
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
            combos.append((r1i * 4 + s, r2i * 4 + s))
    elif hand_str[2] == 'o':
        r1i, r2i = RANKS.index(hand_str[0]), RANKS.index(hand_str[1])
        for s1 in range(4):
            for s2 in range(4):
                if s1 != s2:
                    combos.append((r1i * 4 + s1, r2i * 4 + s2))
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
    combos_c1[i], combos_c2[i] = the two cards of combo i (int indices).
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
    return (np.array(c1_list, dtype=np.int32),
            np.array(c2_list, dtype=np.int32),
            np.array(w_list, dtype=np.float64))


def sample_from_range(c1s, c2s, weights, blocked_mask, rng_np):
    """
    Sample a combo from range arrays, excluding blocked cards.
    blocked_mask: numpy bool array of size 52, True = blocked.
    Returns (card1_idx, card2_idx) or None.
    """
    valid = ~blocked_mask[c1s] & ~blocked_mask[c2s]
    if not np.any(valid):
        return None
    w = weights * valid
    total = w.sum()
    if total <= 0:
        return None
    w = w / total
    idx = rng_np.choice(len(w), p=w)
    return int(c1s[idx]), int(c2s[idx])


# ---------------------------------------------------------------------------
# Helper: get a situation dict from original data
# ---------------------------------------------------------------------------

def get_situation(data: dict, position_name: str, facing: str) -> dict:
    """Returns {hand_str: freq} dict."""
    for pos in data["positions"]:
        if pos["name"] == position_name:
            for sit in pos["situations"]:
                if sit["facing"] == facing:
                    return {h["hand"]: h["push"] for h in sit["hands"]}
    raise KeyError(f"Not found: {position_name} / {facing}")


def get_situation_obj(data: dict, position_name: str, facing: str):
    """Returns the raw situation dict object (with 'hands', 'push_pct', etc.)."""
    for pos in data["positions"]:
        if pos["name"] == position_name:
            for sit in pos["situations"]:
                if sit["facing"] == facing:
                    return sit
    raise KeyError(f"Not found: {position_name} / {facing}")


# ---------------------------------------------------------------------------
# Group A: BB equity vs 2 pushers
# ---------------------------------------------------------------------------

def compute_equity_2opp(
    bb_hand_str: str,
    opp1_arrays: tuple,
    opp2_arrays: tuple,
    num_trials: int,
    rng_np: np.random.Generator,
) -> float:
    """
    BB equity in 3-way pot vs 2 opponents (opp1 and opp2).
    Dead chips affect breakeven but NOT the equity calculation itself —
    equity is purely about who wins the showdown.
    """
    opp1_c1, opp1_c2, opp1_w = opp1_arrays
    opp2_c1, opp2_c2, opp2_w = opp2_arrays

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

        # 2. Opp1
        opp1_combo = sample_from_range(opp1_c1, opp1_c2, opp1_w, blocked_mask, rng_np)
        if opp1_combo is None:
            continue
        blocked_mask[opp1_combo[0]] = True
        blocked_mask[opp1_combo[1]] = True

        # 3. Opp2
        opp2_combo = sample_from_range(opp2_c1, opp2_c2, opp2_w, blocked_mask, rng_np)
        if opp2_combo is None:
            continue
        blocked_mask[opp2_combo[0]] = True
        blocked_mask[opp2_combo[1]] = True

        # 4. Deal 5-card board from remaining
        remaining = deck[~blocked_mask]
        board_idx = rng_np.choice(len(remaining), 5, replace=False)
        board_cards = remaining[board_idx]

        b0 = CARD_TABLE[board_cards[0]]
        b1 = CARD_TABLE[board_cards[1]]
        b2 = CARD_TABLE[board_cards[2]]
        b3 = CARD_TABLE[board_cards[3]]
        b4 = CARD_TABLE[board_cards[4]]

        bb_val   = eval7.evaluate([CARD_TABLE[bb_combo[0]],   CARD_TABLE[bb_combo[1]],   b0,b1,b2,b3,b4])
        opp1_val = eval7.evaluate([CARD_TABLE[opp1_combo[0]], CARD_TABLE[opp1_combo[1]], b0,b1,b2,b3,b4])
        opp2_val = eval7.evaluate([CARD_TABLE[opp2_combo[0]], CARD_TABLE[opp2_combo[1]], b0,b1,b2,b3,b4])

        best = max(bb_val, opp1_val, opp2_val)
        if bb_val == best:
            winners = 1 + (opp1_val == best) + (opp2_val == best)
            wins += 1.0 / winners

        valid_trials += 1

    if valid_trials == 0:
        return 0.0
    return wins / valid_trials


def equity_to_freq_bb(equity: float, breakeven: float) -> float:
    """Linear interpolation ±0.5% around breakeven."""
    lo = breakeven - 0.005
    hi = breakeven + 0.005
    if equity >= hi:
        return 1.0
    elif equity <= lo:
        return 0.0
    else:
        return (equity - lo) / (hi - lo)


# ---------------------------------------------------------------------------
# Group B: SB EV of pushing vs folding
# ---------------------------------------------------------------------------

def compute_sb_push_ev(
    sb_hand_str: str,
    co_arrays: tuple,
    btn_arrays: tuple,
    bb_call_range: dict,      # {hand_str: call_freq} for BB facing CO+BTN+SB push
    num_trials: int,
    rng_np: np.random.Generator,
) -> float:
    """
    SB's EV of pushing when CO and BTN have already pushed.

    If SB pushes:
      - BB may call (using bb_call_range) or fold
      - If BB folds:  3-way showdown CO+BTN+SB, pot = 16+16+16+2(BB dead) = 50
        SB net = equity_3way * 50 - 16
      - If BB calls:  4-way showdown CO+BTN+SB+BB, pot = 64
        SB net = equity_4way * 64 - 16
    SB folds EV = -1

    Returns EV(push) in chips.
    """
    co_c1,  co_c2,  co_w  = co_arrays
    btn_c1, btn_c2, btn_w = btn_arrays

    # Build BB call arrays (weighted by call freq)
    bb_c1_list, bb_c2_list, bb_w_list = [], [], []
    for hand_str, freq in bb_call_range.items():
        for combo in combos_for_hand(hand_str):
            bb_c1_list.append(combo[0])
            bb_c2_list.append(combo[1])
            bb_w_list.append(freq)
    bb_c1_arr = np.array(bb_c1_list, dtype=np.int32)
    bb_c2_arr = np.array(bb_c2_list, dtype=np.int32)
    bb_w_arr  = np.array(bb_w_list,  dtype=np.float64)

    # BB call probability (marginal, ignoring card removal for simplicity)
    total_bb_combos = sum(num_combos(h) for h in bb_call_range)
    total_bb_weighted = sum(num_combos(h) * f for h, f in bb_call_range.items())
    bb_call_prob = total_bb_weighted / total_bb_combos if total_bb_combos > 0 else 0.0

    sb_all_combos = combos_for_hand(sb_hand_str)
    sb_n = len(sb_all_combos)
    deck = np.arange(52, dtype=np.int32)

    total_ev = 0.0
    valid_trials = 0
    blocked_mask = np.zeros(52, dtype=bool)

    for _ in range(num_trials):
        # 1. SB combo
        sb_combo = sb_all_combos[rng_np.integers(sb_n)]
        blocked_mask[:] = False
        blocked_mask[sb_combo[0]] = True
        blocked_mask[sb_combo[1]] = True

        # 2. CO combo
        co_combo = sample_from_range(co_c1, co_c2, co_w, blocked_mask, rng_np)
        if co_combo is None:
            continue
        blocked_mask[co_combo[0]] = True
        blocked_mask[co_combo[1]] = True

        # 3. BTN combo
        btn_combo = sample_from_range(btn_c1, btn_c2, btn_w, blocked_mask, rng_np)
        if btn_combo is None:
            continue
        blocked_mask[btn_combo[0]] = True
        blocked_mask[btn_combo[1]] = True

        # 4. Determine if BB calls
        # Sample a BB hand; check if it falls in the call range (weighted by call freq)
        # We use the marginal probability approach: draw BB hand from uniform,
        # then accept with probability proportional to call_freq.
        # More accurately: sample from bb_w_arr (weighted by call freq vs uniform)
        # to get a "calling BB hand", but we need to also consider BB folding.
        #
        # Method: sample BB combo from full deck (respecting blocked), then
        # check if that combo is a "call" based on bb_call_range frequency.
        # Equivalently: sample from call-weighted range with probability bb_call_prob,
        # else BB folds.
        #
        # Accurate approach: for each trial, sample BB hand from unblocked combos
        # uniform, then BB calls with probability = bb_call_range[that_hand].

        # Get unblocked combos for BB
        valid_bb = ~blocked_mask[bb_c1_arr] & ~blocked_mask[bb_c2_arr]
        if not np.any(valid_bb):
            continue

        # Sample BB hand uniformly from unblocked range combos
        # Weight by uniform (each combo equally likely a priori)
        n_valid = int(valid_bb.sum())
        idx_arr = np.where(valid_bb)[0]
        idx = idx_arr[rng_np.integers(n_valid)]
        bb_c1_sampled = int(bb_c1_arr[idx])
        bb_c2_sampled = int(bb_c2_arr[idx])
        bb_calls_freq = bb_w_arr[idx]  # this is the call frequency for that hand

        # BB calls with probability = bb_calls_freq
        bb_calls = rng_np.random() < bb_calls_freq

        # 5. Deal board
        if bb_calls:
            blocked_mask[bb_c1_sampled] = True
            blocked_mask[bb_c2_sampled] = True

        remaining = deck[~blocked_mask]
        board_idx = rng_np.choice(len(remaining), 5, replace=False)
        board_cards = remaining[board_idx]

        b0 = CARD_TABLE[board_cards[0]]
        b1 = CARD_TABLE[board_cards[1]]
        b2 = CARD_TABLE[board_cards[2]]
        b3 = CARD_TABLE[board_cards[3]]
        b4 = CARD_TABLE[board_cards[4]]

        sb_val  = eval7.evaluate([CARD_TABLE[sb_combo[0]],  CARD_TABLE[sb_combo[1]],  b0,b1,b2,b3,b4])
        co_val  = eval7.evaluate([CARD_TABLE[co_combo[0]],  CARD_TABLE[co_combo[1]],  b0,b1,b2,b3,b4])
        btn_val = eval7.evaluate([CARD_TABLE[btn_combo[0]], CARD_TABLE[btn_combo[1]], b0,b1,b2,b3,b4])

        if bb_calls:
            # 4-way showdown, pot = 64
            bb_val_hand = eval7.evaluate([CARD_TABLE[bb_c1_sampled], CARD_TABLE[bb_c2_sampled], b0,b1,b2,b3,b4])
            best = max(sb_val, co_val, btn_val, bb_val_hand)
            winners = ((sb_val == best) + (co_val == best) + (btn_val == best) + (bb_val_hand == best))
            if sb_val == best:
                sb_share = 64.0 / winners
            else:
                sb_share = 0.0
            ev_trial = sb_share - 16.0
        else:
            # 3-way showdown, pot = 50 (BB's 2-chip blind is dead)
            best = max(sb_val, co_val, btn_val)
            winners = (sb_val == best) + (co_val == best) + (btn_val == best)
            if sb_val == best:
                sb_share = 50.0 / winners
            else:
                sb_share = 0.0
            ev_trial = sb_share - 16.0

        total_ev += ev_trial
        valid_trials += 1

        # Unblock BB if we blocked it
        if bb_calls:
            blocked_mask[bb_c1_sampled] = False
            blocked_mask[bb_c2_sampled] = False

    if valid_trials == 0:
        return -1.0  # fallback = fold EV
    return total_ev / valid_trials


def sb_ev_to_freq(ev_push: float, ev_fold: float = -1.0) -> float:
    """
    Linear interpolation ±0.5 chips around the EV boundary.
    push when EV(push) > EV(fold) + 0.5  => 1.0
    fold when EV(push) < EV(fold) - 0.5  => 0.0
    """
    lo = ev_fold - 0.5
    hi = ev_fold + 0.5
    if ev_push >= hi:
        return 1.0
    elif ev_push <= lo:
        return 0.0
    else:
        return (ev_push - lo) / (hi - lo)


# ---------------------------------------------------------------------------
# Recompute push_pct from corrected hands
# ---------------------------------------------------------------------------

def recompute_push_pct(hands_list: list) -> float:
    total_w = 0.0
    total_push = 0.0
    for h in hands_list:
        nc = num_combos(h["hand"])
        total_w += nc
        total_push += nc * h["push"]
    return round(total_push / total_w * 100, 1) if total_w > 0 else 0.0


# ---------------------------------------------------------------------------
# Fix a BB 2-opponent situation
# ---------------------------------------------------------------------------

def fix_bb_2opp(
    label: str,
    facing_str: str,
    opp1_pos: str, opp1_facing: str,
    opp2_pos: str, opp2_facing: str,
    pot_total: float,
    dead_chips: float,
    orig_data: dict,
    fixed_data: dict,
    num_trials: int,
    rng_np: np.random.Generator,
):
    """
    Fix BB's calling range facing 2 opponents who pushed.

    pot_total = total chips in pot if BB calls (16*3 for BB + 2 opponents, plus dead)
    BB calls 14 more chips.
    breakeven = 14 / pot_total
    """
    breakeven = 14.0 / pot_total

    print(f"\n=== Fixing: {label} ===")
    print(f"Breakeven: {breakeven*100:.3f}%  (14 / {pot_total:.0f})")
    print(f"Trials per hand: {num_trials:,}")

    opp1_range = get_situation(orig_data, opp1_pos, opp1_facing)
    opp2_range = get_situation(orig_data, opp2_pos, opp2_facing)
    opp1_arrays = build_range_arrays(opp1_range)
    opp2_arrays = build_range_arrays(opp2_range)

    print(f"{opp1_pos} '{opp1_facing}' combos: {len(opp1_arrays[0])}, "
          f"mean push: {sum(opp1_range.values())/len(opp1_range):.3f}")
    print(f"{opp2_pos} '{opp2_facing}' combos: {len(opp2_arrays[0])}, "
          f"mean push: {sum(opp2_range.values())/len(opp2_range):.3f}")

    bb_sit_obj = get_situation_obj(orig_data, "BB", facing_str)
    hand_order = [h["hand"] for h in bb_sit_obj["hands"]]
    old_freqs  = {h["hand"]: h["push"] for h in bb_sit_obj["hands"]}
    old_pct    = bb_sit_obj["push_pct"]

    print(f"\n{'Hand':<8} | {'Solver%':>8} | {'Equity%':>8} | {'EV(chips)':>10} | {'Corrected%':>10} | Change")
    print("-" * 72)
    sys.stdout.flush()

    corrected_hands = []
    num_changed = 0

    for hand_str in hand_order:
        solver_freq = old_freqs[hand_str]

        equity = compute_equity_2opp(
            hand_str, opp1_arrays, opp2_arrays,
            num_trials=num_trials, rng_np=rng_np
        )

        ev_chips = equity * pot_total - 14.0
        corrected_freq = equity_to_freq_bb(equity, breakeven)

        changed = abs(corrected_freq - solver_freq) > 0.01
        if changed:
            num_changed += 1

        change_str = "FIXED" if changed else "ok"
        print(f"{hand_str:<8} | {solver_freq*100:>8.2f} | {equity*100:>8.2f} | "
              f"{ev_chips:>+10.2f} | {corrected_freq*100:>10.2f} | {change_str}")
        sys.stdout.flush()

        corrected_hands.append({"hand": hand_str, "push": round(corrected_freq, 6)})

    print("-" * 72)
    new_pct = recompute_push_pct(corrected_hands)
    print(f"push_pct: {old_pct:.1f}% -> {new_pct:.1f}%  |  hands changed: {num_changed}/{len(hand_order)}")
    sys.stdout.flush()

    # Apply to fixed_data
    for pos in fixed_data["positions"]:
        if pos["name"] == "BB":
            for sit in pos["situations"]:
                if sit["facing"] == facing_str:
                    sit["hands"] = corrected_hands
                    sit["push_pct"] = new_pct
                    break

    return num_changed, old_pct, new_pct


# ---------------------------------------------------------------------------
# Fix SB vs CO+BTN push
# ---------------------------------------------------------------------------

def fix_sb_co_btn_push(
    orig_data: dict,
    fixed_data: dict,
    bb_call_range: dict,
    num_trials: int,
    rng_np: np.random.Generator,
):
    label = "SB vs CO+BTN push"
    facing_str = "CO+BTN push"

    print(f"\n=== Fixing: {label} ===")
    print(f"EV(fold) = -1 chip")
    print(f"Trials per hand: {num_trials:,}")

    co_range  = get_situation(orig_data, "CO",  "no action")
    btn_range = get_situation(orig_data, "BTN", "CO push")
    co_arrays  = build_range_arrays(co_range)
    btn_arrays = build_range_arrays(btn_range)

    print(f"CO  'no action' combos: {len(co_arrays[0])}, "
          f"mean push: {sum(co_range.values())/len(co_range):.3f}")
    print(f"BTN 'CO push'   combos: {len(btn_arrays[0])}, "
          f"mean push: {sum(btn_range.values())/len(btn_range):.3f}")
    print(f"BB call range (CO+BTN+SB push) mean call freq: "
          f"{sum(bb_call_range.values())/len(bb_call_range):.3f}")

    sb_sit_obj = get_situation_obj(orig_data, "SB", facing_str)
    hand_order = [h["hand"] for h in sb_sit_obj["hands"]]
    old_freqs  = {h["hand"]: h["push"] for h in sb_sit_obj["hands"]}
    old_pct    = sb_sit_obj["push_pct"]

    print(f"\n{'Hand':<8} | {'Solver%':>8} | {'EV(push)':>10} | {'EV(fold)':>10} | {'Corrected%':>10} | Change")
    print("-" * 76)
    sys.stdout.flush()

    corrected_hands = []
    num_changed = 0

    for hand_str in hand_order:
        solver_freq = old_freqs[hand_str]

        ev_push = compute_sb_push_ev(
            hand_str, co_arrays, btn_arrays, bb_call_range,
            num_trials=num_trials, rng_np=rng_np
        )
        ev_fold = -1.0

        corrected_freq = sb_ev_to_freq(ev_push, ev_fold)

        changed = abs(corrected_freq - solver_freq) > 0.01
        if changed:
            num_changed += 1

        change_str = "FIXED" if changed else "ok"
        print(f"{hand_str:<8} | {solver_freq*100:>8.2f} | {ev_push:>+10.3f} | "
              f"{ev_fold:>+10.3f} | {corrected_freq*100:>10.2f} | {change_str}")
        sys.stdout.flush()

        corrected_hands.append({"hand": hand_str, "push": round(corrected_freq, 6)})

    print("-" * 76)
    new_pct = recompute_push_pct(corrected_hands)
    print(f"push_pct: {old_pct:.1f}% -> {new_pct:.1f}%  |  hands changed: {num_changed}/{len(hand_order)}")
    sys.stdout.flush()

    # Apply to fixed_data
    for pos in fixed_data["positions"]:
        if pos["name"] == "SB":
            for sit in pos["situations"]:
                if sit["facing"] == facing_str:
                    sit["hands"] = corrected_hands
                    sit["push_pct"] = new_pct
                    break

    return num_changed, old_pct, new_pct


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fix 5 situations in 4-max 8bb push/fold game")
    parser.add_argument("--trials", type=int, default=50_000,
                        help="Monte Carlo trials per hand (default: 50000)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed (default: 42)")
    args = parser.parse_args()

    rng_np = np.random.default_rng(args.seed)

    print(f"Loading original data: {INPUT_ORIG}")
    with open(INPUT_ORIG) as f:
        orig_data = json.load(f)

    print(f"Loading existing fixed data: {INPUT_FIXED}")
    with open(INPUT_FIXED) as f:
        fixed_data = json.load(f)

    # Verify JSON structure
    print("\nJSON structure (original):")
    for pos in orig_data["positions"]:
        print(f"  {pos['name']}: {[s['facing'] for s in pos['situations']]}")

    print(f"\nTrials per hand: {args.trials:,}")
    print(f"Seed: {args.seed}")

    # -----------------------------------------------------------------------
    # Situation 4: BB vs CO+BTN+SB push — COPY from existing fixed file
    # -----------------------------------------------------------------------
    print("\n=== Situation 4: BB vs CO+BTN+SB push (copy from existing fixed file) ===")
    src_sit = get_situation_obj(fixed_data, "BB", "CO+BTN+SB push")
    new_pct_4 = src_sit["push_pct"]
    orig_sit_4 = get_situation_obj(orig_data, "BB", "CO+BTN+SB push")
    print(f"push_pct: {orig_sit_4['push_pct']:.1f}% -> {new_pct_4:.1f}% (already fixed, preserving)")
    # The fixed_data already has this; nothing to do

    # Build BB call range for situation 5 (from fixed data, not original)
    bb_call_range_3push = get_situation(fixed_data, "BB", "CO+BTN+SB push")

    # -----------------------------------------------------------------------
    # Situation 1: BB vs CO+BTN push (SB folded)
    # Pot: CO 16 + BTN 16 + SB dead 1 + BB 16 = 49
    # -----------------------------------------------------------------------
    changed_1, old_1, new_1 = fix_bb_2opp(
        label="BB vs CO+BTN push (SB folded)",
        facing_str="CO+BTN push",
        opp1_pos="CO",  opp1_facing="no action",
        opp2_pos="BTN", opp2_facing="CO push",
        pot_total=49.0,   # 16+16+1+16
        dead_chips=1.0,
        orig_data=orig_data,
        fixed_data=fixed_data,
        num_trials=args.trials,
        rng_np=rng_np,
    )

    # -----------------------------------------------------------------------
    # Situation 2: BB vs CO+SB push (BTN folded)
    # Pot: CO 16 + SB 16 + BB 16 = 48  (BTN has no blind, no dead money)
    # -----------------------------------------------------------------------
    changed_2, old_2, new_2 = fix_bb_2opp(
        label="BB vs CO+SB push (BTN folded)",
        facing_str="CO+SB push",
        opp1_pos="CO",  opp1_facing="no action",
        opp2_pos="SB",  opp2_facing="CO push",
        pot_total=48.0,   # 16+16+16
        dead_chips=0.0,
        orig_data=orig_data,
        fixed_data=fixed_data,
        num_trials=args.trials,
        rng_np=rng_np,
    )

    # -----------------------------------------------------------------------
    # Situation 3: BB vs BTN+SB push (CO folded)
    # Pot: BTN 16 + SB 16 + BB 16 = 48  (CO has no blind, no dead money)
    # -----------------------------------------------------------------------
    changed_3, old_3, new_3 = fix_bb_2opp(
        label="BB vs BTN+SB push (CO folded)",
        facing_str="BTN+SB push",
        opp1_pos="BTN", opp1_facing="no action",
        opp2_pos="SB",  opp2_facing="BTN push",
        pot_total=48.0,   # 16+16+16
        dead_chips=0.0,
        orig_data=orig_data,
        fixed_data=fixed_data,
        num_trials=args.trials,
        rng_np=rng_np,
    )

    # -----------------------------------------------------------------------
    # Situation 5: SB vs CO+BTN push (non-terminal)
    # -----------------------------------------------------------------------
    changed_5, old_5, new_5 = fix_sb_co_btn_push(
        orig_data=orig_data,
        fixed_data=fixed_data,
        bb_call_range=bb_call_range_3push,
        num_trials=args.trials,
        rng_np=rng_np,
    )

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    total_changed = changed_1 + changed_2 + changed_3 + changed_5
    print(f"\n{'='*60}")
    print("=== Summary ===")
    print(f"  Sit 1 (BB vs CO+BTN push):     {changed_1:3d} hands changed  push_pct {old_1:.1f}% -> {new_1:.1f}%")
    print(f"  Sit 2 (BB vs CO+SB push):      {changed_2:3d} hands changed  push_pct {old_2:.1f}% -> {new_2:.1f}%")
    print(f"  Sit 3 (BB vs BTN+SB push):     {changed_3:3d} hands changed  push_pct {old_3:.1f}% -> {new_3:.1f}%")
    print(f"  Sit 4 (BB vs CO+BTN+SB push):  copied from existing fixed file  ({new_pct_4:.1f}%)")
    print(f"  Sit 5 (SB vs CO+BTN push):     {changed_5:3d} hands changed  push_pct {old_5:.1f}% -> {new_5:.1f}%")
    print(f"  Total hands changed: {total_changed}")

    # -----------------------------------------------------------------------
    # Write output
    # -----------------------------------------------------------------------
    with open(OUTPUT, "w") as f:
        json.dump(fixed_data, f, indent=2)
    print(f"\nWritten: {OUTPUT}")


if __name__ == "__main__":
    main()
