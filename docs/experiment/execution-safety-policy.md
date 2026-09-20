# 다음 유료 실행 종료·비용 안전 정책

**적용 범위:** 이 문서는 원장 schema version 4로 시작하는 앞으로의 provider 유료
실행에 적용한다. 과거 원장, 측정값, 해시와 결과 JSON은 바꾸지 않는다. 공개 원장은
일부 승인값이 비어 있어 그대로는 실행할 수 없다.

## 30초 요약

- 한 과제의 한 실제 시도인 `attempt`마다 provider HTTP 시도 수, API 계산 비용,
  경과 시간, 요청 크기와 출력 token에 상한을 둔다.
- 전체 실행에도 API 계산 비용 상한과 UTC 종료 시각을 둔다. 두 비용 상한과 종료
  시각 중 하나라도 비어 있거나 승인되지 않으면 provider 호출 전에 멈춘다.
- 상한에 닿은 결과는 오답이 아니다. 품질을 아직 모르는 **기술 미완료**로 기록하고,
  비용 때문에 멈췄으면 `budget_stopped`, 그 밖의 관찰 경계에서 멈췄으면
  `censored`로 구분한다.
- 자연 종료까지 기다리는 관찰은 일반 비교에서 허용하지 않는다. 별도 파일럿의 사전
  비용 승인, 최대 노출액과 수동 종료 조건을 먼저 고정해야 하며, 현재 실행기에는 그
  파일럿 진입점이 없다.

## 무엇을 얼마로 막나

`trial`은 한 과제·반복·조건의 품질 단위이고, `attempt`는 그 안에서 실제로 시작한
시도다. 준비 재시도가 있으면 `attempt` 비용은 각각 남지만 품질 결과는 `trial`에 한
번만 들어간다.

| 경계 | schema version 4 정책 | 적용 시점 | 닿았을 때 |
|---|---:|---|---|
| attempt당 provider HTTP 시도 | 60회 | 61번째 전송 예약 전 | `budget_stopped` |
| attempt당 API 계산 비용 | 실행 전 승인한 양수 | 매 전송 예약 전·응답 정산 뒤 | `budget_stopped` |
| 전체 실행 API 계산 비용 | 실행 전 승인한 양수, attempt 상한 이상 | 매 전송 예약 전·응답 정산 뒤 | `budget_stopped` |
| attempt 경과 시간 | 2,400초 | 실행 process와 요청 대기 중 | `censored` |
| 전체 실행 종료 시각 | 실행 전 승인한 미래 UTC 시각 | 요청·대기·process 감시 중 | `censored` |
| 요청 크기 | 8,000,000 UTF-8 wire bytes | 변환 전 수신과 전송 직전 | `censored` |
| 응답 출력 | 요청 `max_completion_tokens=2,048` | 전송 전 고정, 사용량 수신 뒤 대조 | `censored` |
| provider HTTP 대기 | 300초 | 외부 HTTP 시도마다 | `censored` 또는 transport 오류 |
| 일시적 HTTP 시도 | 합계 최대 3회 | HTTP 429 처리 | 소진 뒤 기술 오류 |
| 한 번의 재시도 대기 | 최대 120초 | `Retry-After` 적용 전 | `censored` |
| 진행 없는 반복 | 최근 논리 요청 8개에서 서로 다른 진행 신호 3개 미만 | 다음 외부 전송 전 | `censored` |

provider HTTP 시도에는 같은 논리 요청의 429 재시도도 각각 포함한다. 진행 신호는
가장 최근 assistant 명령 계획과 그 뒤 user 관찰을 원문 대신 SHA-256으로 만든 값이다.
신호를 만들 수 없는 요청도 창에서 빠뜨리지 않고 같은 “신호 없음” 값으로 센다.

API 계산 비용은 provider 사용량에 원장의 고정 가격표를 곱한 값이며 실제 청구서가
아니다. 전송 전에는 로컬에서 센 비캐시 입력 token, protocol 여유 4,096 token과 출력
상한을 합쳐 비용을 예약한다. 이 예약은 provider의 청구 보장이 아니므로 응답 뒤 실제
사용량과 다시 대조한다. 확인된 비용, 사용량을 받지 못한 미확정 노출액, 전송 중인
예약액을 모두 합쳐 다음 요청 허용 여부를 판단한다. 미확정 값을 0으로 바꾸지 않는다.

## 실행 전 반드시 채울 값

공개 `ledgers/native.template.toml`과 `ledgers/screening.template.toml`은 고정 경계를
보여 주는 템플릿이다. 다음 값은 공개 기본값으로 대신 정하지 않는다.

1. `max_api_cost_usd_per_attempt`: 과제의 한 실제 시도에 허용할 API 계산 비용
2. `max_api_cost_usd_per_run`: 전체 새 실행에 허용할 API 계산 비용
3. `run_deadline_utc`: 미래의 명시적 UTC 종료 시각
4. `cost_limits_approved = true`와 실제 승인 근거
5. 실행 승인, 가격표 출처·확인 시각, deployment 공유 조정 근거

두 비용 상한은 모두 양수여야 하고 전체 실행 상한은 attempt 상한보다 작을 수 없다.
세 값은 일부만 채울 수 없다. 종료 시각이 이미 지났거나 가격표가 비어 있어도 실행을
시작하지 않는다. 일반 비교에서는 나머지 고정 경계를 늘리거나 끌 수 없다. 변경이
필요하면 새 정책 revision, 새 source commit과 새 원장으로 검토한다.

## 상한에 닿은 결과를 읽는 법

상한 종료는 `pass`, `wrong_answer`, `wrong_format`과 같은 품질 판정이 아니다.

| 기록 | 값 |
|---|---|
| 기술 상태 | `technical_incomplete` |
| 품질 상태 | `unknown` |
| 종료 성격 | `budget_stopped` 또는 `censored` |
| 검열 표기 | `right_censored` |
| 품질 분모 | 제외 |
| 자동 재전송 | 없음 |

`budget_stopped`는 호출 수나 계산 비용 예산에 닿았다는 뜻이다. `censored`는 시간,
요청 크기, 출력 token, 재시도 대기 또는 진행 신호 경계에서 관찰을 끝냈다는 뜻이다.
둘 다 내장 채점 오답으로 바꾸지 않는다. verifier가 실행되기 전에 끝났다면 품질은
계속 미확정이다.

## 어떤 증거를 남기나

각 종료 기록에는 다음을 함께 보존한다.

- 종료 이유, 범위가 attempt인지 전체 실행인지, 실제 적용 상한과 관측값
- 마지막 논리 요청·HTTP 시도 위치, 요청 SHA-256과 byte 수
- 마지막 응답의 HTTP 상태·SHA-256과 usage 확인 상태
- 확인된 API 계산 비용, 미확정 노출액과 아직 전송 중이던 예약액
- source commit, 원장과 실행 manifest SHA-256, 과제·컨테이너·workspace 식별 계보
- workspace 보존·상태 재생 manifest 상태와 verifier 실행 여부

원문 요청·응답, endpoint, credential, tenant 값과 개인 경로는 공개 결과에 넣지 않는다.
상태 재생과 원격 hash 확인이 끝나지 않은 기술 종료는 완료된 증거로 승격하지 않는다.
같은 실행을 재개할 때 사용량 없는 요청의 최대 노출액조차 계산할 수 없으면 새 유료
요청을 보내지 않는다.

## 자연 종료 관찰은 별도 파일럿이다

일반 비교 원장의 `natural_termination_observation`은 항상
`separate_pilot_only`다. 일반 비교에서 위 상한을 해제해 자연 종료를 기다리는 설정은
허용하지 않는다.

별도 파일럿을 만들려면 최소한 사전 승인한 계산 비용, 최대 노출액, 수동 종료 조건,
운영 책임자와 증거 보존 범위를 독립 원장과 schema에 고정해야 한다. 현재 저장소에는
그 파일럿 실행 계약과 진입점이 없으므로 자연 종료 관찰은 실행할 수 없다. 이 빈자리를
일반 비교의 큰 숫자나 빈 상한으로 대신하지 않는다.

## 과거 기록과 남은 한계

- schema version 1~3 원장과 기존 결과는 당시 정책의 역사 기록으로 계속 검증한다.
  새 provider 실행에는 schema version 4만 쓴다.
- 과거 결과를 읽기 전용으로 연결할 때 60회 호출 또는 2,048 출력 token 경계의 영향을
  받은 결과는 새 실행의 같은 결과로 재사용하지 않는다.
- 비용 예약은 provider의 실제 청구 상한을 보증하지 않는다. provider가 usage를
  돌려주지 않거나 토큰화가 다르면 미확정 노출액이 남으며 청구서 대사가 필요하다.
- 진행 신호는 명령 계획과 관찰 문자열의 SHA-256 다양성을 세는 운영 규칙이다. 문자열이
  달라졌다는 사실이 의미 있는 작업 진전을 증명하지 않으므로 품질이나 완료 근거로 쓰지
  않는다.
- attempt의 2,400초 상한은 준비, agent와 verifier를 포함한 process 경계다. 단계별
  원인이나 순수 모델 시간의 상한으로 해석하지 않는다.
- Harbor 내부 단계 타이머는 증거 수집을 중간에 서로 다르게 자르지 않도록 비활성화한
  채 유지한다. 대신 바깥 supervisor와 보호된 loopback transport가 위 attempt·요청
  상한을 적용한다.

정확한 기계 계약은
[`execution-safety-policy.schema.json`](../../schemas/execution-safety-policy.schema.json),
원장 검사는 [`execution_safety.py`](../../src/execution_safety.py), 실행 경계는
[`live_transport.py`](../../src/live_transport.py)에 있다.
