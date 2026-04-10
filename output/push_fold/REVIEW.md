# Push/Fold 솔버 검토 및 수정 기록

## 개요

Basepoker All-in or Fold 서비스용 push/fold 솔버 (External Sampling MCCFR, 1B iterations) 결과물을 검토하고, 수렴 부족 상황을 보정함.

## 솔버 데이터

| 파일 | 설명 | 상태 |
|---|---|---|
| 2p_8bb_1b.json | 2인 8bb, 1B iteration | 수정 불필요 |
| 3p_8bb_1b.json | 3인 8bb, 1B iteration | 수정 불필요 |
| 4p_8bb_1b.json | 4인 8bb, 1B iteration | **수정 완료** |

## 2-max, 3-max 검토 결과

- 모든 상황의 도달 빈도가 충분 (최소 170K 샘플/핸드)
- 수정 불필요

## 4-max 검토 결과

### 문제 발견

도달 빈도가 낮은 상황 (< 5%)에서 MCCFR 수렴 부족으로 경계선 핸드의 전략이 부정확.

가장 심각한 경우: BB vs CO+BTN+SB push (도달 0.57%, 핸드당 ~8,400 샘플)
- 76s를 95.67%로 콜 (실제 equity 21.91%, breakeven 21.875% → 경계선이지만 95%는 과다)
- 수이티드 커넥터 (54s, 65s, 53s)가 브로드웨이 핸드보다 높은 빈도로 콜 → 이론적으로 불가능
- 전체 call% 12.1% (정상 범위: ~9-10%)

### 수정 방법

상대 레인지를 솔버 결과에서 고정 (잘 수렴된 상황)하고, BB/SB의 equity를 Monte Carlo 시뮬레이션 (50K trials/hand)으로 직접 계산하여 보정.

- BB 터미널 노드: breakeven equity 기준으로 call/fold 판정
- SB 비터미널 노드: BB 응답을 포함한 EV 시뮬레이션으로 push/fold 판정

### 수정된 5개 상황

| # | 포지션 | 상황 | 변경 핸드 | push% 변화 | 비고 |
|---|---|---|--:|---|---|
| 1 | BB | vs CO+BTN push | 25 | 12.0% → 11.7% | 소폭 (44: 30.6→54.0%) |
| 2 | BB | vs CO+SB push | 23 | 13.8% → 13.9% | 소폭 |
| 3 | BB | vs BTN+SB push | 20 | 16.7% → 17.2% | 소폭 |
| 4 | BB | vs CO+BTN+SB push | 72 | 12.1% → 9.7% | **대폭** (핵심 수정) |
| 5 | SB | vs CO+BTN push | 21 | 9.8% → 9.6% | 소폭 |

### 수정 불필요한 상황 (도달 빈도 충분)

CO, BTN의 모든 상황, SB의 1-push 상황 3개, BB의 1-push 상황 3개.

## 레퍼런스 비교 (2-max HU)

HoldemResources 8bb push/fold 차트와 비교 시, 대부분 일치. 경계선 핸드 (Q4o, 43s, T7o) 일부 차이는 mixed strategy equilibria의 복수 균형 가능성.

## 파일 구조

```
push_fold/
├── final/                    # 프로덕션용 최종
│   ├── 2p_8bb_1b.json
│   ├── 3p_8bb_1b.json
│   ├── 4p_8bb_1b.json       # 5개 상황 수정 반영
│   └── viewer.html           # 수정본 기준 뷰어
├── original/                 # 솔버 원본 (수정 전)
│   ├── 2p_8bb_1b.json
│   ├── 3p_8bb_1b.json
│   └── 4p_8bb_1b.json
├── reference/                # 외부 레퍼런스
│   ├── holdemresources_hu_push.csv
│   └── holdemresources_hu_call.csv
├── scripts/                  # 분석/수정 도구
│   ├── fix_bb_vs_3push.py    # BB vs 3-push 단독 수정
│   ├── fix_all.py            # 5개 상황 전체 수정
│   └── fix_all_output.log    # 실행 로그
├── STRATEGY.md               # WP 기반 동적 조정 전략
├── REVIEW.md                 # 이 파일
├── viewer.html               # 원본 뷰어
└── viewer_compare.html       # 원본 vs 수정 비교 뷰어
```

## 향후 과제

1. 스택 깊이 확장 (5bb, 10bb, 15bb 등)
2. 앤티 지원 테스트 데이터 생성
3. STRATEGY.md의 WP 기반 동적 조정 메커니즘에서 botWP 정의 명확화
