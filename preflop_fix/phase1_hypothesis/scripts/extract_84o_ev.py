#!/usr/bin/env python3
"""Extract 84o's root EV from a DCFR solver output JSON.

Finds the IP root decision node and averages the EV of all 84o combos.

Usage:
  python3 extract_84o_ev.py <path/to/solve.json>
  python3 extract_84o_ev.py <file1.json> <file2.json> ...  # multi-file average
"""
import json
import sys
from itertools import product


def all_84o_hands():
    s = set()
    for c1 in ("8c", "8d", "8h", "8s"):
        for c2 in ("4c", "4d", "4h", "4s"):
            s.add(c1 + c2)
            s.add(c2 + c1)
    return s


def find_ip_root(data):
    """Find the root decision node for the IP player.
    Strategy: the first IP entry (sorted by shortest node path string).
    """
    ip_entries = [e for e in data["strategy"] if e.get("player") == "IP"]
    if not ip_entries:
        return None
    # Sort by depth (arrow count) then by entry order
    ip_entries.sort(key=lambda e: str(e.get("node", "")).count("→"))
    return ip_entries[0]


def extract(path):
    with open(path) as f:
        data = json.load(f)
    hands_84o = all_84o_hands()
    root = find_ip_root(data)
    if root is None:
        print(f"[{path}] No IP nodes found!")
        return None
    combos = [c for c in root["combos"] if c["hand"] in hands_84o]
    if not combos:
        print(f"[{path}] No 84o combos at IP root node='{root.get('node')}'")
        return None
    evs = [c.get("ev", float("nan")) for c in combos]
    valid = [e for e in evs if e == e]
    avg = sum(valid) / len(valid) if valid else float("nan")
    return {
        "path": path,
        "board": data.get("config", {}).get("board"),
        "iterations": data.get("iterations"),
        "exploitability_pct": data.get("exploitability_pct"),
        "oop_ev_avg": data.get("oop_ev"),
        "ip_ev_avg": data.get("ip_ev"),
        "node": root.get("node"),
        "n_combos": len(combos),
        "evs": evs,
        "avg_ev_84o": avg,
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    per_file = []
    for p in sys.argv[1:]:
        r = extract(p)
        if r is None:
            continue
        per_file.append(r)
        print(f"\n=== {p} ===")
        print(f"  board        : {r['board']}")
        print(f"  iterations   : {r['iterations']}")
        print(f"  exploit %    : {r['exploitability_pct']:.3f}")
        print(f"  OOP EV avg   : {r['oop_ev_avg']:.3f}")
        print(f"  IP EV  avg   : {r['ip_ev_avg']:.3f}")
        print(f"  IP root node : '{r['node']}'")
        print(f"  84o combos   : {r['n_combos']}")
        for ev in r["evs"]:
            print(f"    ev = {ev:+.3f}")
        print(f"  84o avg EV   : {r['avg_ev_84o']:+.3f} chips")

    if len(per_file) > 1:
        avgs = [r["avg_ev_84o"] for r in per_file]
        mean_ev = sum(avgs) / len(avgs)
        print("\n=== Multi-flop summary ===")
        for r in per_file:
            print(f"  {r['board']:10s}  {r['avg_ev_84o']:+7.3f}  (expl {r['exploitability_pct']:.2f}%)")
        print(f"  Mean 84o realized flop EV across {len(per_file)} flops: {mean_ev:+.3f} chips")
        # Preflop investment: BTN posts 5 chips to open 2.5x. With BB calling
        # we reach the flop; the BTN invested 5 of which 5.5 is now "his share
        # of the pot" (pot=11 / 2 for EV accounting). So the "root EV" from
        # the flop solver already accounts for the 5.5 chip contribution if
        # the solver reports raw chip EV relative to zero.
        # We compare to equilibrium neutrality = pot/2 = 5.5 (pure 50% share).
        print(f"  Pot share neutrality (pot/2 = 5.5)")
        print(f"  Delta vs neutrality: {mean_ev - 5.5:+.3f} chips")


if __name__ == "__main__":
    main()
