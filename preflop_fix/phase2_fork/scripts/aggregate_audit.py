#!/usr/bin/env python3
"""Aggregate audit results for all Phase 2 charts into a markdown table.

Reads every chart JSON in preflop_fix/phase2_fork/results/ matching
flat_tax*.json and regression_original_tax20.json, and the Phase 1b
Original baselines under preflop_fix/phase1b_ablation/results/.

Writes a single AUDIT.md summarizing:
  - Per-position RFI frequencies per (mode, base_tax)
  - Anomaly counts
  - Specific-hand (84o, 72o, 42o, 54o, 65o) open rates
  - GTO target comparison
  - Monotonicity check UTG ≤ HJ ≤ CO ≤ BTN

Usage:
  python3 aggregate_audit.py > AUDIT.md
"""
import json
import os
import sys
from collections import OrderedDict

RANKS = "23456789TJQKA"
RANK_VALUE = {r: i for i, r in enumerate(RANKS, start=2)}

GTO_TARGETS = {
    "UTG": 14.0,
    "HJ": 17.0,
    "CO": 28.0,
    "BTN": 48.0,
    "SB": 40.0,
}


def hand_sort_key(hand):
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


def audit_chart(path):
    with open(path) as f:
        data = json.load(f)
    spots_by_name = {s.get("spot_name", ""): s for s in data}
    result = {}
    for pos in ("UTG", "HJ", "CO", "BTN", "SB"):
        name = f"{pos} RFI"
        spot = spots_by_name.get(name)
        if spot is None:
            continue
        hands = spot.get("hands", [])
        total_weight = 0.0
        rows = []
        for h in hands:
            hand = h["hand"]
            freq = open_freq(h)
            combos = hand_combos(hand)
            total_weight += (combos / 1326.0) * freq
            rows.append((hand_sort_key(hand), hand, freq))
        rows.sort(reverse=True)
        anomaly_count = 0
        for i, (_s1, _h1, f1) in enumerate(rows):
            for j in range(i):
                _s2, _h2, f2 = rows[j]
                if f1 > f2 + 0.05:
                    anomaly_count += 1
        found = {h: f for (_, h, f) in rows}
        result[pos] = {
            "total": total_weight * 100.0,
            "anomaly": anomaly_count,
            "84o": (found.get("84o", 0.0) or 0.0) * 100.0,
            "72o": (found.get("72o", 0.0) or 0.0) * 100.0,
            "42o": (found.get("42o", 0.0) or 0.0) * 100.0,
            "54o": (found.get("54o", 0.0) or 0.0) * 100.0,
            "65o": (found.get("65o", 0.0) or 0.0) * 100.0,
        }
    return result


def collect_configs():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    phase1b = os.path.abspath(
        os.path.join(root, "..", "phase1b_ablation", "results")
    )
    phase2 = os.path.join(root, "results")

    configs = OrderedDict()

    # Phase 1b baselines (Original mode)
    for tax_label, path_name in [
        ("Orig 0.00", "preflop_charts_6p_100bb_tax0.json"),
        ("Orig 0.05", "preflop_charts_6p_100bb_tax05.json"),
        ("Orig 0.10", "preflop_charts_6p_100bb_tax10.json"),
        ("Orig 0.15", "preflop_charts_6p_100bb_tax15.json"),
        ("Orig 0.20*", "preflop_charts_6p_100bb_tax20_baseline.json"),
    ]:
        p = os.path.join(phase1b, path_name)
        if os.path.exists(p):
            configs[tax_label] = p

    # Phase 2 flat sweep
    for lbl, name in [
        ("Flat 0.00", "flat_tax00.json"),
        ("Flat 0.05", "flat_tax05.json"),
        ("Flat 0.08", "flat_tax08.json"),
        ("Flat 0.10", "flat_tax10.json"),
        ("Flat 0.12", "flat_tax12.json"),
        ("Flat 0.15", "flat_tax15.json"),
    ]:
        p = os.path.join(phase2, name)
        if os.path.exists(p):
            configs[lbl] = p

    # Extended sweep: Shift / Capped / Quadratic / PerGap
    for lbl, name in [
        ("Shift1 0.10", "shift1_010.json"),
        ("Shift1 0.11", "shift1_011.json"),
        ("Shift1 0.12", "shift1_012.json"),
        ("Shift1 0.13", "shift1_013.json"),
        ("Shift1 0.14", "shift1_014.json"),
        ("Shift1 0.15", "shift1_015.json"),
        ("Shift1 0.20", "shift1_020.json"),
        ("Shift2 0.15", "shift2_015.json"),
        ("Shift2 0.20", "shift2_020.json"),
        ("Capped2 0.10", "capped2_010.json"),
        ("Capped3 0.15", "capped3_015.json"),
        ("Quad 0.20", "quad_020.json"),
        ("Quad 0.25", "quad_025.json"),
        ("PerGapA 0.15", "pergap_a_015.json"),
        ("PerGapA 0.20", "pergap_a_020.json"),
        ("PerGapB 0.15", "pergap_b_015.json"),
        ("PerGapB 0.20", "pergap_b_020.json"),
        ("PerGapC 0.15", "pergap_c_015.json"),
    ]:
        p = os.path.join(phase2, name)
        if os.path.exists(p):
            configs[lbl] = p

    # Fork regression
    p = os.path.join(phase2, "regression_original_tax20.json")
    if os.path.exists(p):
        configs["Fork Orig 0.20"] = p

    return configs


def fmt_delta(val, target):
    d = val - target
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.1f}"


def main():
    configs = collect_configs()
    if not configs:
        print("no charts found", file=sys.stderr)
        sys.exit(1)

    print("# Phase 2 Fork — Flat Tax Sweep Audit")
    print()
    print(f"Configs audited: {len(configs)}")
    print()
    print("Reference GTO targets (6-max 100bb):")
    for k, v in GTO_TARGETS.items():
        print(f"  - {k}: ~{v:.0f}%")
    print()
    print("* = Phase 1b baseline that matched the production `oop_pot_tax=0.20`")
    print("  default (src/preflop.rs).")
    print()

    audits = {lbl: audit_chart(p) for lbl, p in configs.items()}

    # ------------------------------------------------------------------
    # Table 1: per-position total RFI%
    # ------------------------------------------------------------------
    print("## Total Open % per position")
    print()
    hdr = ["Config", "UTG", "HJ", "CO", "BTN", "SB", "Mono?"]
    print("| " + " | ".join(hdr) + " |")
    print("|" + "|".join(["---"] * len(hdr)) + "|")
    for lbl, res in audits.items():
        utg = res.get("UTG", {}).get("total", 0.0)
        hj = res.get("HJ", {}).get("total", 0.0)
        co = res.get("CO", {}).get("total", 0.0)
        btn = res.get("BTN", {}).get("total", 0.0)
        sb = res.get("SB", {}).get("total", 0.0)
        mono = (utg <= hj <= co <= btn)
        row = [
            lbl,
            f"{utg:5.2f}",
            f"{hj:5.2f}",
            f"{co:5.2f}",
            f"{btn:5.2f}",
            f"{sb:5.2f}",
            "yes" if mono else "NO",
        ]
        print("| " + " | ".join(row) + " |")
    tgt_row = ["GTO", "14", "17", "28", "48", "40", "yes"]
    print("| " + " | ".join(tgt_row) + " |")
    print()

    # ------------------------------------------------------------------
    # Table 2: Δ vs GTO per position
    # ------------------------------------------------------------------
    print("## Δ vs GTO target (pp)")
    print()
    print("| Config | UTG | HJ | CO | BTN | SB |")
    print("|---|---|---|---|---|---|")
    for lbl, res in audits.items():
        row = [lbl]
        for pos in ("UTG", "HJ", "CO", "BTN", "SB"):
            v = res.get(pos, {}).get("total", 0.0)
            row.append(fmt_delta(v, GTO_TARGETS[pos]))
        print("| " + " | ".join(row) + " |")
    print()

    # ------------------------------------------------------------------
    # Table 3: BTN-specific anomaly hands
    # ------------------------------------------------------------------
    print("## BTN anomaly hands (open %)")
    print()
    print("Targets: 84o/72o/42o should be ~0%, 54o ~5%, 65o ~30%.")
    print()
    print("| Config | 84o | 72o | 42o | 54o | 65o | anomaly pairs |")
    print("|---|---|---|---|---|---|---|")
    for lbl, res in audits.items():
        btn = res.get("BTN", {})
        row = [
            lbl,
            f"{btn.get('84o', 0.0):5.2f}",
            f"{btn.get('72o', 0.0):5.2f}",
            f"{btn.get('42o', 0.0):5.2f}",
            f"{btn.get('54o', 0.0):5.2f}",
            f"{btn.get('65o', 0.0):5.2f}",
            str(btn.get("anomaly", 0)),
        ]
        print("| " + " | ".join(row) + " |")
    print()

    # ------------------------------------------------------------------
    # Table 4: CO anomaly hands (secondary check)
    # ------------------------------------------------------------------
    print("## CO anomaly hands (open %)")
    print()
    print("| Config | 84o | 72o | 42o | 54o | 65o | anomaly pairs |")
    print("|---|---|---|---|---|---|---|")
    for lbl, res in audits.items():
        co = res.get("CO", {})
        row = [
            lbl,
            f"{co.get('84o', 0.0):5.2f}",
            f"{co.get('72o', 0.0):5.2f}",
            f"{co.get('42o', 0.0):5.2f}",
            f"{co.get('54o', 0.0):5.2f}",
            f"{co.get('65o', 0.0):5.2f}",
            str(co.get("anomaly", 0)),
        ]
        print("| " + " | ".join(row) + " |")
    print()

    # ------------------------------------------------------------------
    # Acceptance summary
    # ------------------------------------------------------------------
    print("## Acceptance criteria summary")
    print()
    print("Pass if: BTN total ∈ [45,51], BTN 84o<5, BTN 72o<5, BTN 42o<3,")
    print("monotone UTG≤HJ≤CO≤BTN.")
    print()
    print("| Config | BTN∈[45,51] | 84o<5 | 72o<5 | 42o<3 | Mono | PASS? |")
    print("|---|---|---|---|---|---|---|")
    for lbl, res in audits.items():
        btn = res.get("BTN", {})
        utg = res.get("UTG", {}).get("total", 0.0)
        hj = res.get("HJ", {}).get("total", 0.0)
        co = res.get("CO", {}).get("total", 0.0)
        bt = btn.get("total", 0.0)
        c1 = 45.0 <= bt <= 51.0
        c2 = btn.get("84o", 100.0) < 5.0
        c3 = btn.get("72o", 100.0) < 5.0
        c4 = btn.get("42o", 100.0) < 3.0
        c5 = utg <= hj <= co <= bt
        all_pass = c1 and c2 and c3 and c4 and c5
        row = [
            lbl,
            "✓" if c1 else "✗",
            "✓" if c2 else "✗",
            "✓" if c3 else "✗",
            "✓" if c4 else "✗",
            "✓" if c5 else "✗",
            "**PASS**" if all_pass else "fail",
        ]
        print("| " + " | ".join(row) + " |")
    print()

    # Fork regression diff (Fork Orig 0.20 vs Phase1b Orig 0.20)
    if "Fork Orig 0.20" in audits and "Orig 0.20*" in audits:
        print("## Fork regression check (Fork Orig 0.20 − Phase1b Orig 0.20)")
        print()
        print("Both are tax_mode=original, base_tax=0.20, seed=42, 2M iter.")
        print("Differences should be ≤ MC noise (~0.5-1 pp).")
        print()
        print("| Position | Fork | Phase1b | Δ |")
        print("|---|---|---|---|")
        f = audits["Fork Orig 0.20"]
        b = audits["Orig 0.20*"]
        max_delta = 0.0
        for pos in ("UTG", "HJ", "CO", "BTN", "SB"):
            fv = f.get(pos, {}).get("total", 0.0)
            bv = b.get(pos, {}).get("total", 0.0)
            d = fv - bv
            max_delta = max(max_delta, abs(d))
            print(f"| {pos} | {fv:.2f} | {bv:.2f} | {d:+.2f} |")
        print()
        if max_delta < 1.0:
            print(f"Regression check: **PASS** (max |Δ| = {max_delta:.2f} pp < 1.0)")
        else:
            print(f"Regression check: **REVIEW** (max |Δ| = {max_delta:.2f} pp ≥ 1.0)")
        print()


if __name__ == "__main__":
    main()
