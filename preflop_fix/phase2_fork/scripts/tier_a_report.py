#!/usr/bin/env python3
"""Tier-A comprehensive preflop chart report.

Compares a solver chart JSON against GTO reference frequencies.
Optionally compares against a baseline (buggy prod) chart for improvement tracking.

Usage:
  python3 tier_a_report.py <new_chart.json> [baseline_chart.json]
"""
import json
import sys

# ---------------------------------------------------------------------------
# GTO reference data
# ---------------------------------------------------------------------------

# Position RFI targets: (lo, hi) percent
GTO_RFI = {
    "UTG": (14.0, 15.0),
    "HJ":  (17.0, 19.0),
    "CO":  (26.0, 28.0),
    "BTN": (47.0, 49.0),
    "SB":  (40.0, 44.0),   # raise-only (not limp)
}

# Per-hand GTO reference for BTN (approximate open %)
# 0 = clear fold, 100 = clear open, None = mixed/range-dependent
GTO_BTN_HANDS = {
    # Pocket pairs
    "22": 60.0, "33": 65.0, "44": 70.0, "55": 80.0,
    "66": 90.0, "77": 95.0, "88": 100.0, "99": 100.0,
    "TT": 100.0, "JJ": 100.0, "QQ": 100.0, "KK": 100.0, "AA": 100.0,
    # Problem offsuit junk (GTO Wizard confirmed: 87o/86o/85o/84o all 100% fold)
    "84o": 0.0, "85o": 0.0, "86o": 0.0, "87o": 0.0,
    "72o": 0.0, "42o": 0.0, "54o": 0.0,
    "65o": 0.0, "75o": 0.0, "96o": 0.0,
    "T5o": 0.0, "J4o": 0.0,
    # Key suited hands
    "A2s": 80.0, "A3s": 85.0, "A4s": 90.0, "A5s": 95.0,
    "76s": 90.0, "65s": 85.0, "54s": 75.0,
}

# Per-hand GTO reference for UTG (tight GTO range ~14%)
GTO_UTG_HANDS = {
    "AA": 100.0, "KK": 100.0, "QQ": 100.0, "JJ": 100.0,
    "TT": 100.0, "99": 100.0, "88": 85.0, "77": 65.0,
    "66": 35.0, "55": 20.0, "44": 5.0, "33": 0.0, "22": 0.0,
    "AKs": 100.0, "AQs": 100.0, "AJs": 100.0, "ATs": 100.0,
    "A9s": 70.0, "A8s": 50.0, "A7s": 30.0, "A6s": 20.0, "A5s": 40.0,
    "A4s": 20.0, "A3s": 10.0, "A2s": 5.0,
    "KQs": 100.0, "KJs": 90.0, "KTs": 80.0, "K9s": 40.0, "K8s": 10.0,
    "QJs": 90.0, "QTs": 75.0, "Q9s": 30.0,
    "JTs": 80.0, "J9s": 35.0,
    "T9s": 50.0, "T8s": 20.0,
    "98s": 30.0, "87s": 15.0, "76s": 10.0,
    "AKo": 100.0, "AQo": 100.0, "AJo": 80.0, "ATo": 50.0,
    "KQo": 70.0, "KJo": 35.0,
    # Junk — should be 0
    "72o": 0.0, "84o": 0.0, "94o": 0.0, "T3o": 0.0,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RANKS = "23456789TJQKA"
RANK_VALUE = {r: i for i, r in enumerate(RANKS, start=2)}


def hand_combos(hand: str) -> int:
    if len(hand) == 2:
        return 6
    if hand[2] == "s":
        return 4
    return 12


def open_freq(hand_entry: dict) -> float:
    for a in hand_entry.get("actions", []):
        if a["action"].startswith("raise") or a["action"].startswith("allin"):
            return float(a["prob"])
    return 0.0


def load_chart(path: str) -> dict:
    """Load chart JSON and return {spot_name: {hand: freq}} mapping."""
    with open(path) as f:
        data = json.load(f)
    result = {}
    for spot in data:
        name = spot.get("spot_name", "")
        hands = {}
        for h in spot.get("hands", []):
            hands[h["hand"]] = open_freq(h)
        result[name] = {"hands": hands, "raw": spot}
    return result


def calc_rfi(spot_hands: dict) -> float:
    """Compute aggregate RFI% from a {hand: freq} dict."""
    total = 0.0
    for hand, freq in spot_hands.items():
        combos = hand_combos(hand)
        total += (combos / 1326.0) * freq
    return total * 100.0


def verdict(val: float, lo: float, hi: float) -> str:
    if lo <= val <= hi:
        return "✓"
    if abs(val - lo) <= 3.0 or abs(val - hi) <= 3.0:
        return "⚠"
    return "✗"


def delta_str(val: float, ref: float) -> str:
    d = val - ref
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.1f}"


def improvement_str(new_val: float, base_val: float, lo: float, hi: float) -> str:
    """Describe whether new is better than baseline relative to target range."""
    mid = (lo + hi) / 2.0
    new_err = abs(new_val - mid)
    base_err = abs(base_val - mid)
    diff = base_err - new_err  # positive = improvement
    sign = "+" if diff >= 0 else ""
    tag = "better" if diff > 0.5 else ("worse" if diff < -0.5 else "same")
    return f"{sign}{diff:.1f}pp ({tag})"


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def section_rfi(chart: dict, baseline: dict | None) -> float:
    """Print Section 1 and return MAE."""
    print("## Section 1: Position-by-Position RFI\n")

    positions = ["UTG", "HJ", "CO", "BTN", "SB"]
    has_base = baseline is not None

    # Header
    if has_base:
        hdr = f"{'Pos':<6} {'New%':>7} {'GTO Range':>13} {'Delta':>8} {'Verdict':>7}  {'Base%':>7} {'Improvement':>15}"
    else:
        hdr = f"{'Pos':<6} {'New%':>7} {'GTO Range':>13} {'Delta':>8} {'Verdict':>7}"
    print(hdr)
    print("-" * len(hdr))

    errors = []
    for pos in positions:
        spot_name = f"{pos} RFI"
        if spot_name not in chart:
            print(f"{pos:<6}  (spot not found in chart)")
            continue

        hands = chart[spot_name]["hands"]
        rfi = calc_rfi(hands)
        lo, hi = GTO_RFI[pos]
        mid = (lo + hi) / 2.0
        errors.append(abs(rfi - mid))

        v = verdict(rfi, lo, hi)
        d = delta_str(rfi, mid)
        gto_rng = f"{lo:.0f}-{hi:.0f}%"

        if has_base and f"{pos} RFI" in baseline:
            base_rfi = calc_rfi(baseline[spot_name]["hands"])
            imp = improvement_str(rfi, base_rfi, lo, hi)
            print(f"{pos:<6} {rfi:>6.2f}% {gto_rng:>13} {d:>8} {v:>7}  {base_rfi:>6.2f}% {imp:>15}")
        else:
            print(f"{pos:<6} {rfi:>6.2f}% {gto_rng:>13} {d:>8} {v:>7}")

    mae = sum(errors) / len(errors) if errors else 0.0
    print()
    return mae


def section_per_hand(chart: dict, baseline: dict | None, pos: str,
                     gto_ref: dict, section_num: int, section_title: str,
                     highlight_hands: list[str]) -> int:
    """Print per-hand analysis section. Returns count of junk hands opened > 5%."""
    print(f"## Section {section_num}: {section_title}\n")

    spot_name = f"{pos} RFI"
    if spot_name not in chart:
        print(f"  (spot '{spot_name}' not found in chart)\n")
        return 0

    hands = chart[spot_name]["hands"]
    has_base = baseline is not None and spot_name in (baseline or {})

    junk_opened = 0

    # Determine which hands to show — use highlight_hands list
    display_hands = [h for h in highlight_hands if h in hands or h in gto_ref]

    # Also gather pocket pairs if this is BTN or UTG
    pairs = [f"{r}{r}" for r in RANKS[::-1]]  # AA down to 22
    all_display = []
    seen = set()
    # Pairs first
    for h in pairs:
        if h not in seen:
            all_display.append(h)
            seen.add(h)
    # Then the highlight hands
    for h in highlight_hands:
        if h not in seen:
            all_display.append(h)
            seen.add(h)

    if has_base:
        hdr = f"  {'Hand':<8} {'New%':>7} {'GTO%':>7} {'Delta':>8} {'Verdict':>7}  {'Base%':>7}"
    else:
        hdr = f"  {'Hand':<8} {'New%':>7} {'GTO%':>7} {'Delta':>8} {'Verdict':>7}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    for hand in all_display:
        if hand not in hands:
            continue
        freq_pct = hands[hand] * 100.0
        gto_pct = gto_ref.get(hand, None)

        if gto_pct is not None:
            d = delta_str(freq_pct, gto_pct)
            # For junk (gto=0), flag anything above 5%
            tol = 10.0 if gto_pct >= 80 else (5.0 if gto_pct > 0 else 5.0)
            v = "✓" if abs(freq_pct - gto_pct) <= tol else ("⚠" if abs(freq_pct - gto_pct) <= tol * 2 else "✗")
            gto_str = f"{gto_pct:>6.1f}%"
        else:
            d = "  n/a"
            v = "?"
            gto_str = "   n/a "

        # Track junk
        if gto_ref.get(hand, 100.0) <= 5.0 and freq_pct > 5.0:
            junk_opened += 1

        if has_base:
            base_hands = baseline[spot_name]["hands"]
            base_pct = base_hands.get(hand, 0.0) * 100.0
            print(f"  {hand:<8} {freq_pct:>6.2f}% {gto_str} {d:>8} {v:>7}  {base_pct:>6.2f}%")
        else:
            print(f"  {hand:<8} {freq_pct:>6.2f}% {gto_str} {d:>8} {v:>7}")

    print()
    return junk_opened


def section_summary(mae: float, junk_count: int, chart: dict, baseline: dict | None):
    print("## Section 4: Summary Statistics\n")

    positions = ["UTG", "HJ", "CO", "BTN", "SB"]
    rfis = []
    for pos in positions:
        spot_name = f"{pos} RFI"
        if spot_name in chart:
            rfis.append((pos, calc_rfi(chart[spot_name]["hands"])))

    # Simple similarity score: 100 - mean_abs_error (capped 0-100)
    similarity = max(0.0, 100.0 - mae)

    print(f"  Mean Absolute Error vs GTO midpoints : {mae:.2f} pp")
    print(f"  Junk hands opened >5% from BTN       : {junk_count}")
    print(f"  Similarity score (100 - MAE)          : {similarity:.1f} / 100")

    print()
    print("  Per-position breakdown:")
    for pos, rfi in rfis:
        lo, hi = GTO_RFI[pos]
        mid = (lo + hi) / 2.0
        err = abs(rfi - mid)
        v = verdict(rfi, lo, hi)
        print(f"    {pos:<6}  {rfi:>6.2f}%  err={err:.2f}pp  {v}")

    if baseline is not None:
        print()
        print("  Baseline comparison:")
        base_errors = []
        for pos in positions:
            spot_name = f"{pos} RFI"
            if spot_name in chart and spot_name in baseline:
                lo, hi = GTO_RFI[pos]
                mid = (lo + hi) / 2.0
                new_rfi = calc_rfi(chart[spot_name]["hands"])
                base_rfi = calc_rfi(baseline[spot_name]["hands"])
                new_err = abs(new_rfi - mid)
                base_err = abs(base_rfi - mid)
                base_errors.append(base_err)
                tag = "better" if new_err < base_err - 0.5 else ("worse" if new_err > base_err + 0.5 else "same")
                print(f"    {pos:<6}  new_err={new_err:.2f}pp  base_err={base_err:.2f}pp  -> {tag}")
        if base_errors:
            base_mae = sum(base_errors) / len(base_errors)
            print(f"\n  Baseline MAE : {base_mae:.2f} pp")
            print(f"  New MAE      : {mae:.2f} pp")
            delta = base_mae - mae
            sign = "+" if delta >= 0 else ""
            print(f"  Improvement  : {sign}{delta:.2f} pp")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

BTN_HIGHLIGHT = [
    # Offsuit junk
    "84o", "85o", "86o", "87o", "72o", "42o", "54o", "65o", "75o", "96o", "T5o", "J4o",
    # Suited connectors
    "76s", "65s", "54s",
    # Suited aces
    "A5s", "A4s", "A3s", "A2s",
    # Broadway
    "AKo", "AQo", "KQo",
]

UTG_HIGHLIGHT = [
    # Pairs (low end)
    # already shown in pairs section
    # Suited connectors / broadways
    "AKs", "AQs", "AJs", "ATs", "A9s", "A5s", "A4s", "A3s", "A2s",
    "KQs", "KJs", "KTs", "K9s",
    "QJs", "QTs", "JTs", "T9s", "98s", "87s", "76s",
    "AKo", "AQo", "AJo", "ATo", "KQo", "KJo",
    # Junk checks
    "72o", "84o", "94o", "T3o",
]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    new_path = sys.argv[1]
    base_path = sys.argv[2] if len(sys.argv) > 2 else None

    chart = load_chart(new_path)
    baseline = load_chart(base_path) if base_path else None

    print(f"# Tier-A Preflop Chart Report")
    print(f"# New chart   : {new_path}")
    if base_path:
        print(f"# Baseline    : {base_path}")
    print()

    # Section 1
    mae = section_rfi(chart, baseline)

    # Section 2: BTN per-hand
    junk_count = section_per_hand(
        chart, baseline, "BTN",
        GTO_BTN_HANDS, 2, "BTN Per-Hand Analysis",
        BTN_HIGHLIGHT,
    )

    # Section 3: UTG per-hand
    section_per_hand(
        chart, baseline, "UTG",
        GTO_UTG_HANDS, 3, "UTG Per-Hand Analysis",
        UTG_HIGHLIGHT,
    )

    # Section 4: Summary
    section_summary(mae, junk_count, chart, baseline)


if __name__ == "__main__":
    main()
