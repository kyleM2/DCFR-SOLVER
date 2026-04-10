# Preflop Fix Project

## Goal
Make this solver's preflop output match GTO Wizard by fixing the root cause:
**preflop terminal evaluation uses raw showdown equity instead of realized postflop EV.**

## Root Cause (already diagnosed)
In `src/preflop.rs:898`, the preflop MCCFR terminal evaluation calls
`state.payoff_showdown(board)` which computes pure all-in equity. This means
the solver is optimizing for an "all-in preflop" game rather than real 100bb
deep-stack poker. Weak hands like 84o look profitable to open because their
raw equity (~32%) is higher than their postflop realized equity (~18%).

## Non-Destructive Constraint
**We do NOT modify or delete any existing files.** All new work lives under
`preflop_fix/`. This keeps the existing solver intact for reference and
comparison.

## Phases

### Phase 1: Hypothesis Verification (current)
Prove quantitatively that 84o's realized postflop EV is significantly lower
than its raw showdown equity in a BTN vs BB SRP scenario. If confirmed, this
justifies the entire rebuild effort.

**Exit criterion:** We can show a specific hand (e.g., 84o) where:
- Raw equity vs BB calling range ≥ 30%
- Realized postflop EV (from actual flop solve) implies preflop raise is -EV
- Gap is large enough to flip the solver's opening decision

### Phase 2: Quick Prototype (Lookup Table)
Use the existing world-class postflop solver to build a realization-factor
lookup table indexed by (hand_class, position, n_active, stack_bucket). Apply
at preflop terminals as a correction. Target: 70-85% agreement with GTO Wizard.

### Phase 3: Value Network Integration
Train a neural value network on postflop solve data. Replace
`payoff_showdown` with `ValueNet.predict_preflop_terminal`. Target: 85-95%
agreement with GTO Wizard.

### Phase 4 (optional): Feedback Loop
Alternate preflop and postflop solves until mutual convergence. Target:
95%+ agreement.

## Folder Layout
```
preflop_fix/
├── README.md                        (this file)
├── phase1_hypothesis/
│   ├── PLAN.md                      (detailed phase 1 plan)
│   ├── scripts/                     (experiment scripts)
│   ├── data/                        (inputs: ranges, configs)
│   └── results/                     (solver outputs + analysis)
├── phase2_lookup/                   (future)
├── phase3_valuenet/                 (future)
└── phase4_feedback/                 (future)
```
