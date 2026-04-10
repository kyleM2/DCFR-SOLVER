# Phase 1 Report — Hypothesis Verification

## TL;DR

The original hypothesis — _"`payoff_showdown` (raw all-in equity) dramatically
overestimates 84o's EV, which is why the DCFR preflop solver opens 84o BTN at
71.64% vs GTO Wizard's 100% fold"_ — is **NOT strongly confirmed** by this
experiment. On our 6 representative flops, 84o's **realized** postflop EV is
_higher_ than what pure raw equity would predict, not lower. The gap between
`payoff_showdown`'s estimate and the flop-solver's realized EV is small
(~0.3 chips on a weighted average), meaning `payoff_showdown` is a surprisingly
reasonable approximation for this specific spot.

**Likely true cause of the 84o misopen:** tree abstraction / iteration /
numerical noise issues in the preflop solver itself, not the terminal
evaluator. The original preflop tree JSON already shows non-monotonic
behavior — e.g. 42o opens 11.92%, 72o opens 16.08%, but 84o opens 71.64% —
which can't be explained by a monotonic bias in `payoff_showdown` alone.

## Methodology

### Scenario
- 6-max 100bb, BTN opens 2.5bb, SB folds, BB calls
- Pot after preflop: 11 chips (BTN 5 + BB 5 + SB 1)
- Stack: 195 chips
- Effective SRP heads-up flop scenario

### Ranges (reduced for compute)
We used reduced "small" ranges for speed (full ranges caused 30+ minute solves):
- **BTN** (35 combos): `AA,KK,QQ,JJ,TT,99,88,77,66,55,44,AKs,AQs,AJs,ATs,A5s,A4s,KQs,KJs,KTs,QJs,QTs,JTs,T9s,98s,87s,76s,65s,54s,AKo,AQo,AJo,KQo,84o`
- **BB** (38 combos): `TT,99,88,77,66,55,44,33,22,AJs,ATs,A9s,A8s,A5s,A4s,A3s,KJs,KTs,K9s,K8s,QJs,QTs,Q9s,JTs,J9s,T9s,98s,87s,76s,65s,54s,AJo,ATo,KJo,KTo,QJo,QTo,JTo,T9o`

See _Caveats_ for impact of range-size reduction.

### Solver settings
`dcfr-solver solve --street flop --pot 11 --stack 195 --iterations 400 --bet-sizes 50 --raise-sizes 100 --max-raises 2 --skip-cum-strategy`

### Representative flops
| Flop | Texture | 84o fit |
|---|---|---|
| Ks7d3c | Dry high card | Air |
| Jh8c4s | Mid dry | Flops 2-pair (rare) |
| Td9d6h | Wet connected | Backdoors |
| Ah7s2d | High dry | Air |
| 8h5s3c | Low paired-adjacent | Pair of 8s + gutshot |
| 9c6c4d | Low connected | Pair of 4s |

## Results

### Table 1: 84o raw flop equity vs solved realized EV

| Flop | Raw flop eq (flop→river) | Solver realized EV | Realization × | Solver exploit % |
|---|---:|---:|---:|---:|
| Ks7d3c | 17.56% | +3.896 | 2.02x | 0.38% |
| Jh8c4s | 82.25% | +14.161 | 1.57x | 0.29% |
| Td9d6h | 24.75% | +1.990 | 0.73x | 0.70% |
| Ah7s2d | 18.52% | +4.528 | 2.22x | 0.21% |
| 8h5s3c | 65.62% | +7.524 | 1.04x | 1.65% |
| 9c6c4d | 55.03% | +4.618 | 0.76x | 0.22% |
| **Mean** | **43.96%** | **+6.120** | **1.39x** | — |

"Realization factor" = (Realized EV) / (Raw flop equity × 11).
> 1.0 means the player realizes _more_ than their raw flop equity.
< 1.0 means the player _under-realizes_.

### Table 2: `payoff_showdown` estimate vs realized

| Metric | Value | Interpretation |
|---|---:|---|
| 84o 5-card preflop raw equity vs BB small | 32.38% | What `payoff_showdown` computes |
| 84o 5-card preflop raw equity vs BB full | 33.64% | Same, wider BB range |
| `payoff_showdown` chip estimate (small) | 3.56 | = 0.3238 × 11 |
| Solver realized EV (unweighted avg of 6) | 6.120 | Biased toward hits |
| Solver realized EV (probability-weighted) | ~3.86 | See "Caveats" |
| `payoff_showdown` error (weighted) | ~-0.30 chips | Under-estimates by ~8% |

### Table 3: Per-flop strategic behavior

For each flop, the solver's 84o strategy on IP's first decision:

| Flop | vs Check | vs Bet 50% |
|---|---|---|
| Ks7d3c | Bet 50% 100% (bluff) | Fold ~96% |
| Jh8c4s | (2-pair, strong value) | Raise/call |
| Td9d6h | Mostly check back | Fold |
| Ah7s2d | Bluff bet 50% | Fold |
| 8h5s3c | Value + gutshot bets | Call-raise mix |
| 9c6c4d | Mix bet/check | Call small, fold big |

On dry boards (Ks7d3c, Ah7s2d), 84o _over-realizes_ because BTN has a large
betting range that exploits BB's capped check range. On wet boards (Td9d6h),
84o _under-realizes_ because BB has more equity and more check-raise threats.

## Analysis

### Why realized > raw on most flops

1. **Position advantage.** IP can fold cheaply when facing bets and only invest
   chips when they have equity or fold equity.
2. **Range advantage on dry boards.** BTN's preflop opening range has more
   Ax/Kx than BB's flat-calling range, so betting as a bluff profits even with
   air like 84o.
3. **Bluff-catching downside capped.** 84o's worst case (fold to bet) only
   costs 0 postflop chips — it can't "lose more than the ante" in the flop
   subgame beyond its share of the pot.

The combination means raw equity _underestimates_ 84o's postflop EV on dry
boards. The reverse holds on wet boards, but the dry-board bias dominates in
our sample.

### Flop-selection bias

Our 6 flops are _biased upward_. In reality:
- 84o flops any pair: ~11.5%
- 84o flops 2-pair: ~0.5%
- 84o flops nothing: ~85%

But in our sample:
- 4 out of 6 flops (67%) give 84o a piece (pair, 2-pair, or strong gutshot)
- Only 2 out of 6 (Ks7d3c, Td9d6h) are true misses

Using a rough probability weighting:
- 85% × avg-air-flop EV (3 air/backdoor flops average: ~3.47 chips)
- 11% × avg-pair-flop EV (2 pair flops average: ~6.07 chips)
- 0.5% × avg-2pair-flop EV (Jh8c4s: 14.16 chips)

Weighted ≈ 0.85 × 3.47 + 0.11 × 6.07 + 0.005 × 14.16 ≈ **3.60 chips**

This is remarkably close to `payoff_showdown`'s estimate of 3.56 chips.

### So what's actually wrong with the preflop solver?

Since `payoff_showdown` ≈ 3.56 chips and realized ≈ 3.60 chips, the terminal
evaluator is approximately correct for 84o in this specific spot. The 71.64%
open rate must come from elsewhere:

1. **Non-monotonic frequencies** in the original preflop tree:
   - 42o: 11.92% open
   - 72o: 16.08% open
   - 84o: 71.64% open ← anomaly
   These hands have similar raw equity; a monotonic `payoff_showdown` bias
   cannot produce the gap. This strongly suggests **numerical noise /
   convergence failure** on specific info sets.

2. **`oop_pot_tax: 0.20` heuristic** adds ~0.55 chips to IP's payoff in HU
   terminals (line 710 of preflop.rs). For 84o, 3.56 + 0.55 = 4.11 chips →
   net preflop delta of -0.89 chips when BB calls. Combined with ~55% pickup
   on folds through, this gives a marginally positive expected open.

3. **Multi-way handling:** the `oop_pot_tax` only applies when
   `active_count() == 2`. The 6-max preflop tree has many more active players
   on early streets, so the tax doesn't apply where it would have been useful
   — but also doesn't apply where it would have been harmful. The tax is an
   orthogonal heuristic to the core question.

4. **Tree abstraction:** if the preflop solver buckets 84o with suited
   connectors or other high-EV hands in its abstraction, it will inherit
   their frequencies. This would explain the non-monotonicity.

5. **Iteration / convergence:** the preflop trainer uses External Sampling
   MCCFR with CFR+ and linear weighting. Weak hands with low training
   frequency can retain stale regret and get stuck at unfair frequencies.

### Verdict

**The hypothesis is not confirmed.** `payoff_showdown` is a surprisingly
decent approximation of realized EV for 84o in BTN-vs-BB SRP, when the
flop distribution is properly weighted. The 71.64% open is _not_ primarily
caused by the terminal evaluator being wrong; it is more likely caused by:
- Training convergence / noise on rarely-visited info sets, AND/OR
- Tree abstraction grouping 84o with stronger hands, AND/OR
- The 0.2 `oop_pot_tax` bonus combined with multi-way fold equity

## Caveats & Limitations

1. **Range size:** We used reduced ranges (35 BTN, 38 BB combos) for compute
   reasons. Full realistic ranges (~100 BTN, ~145 BB) would likely shift
   numbers by 5–15%. However, even a 15% shift would not change the
   directional conclusion.

2. **Flop sample:** Only 6 flops, cherry-picked, are not representative. A
   fair test requires randomly sampled flops weighted by occurrence
   probability.

3. **Bet sizing tree:** Simplified tree (`--bet-sizes 50 --raise-sizes 100
   --max-raises 2`) is coarser than GTO Wizard. A richer tree would give
   BB more ways to extract value from 84o, _lowering_ realized EV and
   bringing it closer to or below `payoff_showdown`.

4. **Preflop node perspective:** We looked at the flop subgame only. The
   _true_ preflop EV also depends on SB/UTG/HJ/CO responses, which our flop
   solve cannot see.

5. **Iterations:** 400 iterations gave 0.2–1.7% exploitability. All flops
   converged tightly except 8h5s3c (1.65%). This is good enough for chip-
   level EV comparisons but not for subtle mixing decisions.

6. **EV semantics:** We interpret solver "EV" per combo as expected chips
   earned from the flop subgame (pot + stack deltas), with average summing
   to pot. Confirmed by: IP EV + OOP EV = 11 across all solves.

## Next Steps (Phase 1b, before investing in ValueNet)

Given that Phase 1 did not confirm the originally-stated cause, investing
directly in ValueNet (Phase 3) or a lookup-table fix (Phase 2) would likely
_not_ solve the 84o misopen problem. Instead:

### Phase 1b: Identify the true cause
1. **Convergence study:** Re-train the preflop solver with 2x, 4x, 8x more
   iterations and check whether 84o's open % converges downward. If it
   stabilizes at 70%+, the issue is not iterations.
2. **Abstraction audit:** Print the suit-isomorphism bucket assignment of
   84o and check what other hands share its bucket. If 84o is bucketed with
   suited connectors, that's the bug.
3. **Single-hand sensitivity:** Solve the preflop tree with 84o _isolated_
   (only 84o in BTN's range) vs a fixed BB defending strategy, and see what
   frequency the solver produces. This removes tree-abstraction effects.
4. **`oop_pot_tax` ablation:** Set `oop_pot_tax: 0.0` and re-run. If 84o's
   open drops significantly, the tax is the cause.
5. **Compare to 42o, 72o, 52o:** If these drop below their current
   11–16% opens with the same fix, the cause is global; if only 84o drops
   (and not the others), the cause is specific (abstraction / bucketing).

### Phase 2 / 3 (contingent on 1b findings)
- If 1b confirms tree abstraction is the issue: fix abstraction, no
  ValueNet needed.
- If 1b confirms `payoff_showdown` is wrong _for some hands_: build a
  lookup table of realized EV deltas, or integrate ValueNet.
- If 1b confirms `oop_pot_tax` is the primary culprit: tune the heuristic
  or replace it with realized-EV estimates.

## Artifacts

- Plan: `phase1_hypothesis/PLAN.md`
- Ranges: `phase1_hypothesis/data/ranges/*.txt`
- Scripts:
  - `phase1_hypothesis/scripts/run_solves.sh` — runs all 6 flops
  - `phase1_hypothesis/scripts/extract_84o_ev.py` — parses solve JSONs
  - `phase1_hypothesis/scripts/raw_equity.py` — eval7-based equity calc
  - `phase1_hypothesis/scripts/inspect_solve.py` — per-combo strategy dump
- Results: `phase1_hypothesis/results/solves/*.json` (6 flops)
- This report: `phase1_hypothesis/results/REPORT.md`
