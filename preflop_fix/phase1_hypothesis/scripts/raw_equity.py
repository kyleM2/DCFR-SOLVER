#!/usr/bin/env python3
"""Compute 84o's raw equity vs an opponent range on a given flop
(enumerating all turn+river runouts), and its full-board equity
(enumerating all 5-card boards). Uses eval7 for fast hand evaluation.

Usage:
  python3 raw_equity.py --flop Ks7d3c --opp-range "<range string>"
  python3 raw_equity.py --preflop --opp-range "<range string>"
"""
import argparse
import itertools
import sys

import eval7


RANKS = "23456789TJQKA"
SUITS = "cdhs"
ALL_CARDS = [r + s for r in RANKS for s in SUITS]


def card(s: str) -> eval7.Card:
    return eval7.Card(s)


def expand_combo(tok: str):
    """Expand a range token like 'AKs', 'AKo', 'TT', '84o' to a list of 2-card combos (str list)."""
    tok = tok.strip()
    combos = []
    if len(tok) == 2:  # pair, e.g. 'TT'
        r = tok[0]
        for s1, s2 in itertools.combinations(SUITS, 2):
            combos.append(r + s1 + r + s2)
    elif len(tok) == 3:
        r1, r2, kind = tok[0], tok[1], tok[2]
        if kind == "s":
            for s in SUITS:
                combos.append(r1 + s + r2 + s)
        elif kind == "o":
            for s1 in SUITS:
                for s2 in SUITS:
                    if s1 != s2:
                        combos.append(r1 + s1 + r2 + s2)
        else:
            raise ValueError(f"Unknown token kind in {tok!r}")
    else:
        raise ValueError(f"Unsupported token {tok!r}")
    return combos


def parse_range(range_str: str):
    """Parse a comma-separated range string into a list of 2-card combo strings."""
    out = []
    for tok in range_str.split(","):
        tok = tok.strip()
        if not tok:
            continue
        out.extend(expand_combo(tok))
    return out


def all_84o_combos():
    combos = []
    for s1 in SUITS:
        for s2 in SUITS:
            if s1 != s2:
                combos.append("8" + s1 + "4" + s2)
    return combos  # 12 combos


def hand_strength(cards):
    """Return eval7 hand strength integer."""
    return eval7.evaluate([eval7.Card(c) for c in cards])


def equity_on_flop(hero_hand_str, opp_combos, flop_cards):
    """
    Given hero = 84o (e.g. '8h4s'), opp_combos list, and flop (3 cards),
    enumerate all turn+river runouts and compute hero's equity vs the
    averaged opponent range.
    Returns equity in [0, 1].
    """
    hero = [hero_hand_str[:2], hero_hand_str[2:]]
    dead = set(hero) | set(flop_cards)

    # filter opp combos that conflict with hero or flop
    valid_opp = []
    for combo in opp_combos:
        c1, c2 = combo[:2], combo[2:]
        if c1 in dead or c2 in dead:
            continue
        valid_opp.append((c1, c2))
    if not valid_opp:
        return float("nan")

    # All cards not dead
    remaining = [c for c in ALL_CARDS if c not in dead]

    # Precompute opp card pair cards
    hero_cards_objs = [eval7.Card(hero[0]), eval7.Card(hero[1])]
    flop_objs = [eval7.Card(c) for c in flop_cards]

    total_wins = 0.0
    total_count = 0

    # For each turn+river runout
    # Note: opp must also avoid having these runout cards
    for turn, river in itertools.combinations(remaining, 2):
        board_cards = flop_cards + [turn, river]
        board_set = set(board_cards)
        board_objs = [eval7.Card(c) for c in board_cards]
        hero_score = eval7.evaluate(hero_cards_objs + board_objs)

        run_wins = 0.0
        run_count = 0
        for (oc1, oc2) in valid_opp:
            if oc1 in board_set or oc2 in board_set:
                continue
            opp_objs = [eval7.Card(oc1), eval7.Card(oc2)]
            opp_score = eval7.evaluate(opp_objs + board_objs)
            if hero_score > opp_score:
                run_wins += 1.0
            elif hero_score == opp_score:
                run_wins += 0.5
            run_count += 1
        if run_count == 0:
            continue
        total_wins += run_wins / run_count
        total_count += 1

    return total_wins / total_count if total_count > 0 else float("nan")


def equity_preflop(hero_hand_str, opp_combos):
    """
    Given hero = 84o combo, enumerate all 5-card boards and compute
    equity vs opponent range. This is what payoff_showdown approximates.
    Uses Monte Carlo sampling if exhaustive is too slow.
    """
    hero = [hero_hand_str[:2], hero_hand_str[2:]]
    dead_hero = set(hero)

    valid_opp = []
    for combo in opp_combos:
        c1, c2 = combo[:2], combo[2:]
        if c1 in dead_hero or c2 in dead_hero:
            continue
        valid_opp.append((c1, c2))
    if not valid_opp:
        return float("nan")

    total_wins = 0.0
    total_count = 0

    hero_cards_objs = [eval7.Card(hero[0]), eval7.Card(hero[1])]

    # For each opp combo, enumerate all 5-card boards excluding dead cards.
    # C(48,5) = 1,712,304 — that's manageable but heavy for many opp combos.
    # Use Monte Carlo with fixed sample count per combo for speed.
    import random
    random.seed(42)
    samples_per_combo = 2000
    for (oc1, oc2) in valid_opp:
        dead = dead_hero | {oc1, oc2}
        remaining = [c for c in ALL_CARDS if c not in dead]
        opp_objs = [eval7.Card(oc1), eval7.Card(oc2)]
        for _ in range(samples_per_combo):
            board = random.sample(remaining, 5)
            board_objs = [eval7.Card(c) for c in board]
            hero_score = eval7.evaluate(hero_cards_objs + board_objs)
            opp_score = eval7.evaluate(opp_objs + board_objs)
            if hero_score > opp_score:
                total_wins += 1.0
            elif hero_score == opp_score:
                total_wins += 0.5
            total_count += 1

    return total_wins / total_count if total_count > 0 else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flop", help="Flop 3 cards concatenated, e.g. Ks7d3c")
    ap.add_argument("--preflop", action="store_true",
                    help="Compute full preflop (5-card) equity instead of flop equity")
    ap.add_argument("--opp-range", required=True)
    ap.add_argument("--hero", default="all",
                    help="'all' averages over all 84o combos, or a specific combo like '8h4s'")
    args = ap.parse_args()

    opp = parse_range(args.opp_range)
    print(f"Opp range combos: {len(opp)}")

    if args.hero == "all":
        hero_combos = all_84o_combos()
    else:
        hero_combos = [args.hero]

    if args.preflop:
        print("Mode: preflop (5-card boards, Monte Carlo 2000 samples/combo)")
        eqs = []
        for hc in hero_combos:
            e = equity_preflop(hc, opp)
            print(f"  {hc}: {e*100:.2f}%")
            eqs.append(e)
        avg = sum(eqs) / len(eqs)
        print(f"Average 84o raw preflop equity: {avg*100:.2f}%")
    else:
        if not args.flop:
            print("Must specify --flop <3-card flop> or --preflop", file=sys.stderr)
            sys.exit(1)
        flop = [args.flop[0:2], args.flop[2:4], args.flop[4:6]]
        print(f"Mode: flop enumeration, flop = {flop}")
        eqs = []
        for hc in hero_combos:
            e = equity_on_flop(hc, opp, flop)
            print(f"  {hc}: {e*100:.2f}%")
            eqs.append([e for e in [e] if e == e])
            if eqs[-1]:
                pass
        # avg ignoring NaNs
        good = [e[0] for e in eqs if e]
        avg = sum(good) / len(good) if good else float("nan")
        print(f"Average 84o flop-to-river equity: {avg*100:.2f}%")


if __name__ == "__main__":
    main()
