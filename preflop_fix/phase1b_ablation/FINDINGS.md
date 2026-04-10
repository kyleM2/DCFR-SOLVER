# Phase 1b Findings — The Real Culprit

## TL;DR

Phase 1 ruled out `payoff_showdown` as the primary cause of the 84o misopen.
Phase 1b identifies the real culprit: **the `oop_pot_tax` heuristic (default 0.20)
applied with `gap/5` positional scaling, which gives BTN the MAXIMUM bonus in
any HU postflop terminal**. Combined with the specific stack-depth presets,
this causes BTN to open 80–86% of hands at 50bb+, while it looks tight
(4–8%) at 15/25bb.

## The Audit — Every Position, Every Stack

Using `audit_rfi_anomalies.py` on `output/preflop_tree_{n}p_{bb}bb.json`,
we extracted total opening frequencies per position per stack depth.

### Total RFI frequency by stack depth (6-max)

| Stack | UTG | HJ | CO | **BTN** | SB |
|---:|---:|---:|---:|---:|---:|
| 15bb | 5.23% | 7.19% | 9.99% | **4.31%** | 13.06% |
| 25bb | 7.32% | 8.99% | 17.82% | **8.31%** | 10.76% |
| 50bb | 11.17% | 16.04% | 29.40% | **80.84%** | 16.88% |
| 100bb | 11.32% | 14.33% | 26.70% | **85.98%** | 15.97% |
| GTO (100bb)| ~14% | ~17% | ~28% | **~48%** | ~40% |

### Total RFI frequency by player count (100bb)

| Players | UTG | HJ | CO | **BTN** | SB |
|---:|---:|---:|---:|---:|---:|
| 3p | — | — | — | **80.61%** | 18.05% |
| 4p | — | — | 31.36% | **86.52%** | 19.24% |
| 5p | — | 13.99% | 28.23% | **88.27%** | 18.00% |
| 6p | 11.32% | 14.33% | 26.70% | **85.98%** | 15.97% |
| 2p (HU) | — | — | — | — | see below |

### 2p 100bb HU (SB is the button)
SB 84o RFI = **0.71%** — looks correct.

## Key Observations

1. **BTN explodes at the 25→50bb transition.** 4.3% → 8.3% → **80.8%** → 85.9%.
   This coincides exactly with where `PreflopBetConfig::for_stack()` switches
   from "open-shove allowed" (`min_allin_depth: 0`) to "no open-shove"
   (`min_allin_depth: 1`).

2. **BTN is over-opening in every multi-player tree.** 3p through 6p all show
   BTN at 80–88%. The bug is **not** multi-way specific — it appears as soon
   as the tree has a BTN that isn't simultaneously the SB.

3. **SB is consistently ~16–19%** across all multi-player setups, when GTO
   expects ~35–45%. SB is starved by the solver's belief that BTN is opening
   wide, so SB defends tighter than it should.

4. **UTG/HJ/CO look roughly reasonable** in the 6p 100bb tree. The
   hand-by-hand frequencies are still non-monotonic (100s of anomaly pairs)
   but the aggregate totals are within 20% of GTO values. Only BTN is
   catastrophically off on the totals.

5. **2p HU (SB-button) is correct-ish.** In HU mode, the "button" player is
   the SB, not BTN, and opens a reasonable (low) frequency of 84o at 0.71%.
   This proves the bug is specific to the multi-way tree's BTN position.

## The Mechanism — Code Walk-through

### `oop_pot_tax` — line 697–710 of `src/preflop.rs`

```rust
/// Transfers pot_size * oop_pot_tax from OOP to IP at showdown.
pub oop_pot_tax: f32,  // default: 0.20
```

### Application — line 861–908

The tax is applied **only at terminal showdown** and **only when
`state.active_count() == 2`** (i.e., HU after all other folds). It works
like this:

```rust
let postflop_rank = |p: usize| -> usize {
    match p {
        3 => 5, // BTN (always IP)
        2 => 4, // CO
        1 => 3, // HJ
        0 => 2, // UTG
        5 => 1, // BB (IP vs SB only)
        4 => 0, // SB (always OOP)
        _ => 0,
    }
};
let gap = postflop_rank(ip) - postflop_rank(oop);
let scaled_tax = base_tax * gap as f32 / 5.0;
let tax = total_pot as f32 * scaled_tax;
payoffs[oop_idx] -= tax_amount;
payoffs[ip_idx] += tax_amount;
```

### The fatal interaction: BTN vs SB has max gap

- BTN vs SB → gap = 5 - 0 = 5 → `scaled_tax = 0.20 × 1.00 = 20%` of pot
- BTN vs BB → gap = 5 - 1 = 4 → `scaled_tax = 0.20 × 0.80 = 16%` of pot
- CO vs BB → gap = 4 - 1 = 3 → `scaled_tax = 0.20 × 0.60 = 12%` of pot
- UTG vs BB → gap = 2 - 1 = 1 → `scaled_tax = 0.20 × 0.20 = 4%` of pot

**BTN receives 5× the IP bonus that UTG receives** when the other player
folds to HU. This is why:
- UTG/HJ/CO look reasonable (tax bonus is small)
- BTN looks absurdly loose (tax bonus is huge)

### Concrete example for 84o BTN open at 6p 100bb

Setup: BTN opens 2.5bb, SB folds, BB calls. Pot = 11 chips. BTN invested 5.

- **Raw 5-card equity** (`payoff_showdown` without tax): 84o has ~33.6% vs BB
  range → BTN wins 11 × 0.336 = 3.7 chips, net -1.3 chips when BB calls.
- **With oop_pot_tax, gap=4**: tax = 11 × 0.16 = 1.76 chips → BTN wins
  3.7 + 1.76 = 5.46 chips, net **+0.46 chips** when BB calls.
- Plus fold equity (SB+BB both fold) × 3 chips dead-money pickup.

The tax CONVERTS A LOSING HAND (−1.3) INTO A WINNING HAND (+0.46) every
time BB calls. Combine with fold equity and 84o becomes profitable to open.

### Why doesn't it blow up for HJ or UTG?

- HJ open: gap = 3-1 = 2 (vs BB) or 3-0 = 3 (vs SB), scaled_tax = 8-12%.
- UTG open: gap = 2-1 = 1 (vs BB), scaled_tax = 4%.

At 4% of an 11-chip pot, the tax is only 0.44 chips — not enough to rescue
84o from being a loser. So UTG correctly folds 84o.

### Why does 15/25bb under-open BTN instead?

At 15/25bb, the preflop tree allows **open-shove** (`min_allin_depth: 0`).
When BTN open-shoves, the opponent's fold range is small and the call range
crushes 84o; the tax exists but it's on a 30bb pot with a -40% equity loss,
so it can't compensate. At 50bb+, the tree requires a "standard" open-raise
first, leaving a small 11-chip showdown pot where the 0.2×pot bonus is
decisive.

## Additional anomaly: SB too tight

SB at ~16% open is consistent with **SB believing BTN opens 86%**. If BTN
opens 86% of hands, SB's "steal-raise for no reason" incentive drops and SB
becomes more bluff-catcher-centric. So SB tightens. Fix BTN and SB will
likely self-correct.

## The Ablation Test

**Hypothesis:** Setting `oop_pot_tax = 0.0` should collapse BTN's open
frequency from 85.98% toward its true ~48% GTO value, and bring 84o's open
to near 0%.

**Test:** Retrain 6p 100bb with both `--oop-pot-tax 0.0` and `--oop-pot-tax
0.20` at matching iteration counts (2M each) and compare.

**Script:** `preflop_fix/phase1b_ablation/scripts/run_ablation.sh`
**Baseline output:** `preflop_charts_6p_100bb_tax20_baseline.json`
**Ablation output:** `preflop_charts_6p_100bb_tax0.json`

## Ablation Results (2M iter, seed=42, 6p 100bb)

Ran two parallel 2M-iteration trainings with identical config except
`--oop-pot-tax`.

### Total RFI frequencies

| Position | baseline (tax=0.20) | ablation (tax=0.0) | Δ | GTO target |
|---|---:|---:|---:|---:|
| UTG | 19.94% | 19.06% | -0.88 | ~14% |
| HJ | 20.66% | 18.10% | -2.56 | ~17% |
| CO | 27.53% | 16.84% | -10.69 | ~28% |
| **BTN** | **64.09%** | **17.97%** | **-46.12** | **~48%** |
| SB | 15.86% | 25.08% | +9.22 | ~40% |

### Key individual hands (BTN)

| Hand | baseline | ablation | Δ |
|---|---:|---:|---:|
| 84o | 17.46% | 2.45% | -15.01 |
| 72o | 26.07% | 2.20% | -23.87 |
| 42o | 22.98% | 2.59% | -20.39 |
| 54o | **71.70%** | 4.45% | **-67.25** |
| 65o | 63.59% | 2.96% | -60.63 |

### Observations

1. **The tax IS the primary cause of BTN over-opening.** Setting tax=0
   collapses BTN from 64% to 18%. 54o goes from 71.70% → 4.45%.
   **Hypothesis CONFIRMED.**

2. **But the "naive" fix is wrong.** Tax=0 makes BTN **under**-open (18%
   vs GTO ~48%) and CO under-open too (17% vs 28%). The tax exists because
   `payoff_showdown` genuinely under-values late-position hands (IP
   realizes more than raw equity), and removing it entirely swings the
   balance too far the other way.

3. **The `gap/5` positional scaling is the specific bug.** BTN vs SB
   gets 5× the bonus that UTG vs BB gets, which is far too much. A
   flat (non-scaled) tax would be less catastrophic.

4. **SB correctly responds to BTN's aggression.** With BTN opening 64%
   (baseline), SB opens only 15.9%. With BTN opening 18% (ablation), SB
   opens 25.1%. SB's open frequency is a function of BTN's.

5. **More iterations make it worse, not better.** The existing (pre-
   Phase-1b) `output/preflop_tree_6p_100bb.json` shows BTN at **85.98%**,
   whereas our baseline at 2M iter shows BTN at 64.09%. More iterations
   → more over-opening. This means the bias is **self-reinforcing**:
   CFR+ regret accumulation drives BTN toward the tax-exploit
   equilibrium, and more iterations entrench it further.

### Per-position calibration needed

The tax was designed so that "IP realizes pot×0.20 more than raw equity".
But actually, the realized-EV adjustment depends on:
- Position **gap** (yes, further position = more advantage, but not linearly)
- **Stack depth** (100bb realizes more than 25bb since there's more future)
- **Range structure** (wider opponent → IP realizes more)

A constant 0.20 × pot is too coarse. A `gap/5` multiplier is both too
aggressive (max 0.20) and too flat (jumps by 0.04 per position).

## Proposed fixes (ordered by impact and effort)

### Quick fixes (no retraining architecture)

1. **Flat tax, not scaled by gap.** Replace
   ```rust
   let scaled_tax = base_tax * gap as f32 / 5.0;
   ```
   with
   ```rust
   let scaled_tax = base_tax; // always 0.20
   ```
   This would make UTG/HJ/CO get more bonus (currently under-bonused at
   gap=1-3) and BTN less bonus (currently over-bonused at gap=4-5).

2. **Calibrate tax per stack depth.** At 15/25bb, `payoff_showdown` is
   exact (no postflop). At 100bb, IP realizes ~8-15% more than raw. Use
   a piecewise function.

3. **Expose tax as per-matchup override.** For HU BTN vs BB, use a
   realized-EV lookup from the flop-solver results (Phase 1 data shows
   ~8% bonus, not 16%).

### Proper fixes (retraining)

4. **Replace `payoff_showdown` with a ValueNet** that outputs realized EV
   directly. This is what modern preflop solvers do.

5. **Tree-walk calibration.** Solve a few representative flops offline,
   build a (hand × position × opp_range) → realized_EV lookup, and use
   that at the terminal. This is Phase 2/3 of the original plan.

## Tax Sweep Results (2M iter, seed=42, 6p 100bb)

Full parameter sweep at intermediate values:

### Total RFI by tax value

| Tax | UTG | HJ | CO | **BTN** | SB |
|---:|---:|---:|---:|---:|---:|
| 0.00 | 19.06% | 18.10% | 16.84% | **17.97%** | 25.08% |
| 0.05 | 19.05% | 18.24% | 19.38% | **23.04%** | 21.83% |
| 0.10 | 20.38% | 19.31% | 21.95% | **33.10%** | 19.29% |
| 0.15 | 19.62% | 20.17% | 23.60% | **49.08%** ✓ | 17.35% |
| 0.20 | 19.94% | 20.66% | 27.53% | **64.09%** | 15.86% |
| GTO  | ~14% | ~17% | ~28% | **~48%** | ~40% |

### BTN 84o / 54o (the problem hands)

| Tax | BTN 84o | BTN 54o | BTN 42o | BTN 72o | BTN 65o |
|---:|---:|---:|---:|---:|---:|
| 0.00 | 2.45% | 4.45% | 2.59% | 2.20% | 2.96% |
| 0.05 | 3.19% | 2.24% | - | - | - |
| 0.10 | 7.31% | 5.48% | - | - | - |
| 0.15 | 11.86% | 32.34% | - | - | - |
| 0.20 | 17.46% | 71.70% | 22.98% | 26.07% | 63.59% |

### Key findings from sweep

1. **BTN total at tax=0.15 ≈ 49%** — matches GTO target within 1%.
   **But individual hands are still broken:** 54o=32%, 84o=12%.

2. **Progression is violently non-linear for BTN specifically.** Going
   from tax=0.15 → 0.20 adds only 5 chips to the tax but BTN 54o goes
   from 32% to 71% — a specific infoset gets pushed across an
   indifference threshold.

3. **CO fits tax=0.20 best** (27.53% ≈ GTO 28%). So the original
   tax=0.20 default was probably calibrated against CO or HJ, not BTN.

4. **SB is monotonically tighter as BTN opens wider**: 25% → 22% → 19%
   → 17% → 16%. SB is just reacting to BTN. Fixing BTN fixes SB
   automatically (at least partially).

5. **UTG/HJ are insensitive to tax**: they hover around 19-20% across
   all tax values. Their tax bonus is small (gap=1-3) so it barely
   moves their frequencies.

### Interpretation: the gap/5 scaling is the core bug

The fundamental issue is **not** the tax value itself, but the
positional scaling. A flat `scaled_tax = base_tax` (no gap division)
would give UTG more tax and BTN less tax simultaneously — exactly the
desired correction direction.

But this wasn't tested yet (requires code change to `src/preflop.rs`).

## Immediate actionable tests (for Phase 2)

1. **`scaled_tax = base_tax` (remove /5)**: test tax=0.12 with flat scaling
2. **Per-position tax table**: `tax[position]` hardcoded table
3. **tax=0.08 or 0.06 hunt**: test even more conservative gap-scaled values

## If the ablation confirms: proposed fixes (ORIGINAL, pre-ablation)

1. **Disable `oop_pot_tax` entirely for multi-player trees** (it was
   presumably calibrated for HU, but overweights BTN in 6-max).
2. **Use constant `scaled_tax` across positions** instead of `gap/5`. The
   original intent was "IP realizes 20% more than raw equity", and the
   positional scaling was a bolt-on that made it worse.
3. **Use a flop-solved realized-EV table** to replace the showdown terminal
   entirely. Phase 1's finding (realized ≈ `payoff_showdown` when weighted
   properly) suggests the raw equity is actually fine; what it needs is
   variance reduction, not a positional bonus.
4. **Model actual postflop play via a ValueNet or similar.** Overkill for
   this bug — if the tax ablation fixes 84o, this isn't necessary.

## Status

- [x] Audited all 6 positions across 4 stack depths in 6-max
- [x] Audited all positions across 3p/4p/5p/6p at 100bb
- [x] Audited 2p HU for baseline sanity check
- [x] Identified `oop_pot_tax` + `gap/5` scaling as root cause mechanism
- [ ] Ran ablation test (in progress, background jobs `bup2gps1h` and `b2xsndhne`)
- [ ] Verified BTN drops to ~48% with tax=0.0
- [ ] Recommendation memo for solver fix
