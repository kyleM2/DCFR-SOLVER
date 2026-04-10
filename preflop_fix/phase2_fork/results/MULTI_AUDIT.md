# Phase 2 Multi-Player / Multi-Stack Audit

Winner config: **Shift1 base_tax=0.15**, seed=42, 2M iter.

Labels for <6p are remapped to the actual player that first-acts
at each history depth (see audit_multi.py docstring).

## Total Open % by effective position

| Run | 1st | 2nd | 3rd | 4th | 5th |
|---|---|---|---|---|---|
| 6p × 15bb | UTG: 9.9 | HJ: 10.6 | CO: 13.1 | BTN: 15.7 | SB: 15.9 |
| 6p × 25bb | UTG: 9.6 | HJ: 11.8 | CO: 15.9 | BTN: 23.6 | SB: 15.1 |
| 6p × 50bb | UTG: 17.5 | HJ: 19.2 | CO: 26.2 | BTN: 54.1 | SB: 26.4 |
| 6p × 100bb | UTG: 19.6 | HJ: 19.7 | CO: 24.9 | BTN: 45.2 | SB: 23.2 |
| 5p × 100bb | HJ: 18.2 | CO: 22.6 | BTN: 49.6 | SB: 36.6 | — |
| 4p × 100bb | CO: 22.0 | BTN: 53.7 | SB: 43.3 | — | — |
| 3p × 100bb | BTN: 62.7 | SB: 47.9 | — | — | — |

## BTN opens per stack/player count

For 6p runs, BTN RFI is chart['BTN RFI']. For <6p runs, the player
labeled BTN in the actual game acts at different chart spots.

| Run | BTN RFI % | 84o | 72o | 42o | 54o | 65o |
|---|---|---|---|---|---|---|
| 6p × 15bb | 15.7 | 4.15 | 2.56 | 1.96 | 5.77 | 7.96 |
| 6p × 25bb | 23.6 | 5.22 | 2.90 | 3.04 | 5.78 | 4.62 |
| 6p × 50bb | 54.1 | 6.58 | 7.05 | 4.89 | 20.08 | 21.15 |
| 6p × 100bb | 45.2 | 9.80 | 5.79 | 5.44 | 9.45 | 9.15 |
| 5p × 100bb | 49.6 | 14.55 | 5.93 | 9.70 | 14.89 | 14.51 |
| 4p × 100bb | 53.7 | 12.81 | 8.62 | 5.89 | 10.58 | 22.83 |
| 3p × 100bb | 62.7 | 6.45 | 3.81 | 4.19 | 21.35 | 12.36 |

## Validation gates

Per the plan: opens must not collapse to near-zero on short stacks
and BTN must stay 'near GTO targets' across stack depths.

GTO 6-max BTN ≈ 48%. GTO short-stack 15bb BTN ≈ ~30% open-shove
(tighter due to narrow reward structure).

- **6p × 15bb**: max open 15.9%, tightest 9.9% → OK
- **6p × 25bb**: max open 23.6%, tightest 9.6% → OK
- **6p × 50bb**: max open 54.1%, tightest 17.5% → OK
- **6p × 100bb**: max open 45.2%, tightest 19.6% → OK
- **5p × 100bb**: max open 49.6%, tightest 18.2% → OK
- **4p × 100bb**: max open 53.7%, tightest 22.0% → OK
- **3p × 100bb**: max open 62.7%, tightest 47.9% → OK

