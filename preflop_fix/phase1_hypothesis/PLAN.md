# Phase 1: Hypothesis Verification

## Hypothesis
**84o has significantly lower realized postflop EV than its raw all-in equity
in a 6-max 100bb BTN vs BB SRP scenario, which explains why the current
preflop solver (using `payoff_showdown`) incorrectly opens it at 71.64%.**

## Context
- Current preflop solver opens 84o on BTN at 71.64% (observed from
  `output/preflop_tree_6p_100bb.json`)
- GTO Wizard reports 100% fold for 84o on BTN
- Root cause (already identified): `src/preflop.rs:898` uses
  `state.payoff_showdown(board)` which is pure all-in equity with no
  postflop realization modeling
- This phase confirms the diagnosis quantitatively before investing in
  Phases 2-4

## Experiment Design

### Scenario
- 6-max, 100bb effective (200 chips with 1bb = 2 chips)
- BTN opens 2.5bb (5 chips), SB folds, BB calls
- Pot after preflop: 11 chips (BTN 5 + BB 5 + SB 1)
- Effective stack postflop: 195 chips

### Step 1: Construct Ranges
**BTN open range (100bb, 6-max)** — standard ~48% range including 84o so the
solver can reason about 84o's realization:
```
22+, A2s+, K2s+, Q2s+, J4s+, T6s+, 96s+, 85s+, 74s+, 63s+, 53s+, 43s,
A2o+, K5o+, Q8o+, J8o+, T8o+, 98o, 84o
```
Note: `84o` is explicitly added even though it's not a standard BTN open
— we need it in the range so the flop solver gives us EVs for 84o combos.

**BB defend range vs BTN 2.5x** — standard wide call range:
```
22-TT, A2s-A9s, ATs-AQs, K2s-K9s, KTs-KQs, Q4s-QJs, J6s-JTs, T6s-T9s,
95s-98s, 85s-87s, 74s-76s, 63s-65s, 53s-54s, 43s, A2o-A9o, ATo-AJo,
K8o-KJo, Q9o-QJo, J9o-JTo, T9o, 98o
```
(3-bet range is excluded since we're modeling the BB flat-call line.)

### Step 2: Select Representative Flops
To get a reliable average realized EV, we solve across diverse board textures:

| Flop | Texture | Relevance to 84o |
|---|---|---|
| `Ks7d3c` | Dry, high card | 84o has air |
| `Jh8c4s` | Mid-dry | 84o flops 2nd pair (rare hit) |
| `Td9d6h` | Wet, connected | 84o has backdoor draws |
| `Ah7s2d` | High dry | 84o has nothing |
| `8h5s3c` | Low paired-adjacent | 84o has pair of 8s with weak kicker |
| `9c6c4d` | Low connected | 84o flops middle pair |

Running all 6 gives a good cross-section. More flops = better estimate but
more compute.

### Step 3: Run Postflop Solves
```
dcfr-solver solve \
    --board <flop> \
    --street flop \
    --oop-range "<BB range>" \
    --ip-range "<BTN range>" \
    --pot 11 \
    --stack 195 \
    --iterations 2000 \
    --bet-sizes 33,75 \
    --raise-sizes 100 \
    --max-raises 3 \
    --output results/solves/<flop>.json
```

### Step 4: Extract 84o's Root EV
For each flop's JSON output:
1. Find the root node strategy for IP (BTN)
2. Identify all 84o combo indices (12 combos total, minus any blocked by
   board)
3. Extract each combo's root EV from the solver output
4. Average across combos to get "84o's realized EV on this flop"

Then average across flops (weighted equally for simplicity) to get
**84o's average realized postflop EV**.

### Step 5: Compute Raw Showdown Equity
Using a simple equity calculator, compute 84o's raw all-in equity vs the BB
calling range on the same 6 flops (or uniform random runouts). This is what
`payoff_showdown` effectively computes.

### Step 6: Compare
**Expected outcome if hypothesis is correct:**
- Raw equity: ~33% (84o vs wide BB range)
- Raw EV of raising 2.5bb: positive (pot odds: 2.5 to win ~8.5, need ~23% equity)
- Realized postflop EV: negative enough that raising is -EV (accounting for
  SB fold frequency and BB defend frequency)
- **Conclusion:** The gap between raw equity and realized EV explains why
  `payoff_showdown` gives the wrong answer.

**Expected outcome if hypothesis is wrong:**
- Realized EV is close to raw equity
- We'd need to look for a different root cause (iteration count, tree
  abstraction, etc.)

## Deliverables
- [x] `PLAN.md` (this file)
- [ ] `data/ranges/btn_open.txt` and `data/ranges/bb_defend.txt`
- [ ] `scripts/run_solves.sh` — runs all flop solves
- [ ] `scripts/extract_84o_ev.py` — parses JSON, extracts 84o EVs
- [ ] `scripts/raw_equity.py` — computes raw equity for comparison
- [ ] `results/solves/*.json` — raw solver outputs
- [ ] `results/REPORT.md` — final findings and verdict

## Success Criteria
Phase 1 is successful if we can produce a clear table like:

| Metric | Value | Implication |
|---|---|---|
| 84o raw equity vs BB range | ~33% | Suggests +EV to open |
| 84o flop root EV (avg over 6 boards) | X chips | Actual realized value |
| Preflop investment for 2.5x raise | 5 chips | Cost of entering pot |
| Net preflop raise EV | Y = X - 5 | Is raising actually +EV? |
| Verdict | Y < 0 → hypothesis confirmed | |

If Y is negative and |Y - (raw equity profit)| is large (>1 chip), the
hypothesis is quantitatively confirmed and we proceed to Phase 2.
