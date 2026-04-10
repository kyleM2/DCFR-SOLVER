#!/usr/bin/env python3
"""Audit a preflop chart JSON for RFI frequencies and anomalies.

Works on chart format (list of PreflopSpot {spot_name, hands}) rather than
the tree format (list of nodes with position/line).

Usage:
  python3 audit_chart.py <chart.json> [position=BTN]
"""
import json
import sys
from collections import defaultdict

RANKS = "23456789TJQKA"
RANK_VALUE = {r: i for i, r in enumerate(RANKS, start=2)}


def hand_sort_key(hand):
    """Rough hand-strength sort key (higher = stronger)."""
    if len(hand) == 2:
        r = hand[0]
        return 100 + RANK_VALUE[r]
    r1, r2, k = hand[0], hand[1], hand[2]
    v1, v2 = RANK_VALUE[r1], RANK_VALUE[r2]
    hi, lo = max(v1, v2), min(v1, v2)
    base = hi * 2
    if k == "s":
        base += 2
    gap = hi - lo - 1
    if gap == 0:
        base += 1
    elif gap == 2:
        base -= 1
    elif gap == 3:
        base -= 2
    elif gap >= 4:
        base -= 3 + (gap - 4)
    base += lo / 14.0
    return base


def hand_combos(hand):
    if len(hand) == 2:
        return 6
    if hand[2] == "s":
        return 4
    return 12


def open_freq(hand_entry):
    for a in hand_entry.get("actions", []):
        if a["action"].startswith("raise") or a["action"].startswith("allin"):
            return a["prob"]
    return 0.0


def rfi_name(pos):
    return f"{pos} RFI"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    path = sys.argv[1]
    positions = sys.argv[2:] if len(sys.argv) > 2 else ["UTG", "HJ", "CO", "BTN", "SB"]

    with open(path) as f:
        data = json.load(f)

    # Build {spot_name: spot}
    spots_by_name = {s.get("spot_name", ""): s for s in data}

    print(f"# Chart: {path}")
    print(f"# Total spots: {len(data)}")
    print()

    for pos in positions:
        name = rfi_name(pos)
        if name not in spots_by_name:
            continue
        spot = spots_by_name[name]
        hands = spot.get("hands", [])
        total_weight = 0.0
        anomaly_count = 0
        rows = []
        for h in hands:
            hand = h["hand"]
            freq = open_freq(h)
            combos = hand_combos(hand)
            total_weight += (combos / 1326.0) * freq
            rows.append((hand_sort_key(hand), hand, freq))
        # Count anomalies
        rows.sort(reverse=True)
        for i, (s1, h1, f1) in enumerate(rows):
            for j in range(i):
                s2, h2, f2 = rows[j]
                if f1 > f2 + 0.05:
                    anomaly_count += 1

        # Find specific hands
        found = {h: f for (_, h, f) in rows}
        s84o = found.get("84o", None)
        s72o = found.get("72o", None)
        s42o = found.get("42o", None)
        s54o = found.get("54o", None)
        s65o = found.get("65o", None)

        print(f"## {pos} RFI")
        print(f"  total open: {total_weight*100:6.2f}%")
        print(f"  anomaly pairs: {anomaly_count}")
        print(f"  84o open: {s84o*100 if s84o is not None else float('nan'):6.2f}%" if s84o is not None else "  84o open: n/a")
        print(f"  72o open: {s72o*100 if s72o is not None else float('nan'):6.2f}%" if s72o is not None else "  72o open: n/a")
        print(f"  42o open: {s42o*100 if s42o is not None else float('nan'):6.2f}%" if s42o is not None else "  42o open: n/a")
        print(f"  54o open: {s54o*100 if s54o is not None else float('nan'):6.2f}%" if s54o is not None else "  54o open: n/a")
        print(f"  65o open: {s65o*100 if s65o is not None else float('nan'):6.2f}%" if s65o is not None else "  65o open: n/a")
        print()


if __name__ == "__main__":
    main()
