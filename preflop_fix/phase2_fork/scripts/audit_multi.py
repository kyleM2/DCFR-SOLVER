#!/usr/bin/env python3
"""Audit Phase 2 multi-player / multi-stack charts.

For 6p charts, labels are correct and we reuse audit_chart.py logic.

For <6p charts, the chart extractor in PreflopBlueprint reuses the 6-max
spot naming scheme (history prefix = k folds). In actual multi-player
training, the first-to-act player's info set has history=[], so the chart
spot labeled "UTG RFI" contains the actual first-to-act player's strategy,
"HJ RFI" contains the second-to-act, and so on.

Translation table:
  6p: UTG, HJ, CO, BTN, SB  (labels match reality)
  5p: HJ,  CO, BTN, SB      ("UTG" spot → HJ, etc.; SB spot empty)
  4p: CO,  BTN, SB          ("UTG" spot → CO, etc.)
  3p: BTN, SB               ("UTG" spot → BTN, "HJ" spot → SB)
"""
import json
import os
import sys

RANKS = "23456789TJQKA"
RANK_VALUE = {r: i for i, r in enumerate(RANKS, start=2)}


def hand_combos(hand):
    if len(hand) == 2:
        return 6
    if hand[2] == "s":
        return 4
    return 12


def open_freq(h):
    for a in h.get("actions", []):
        if a["action"].startswith("raise") or a["action"].startswith("allin"):
            return a["prob"]
    return 0.0


LABEL_ORDER = ["UTG RFI", "HJ RFI", "CO RFI", "BTN RFI", "SB RFI"]

POSITION_MAP = {
    6: ["UTG", "HJ", "CO", "BTN", "SB"],
    5: ["HJ", "CO", "BTN", "SB"],
    4: ["CO", "BTN", "SB"],
    3: ["BTN", "SB"],
    2: ["SB"],
}


def audit_spot(spot):
    hands = spot.get("hands", [])
    total = 0.0
    specific = {}
    populated = False
    for h in hands:
        f = open_freq(h)
        if f > 0.0:
            populated = True
        total += (hand_combos(h["hand"]) / 1326.0) * f
        if h["hand"] in ("84o", "72o", "42o", "54o", "65o"):
            specific[h["hand"]] = f * 100.0
    return {
        "populated": populated,
        "total": total * 100.0,
        **{k: specific.get(k, 0.0) for k in ("84o", "72o", "42o", "54o", "65o")},
    }


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    results_dir = os.path.join(root, "results")

    runs = [
        ("6p × 15bb",  6,  "multi_6p_15bb.json"),
        ("6p × 25bb",  6,  "multi_6p_25bb.json"),
        ("6p × 50bb",  6,  "multi_6p_50bb.json"),
        ("6p × 100bb", 6,  "shift1_015.json"),
        ("5p × 100bb", 5,  "multi_5p_100bb.json"),
        ("4p × 100bb", 4,  "multi_4p_100bb.json"),
        ("3p × 100bb", 3,  "multi_3p_100bb.json"),
    ]

    print("# Phase 2 Multi-Player / Multi-Stack Audit")
    print()
    print("Winner config: **Shift1 base_tax=0.15**, seed=42, 2M iter.")
    print()
    print("Labels for <6p are remapped to the actual player that first-acts")
    print("at each history depth (see audit_multi.py docstring).")
    print()
    print("## Total Open % by effective position")
    print()
    print("| Run | 1st | 2nd | 3rd | 4th | 5th |")
    print("|---|---|---|---|---|---|")
    for (name, nplayers, fname) in runs:
        path = os.path.join(results_dir, fname)
        if not os.path.exists(path):
            print(f"| {name} | missing | | | | |")
            continue
        with open(path) as f:
            data = json.load(f)
        spots = {s.get("spot_name", ""): s for s in data}
        pos_labels = POSITION_MAP[nplayers]
        row = [name]
        for i, lbl in enumerate(LABEL_ORDER):
            spot = spots.get(lbl, {})
            info = audit_spot(spot)
            if i < len(pos_labels) and info["populated"]:
                actual_pos = pos_labels[i]
                row.append(f"{actual_pos}: {info['total']:.1f}")
            else:
                row.append("—")
        print("| " + " | ".join(row) + " |")
    print()

    print("## BTN opens per stack/player count")
    print()
    print("For 6p runs, BTN RFI is chart['BTN RFI']. For <6p runs, the player")
    print("labeled BTN in the actual game acts at different chart spots.")
    print()
    print("| Run | BTN RFI % | 84o | 72o | 42o | 54o | 65o |")
    print("|---|---|---|---|---|---|---|")
    for (name, nplayers, fname) in runs:
        path = os.path.join(results_dir, fname)
        if not os.path.exists(path):
            continue
        with open(path) as f:
            data = json.load(f)
        spots = {s.get("spot_name", ""): s for s in data}
        # Find index where BTN lives
        pos_labels = POSITION_MAP[nplayers]
        if "BTN" not in pos_labels:
            continue
        btn_idx = pos_labels.index("BTN")
        chart_label = LABEL_ORDER[btn_idx]
        spot = spots.get(chart_label, {})
        info = audit_spot(spot)
        row = [
            name,
            f"{info['total']:.1f}",
            f"{info['84o']:.2f}",
            f"{info['72o']:.2f}",
            f"{info['42o']:.2f}",
            f"{info['54o']:.2f}",
            f"{info['65o']:.2f}",
        ]
        print("| " + " | ".join(row) + " |")
    print()

    print("## Validation gates")
    print()
    print("Per the plan: opens must not collapse to near-zero on short stacks")
    print("and BTN must stay 'near GTO targets' across stack depths.")
    print()
    print("GTO 6-max BTN ≈ 48%. GTO short-stack 15bb BTN ≈ ~30% open-shove")
    print("(tighter due to narrow reward structure).")
    print()
    for (name, nplayers, fname) in runs:
        path = os.path.join(results_dir, fname)
        if not os.path.exists(path):
            continue
        with open(path) as f:
            data = json.load(f)
        spots = {s.get("spot_name", ""): s for s in data}
        pos_labels = POSITION_MAP[nplayers]
        max_open = 0.0
        tightest = 100.0
        for i, lbl in enumerate(LABEL_ORDER):
            if i >= len(pos_labels):
                break
            info = audit_spot(spots.get(lbl, {}))
            if info["populated"]:
                max_open = max(max_open, info["total"])
                tightest = min(tightest, info["total"])
        gate_nonzero = tightest > 3.0  # no collapse
        print(f"- **{name}**: max open {max_open:.1f}%, tightest {tightest:.1f}% "
              f"→ {'OK' if gate_nonzero else 'FAIL (collapse)'}")
    print()


if __name__ == "__main__":
    main()
