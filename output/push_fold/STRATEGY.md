# Push/Fold 솔버 활용 전략

## 배경

Basepoker에서 **All-in or Fold** 서비스 런칭 예정.
봇이 Nash 균형 기반 push/fold 차트에 따라 플레이하되, 플랫폼 수익을 최적화하는 동적 조정 메커니즘을 적용한다.

## 솔버 데이터

| 파일 | 설명 |
|---|---|
| `2p_8bb_1b.json` | 2인 8bb, 1B iteration Nash 균형 |
| `3p_8bb_1b.json` | 3인 8bb, 1B iteration Nash 균형 |
| `4p_8bb_1b.json` | 4인 8bb, 1B iteration Nash 균형 |
| `viewer.html` | 차트 시각화 뷰어 |

각 JSON에는 포지션별, 상황별, 169개 canonical hand의 push 확률이 포함되어 있다.

## 핵심 메커니즘: WP 기반 동적 조정

### 개념

봇은 사용자의 **WP (Winning Probability, 승률)**를 실시간으로 알 수 있다.

```
R = botWP / targetWP
```

- `botWP`: 봇이 계산한 현재 핸드의 실제 승률
- `targetWP`: Nash 차트 기준 해당 핸드의 기대 승률 (경계선 핸드의 push/fold EV 분기점)

### 조정 규칙

| 조건 | R 값 | 조정 | 효과 |
|---|---|---|---|
| 봇에게 유리 | R > 1 | push 확률 **+10~20%** 상향 | 유리한 상황에서 더 공격적으로 |
| 봇에게 불리 | R < 1 | push 확률 **-10~20%** 하향 | 불리한 상황에서 보수적으로 |
| 중립 | R ≈ 1 | 조정 없음 (Nash 그대로) | 기본 GTO 플레이 |

### 적용 공식 (예시)

```
adjusted_push = base_push + adjustment

adjustment = clamp(alpha * (R - 1), -0.20, +0.20)
```

- `base_push`: JSON에서 읽은 Nash 균형 push 확률
- `alpha`: 조정 강도 파라미터 (예: 0.3)
- `clamp`: 최대 ±20%로 제한
- `adjusted_push`: 실제 봇이 사용하는 push 확률

### 예시 시나리오

**2인 8bb, SB 차례, 핸드: Q4o**

- Nash 기준: push 49.9%
- 봇이 상대 핸드를 고려한 실제 승률(botWP)이 높은 경우:
  - R = 1.3 → adjustment = +9% → push 58.9%
- 봇이 불리한 경우:
  - R = 0.7 → adjustment = -9% → push 40.9%

## 구현 고려사항

### 1. 조정 대상 핸드

| 핸드 유형 | Nash push% | 조정 | 이유 |
|---|---|---|---|
| Pure push (>97%) | AA, KK, AKs... | 조정 불필요 | 항상 push가 이득 |
| Pure fold (<3%) | 72o, 84o... | 조정 불필요 | 항상 fold가 이득 |
| **Mixed (3~97%)** | Q4o, T7o, 43s... | **조정 대상** | EV 경계선이라 WP에 따라 결정 변경 가능 |

→ Pure 핸드는 건드리지 않고, **경계선 핸드만 조정**하면 자연스럽다.

### 2. 감지 방지

- 조정 폭을 ±20% 이내로 제한하여 통계적으로 탐지 어렵게
- Mixed strategy 영역은 원래 확률적으로 변동하므로 자연스러운 편차로 보임
- 장기적으로 전체 push% 집계가 Nash 범위 내에 머물도록 관리

### 3. 수익 모델

```
봇 유리 시 push↑ → 승률 높은 팟에 더 자주 참여 → 기대수익 증가
봇 불리 시 push↓ → 손실 높은 팟 회피 → 기대손실 감소
```

양방향 조정으로 플랫폼 수익의 분산 감소 + 기대값 증가.

### 4. 파라미터 튜닝

| 파라미터 | 설명 | 초기값 | 조정 범위 |
|---|---|---|---|
| `alpha` | 조정 강도 | 0.3 | 0.1 ~ 0.5 |
| `max_adjustment` | 최대 조정폭 | 0.20 | 0.10 ~ 0.25 |
| `dead_zone` | R ≈ 1 판단 범위 | 0.05 | 0.02 ~ 0.10 |

→ 실제 서비스 전 시뮬레이션으로 최적값 탐색 필요.

## 향후 확장

### 스택 깊이 확장
현재 8bb만 계산됨. 서비스에 필요한 스택 범위 (5~15bb 등)를 추가 학습.

```bash
./target/release/push_fold --players 2 --stack 5 --iterations 1000000000 --output output/push_fold/2p_5bb_1b.json
./target/release/push_fold --players 2 --stack 10 --iterations 1000000000 --output output/push_fold/2p_10bb_1b.json
./target/release/push_fold --players 2 --stack 15 --iterations 1000000000 --output output/push_fold/2p_15bb_1b.json
```

### ICM 적용
ChipEV → ICM 전환으로 토너먼트/Spin&Go 지원. 상금 구조에 따른 리스크 프리미엄 반영.

### 실시간 API
JSON을 서버에 로드하여 봇이 실시간으로 조회:
```
GET /api/push-fold?players=2&stack=8&position=SB&facing=no_action&hand=Q4o&wp_ratio=1.3
→ { "base_push": 0.499, "adjusted_push": 0.589 }
```
