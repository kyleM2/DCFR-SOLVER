#!/usr/bin/env python3
"""Phase 1b: Audit the DCFR preflop output for non-monotonic RFI frequencies.

For each position, extract the opening frequency of every hand class,
sort by approximate strength, and identify anomalies where weaker hands
open more than stronger ones.
"""
import json
import sys
from collections import Counter, defaultdict

path = sys.argv[1] if len(sys.argv) > 1 else "output/preflop_tree_6p_100bb.json"
position_filter = sys.argv[2] if len(sys.argv) > 2 else "BTN"

with open(path) as f:
    data = json.load(f)

RANKS = "23456789TJQKA"
RANK_VALUE = {r: i for i, r in enumerate(RANKS, start=2)}


def hand_sort_key(hand):
    """Approximate hand strength sort key (higher = stronger)."""
    if len(hand) == 2:  # pair
        r = hand[0]
        return (100 + RANK_VALUE[r], 0, 0)
    r1, r2, k = hand[0], hand[1], hand[2]
    v1, v2 = RANK_VALUE[r1], RANK_VALUE[r2]
    hi, lo = max(v1, v2), min(v1, v2)
    # rough Chen score
    base = hi * 2
    if k == "s":
        base += 2
    gap = hi - lo - 1
    if gap == 0:
        base += 1  # connected
    elif gap == 1:
        base += 0
    elif gap == 2:
        base -= 1
    elif gap == 3:
        base -= 2
    else:
        base -= 3 + (gap - 4)
    base += lo / 14
    return (base, hi, lo)


def open_freq(hand_entry):
    for a in hand_entry["actions"]:
        if a["action"].startswith("raise"):
            return a["prob"]
    return 0.0


# Find RFI node for this position (line == '' means unopened pot, first to act)
rfi = [x for x in data if x["position"] == position_filter and x["line"] == ""]
if not rfi:
    print(f"No RFI node found for {position_filter}")
    sys.exit(1)
node = rfi[0]
print(f"# {position_filter} RFI — {node['spot_name']}")
print(f"# Actions: {node['available_actions']}")
print(f"# Hands: {len(node['hands'])}")
print()

hand_rows = []
for h in node["hands"]:
    hand = h["hand"]
    freq = open_freq(h)
    strength = hand_sort_key(hand)
    hand_rows.append((strength, hand, freq))

# Sort by strength descending
hand_rows.sort(key=lambda x: x[0], reverse=True)

print(f"{'Rank':>4}  {'Hand':<4}  {'Open%':>7}  {'Running':>7}  Strength")
print("-" * 50)

total_weight = 0.0
for i, (strength, hand, freq) in enumerate(hand_rows, start=1):
    # Weight: pair=6, suited=4, offsuit=12 combos out of 1326
    if len(hand) == 2:
        combos = 6
    elif hand[2] == "s":
        combos = 4
    else:
        combos = 12
    weight = combos / 1326.0
    total_weight += weight * freq
    print(f"{i:>4}  {hand:<4}  {freq*100:6.2f}%  {total_weight*100:6.2f}%  {strength[0]:.2f}")

print()
print(f"Total opening frequency: {total_weight*100:.2f}% of all hands")
print()

# Anomaly detection: find hands that open MORE than a stronger hand
print("# Anomalies: weak hand opens more than stronger hand (top 20)")
anomalies = []
for i, (s1, h1, f1) in enumerate(hand_rows):
    for j in range(i):  # j is stronger (lower index = stronger since sorted desc)
        s2, h2, f2 = hand_rows[j]
        if f1 > f2 + 0.05:  # >5% gap
            anomalies.append((f1 - f2, h1, f1, h2, f2))

anomalies.sort(reverse=True)
print(f"Found {len(anomalies)} (hand_weak, hand_strong) anomaly pairs")
print(f"{'Gap':>6}  {'Weak':<5} {'Freq':>7}  {'Strong':<5} {'Freq':>7}")
for gap, hw, fw, hs, fs in anomalies[:20]:
    print(f"{gap*100:5.1f}%  {hw:<5} {fw*100:6.2f}%  {hs:<5} {fs*100:6.2f}%")

# Focus on 84o and its neighbors
print()
print("# Focus: 84o region")
target_hands = ["84o", "85o", "83o", "74o", "73o", "72o", "53o", "54o", "63o", "64o", "65o",
                "82o", "92o", "93o", "94o", "95o", "96o", "42o", "43o", "52o",
                "84s", "74s", "53s", "63s", "85s"]
found = {h: f for (_, h, f) in hand_rows}
print(f"{'Hand':<5} {'Freq':>7}")
for h in target_hands:
    if h in found:
        print(f"{h:<5} {found[h]*100:6.2f}%")
