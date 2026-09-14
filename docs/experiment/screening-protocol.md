# Terminal-Bench 2.1 평가 과제 선별 규약

**상태:** 실행 전 설계안이다. 선별 실행은 0회다. 평가 적격 기준 B의 최대 20회와 총 18/20은 선택됐지만, B-2의 사용 방식, F1 실패 규칙과 최종 과제 수는 승인되지 않았다. nginx verifier v2는 2026-09-14 UTC에 기존 diff·source SHA·effective SHA·fixture 범위로만 조건부 승인됐다. 여기서 `평가 적격`은 정해진 평가에 넣을 조건을 충족했다는 뜻이며, 작은 반복 표본으로 과제나 모델의 진짜 안정성을 증명했다는 뜻이 아니다.

기존 [1차 실험 규약](protocol.md)은 목적 선정 5과제 기록으로 그대로 둔다. 이 문서는 전체 모집단에서 새 평가 과제를 고르는 후속 설계다.

## 선별 모집단

| 항목 | 고정값 | 성격 |
| --- | --- | --- |
| 벤치마크 | Terminal-Bench 2.1 | 설계 판단 |
| revision | `7131e4375048a0e408a8fb404b5f499d726b695b` | 고정 조건 |
| 모집단 | 공식 영어 과제 89/89개 | 고정 분모 |
| 선별 조건 | 추가 압축 없는 `none` | 설계 판단 |
| 제외 범위 | DeepSWE, 보호 우회 감사 | 설계 판단 |

과제 유형은 [벤치마크 EDA](../eda/README.md#table-5)의 주된 산출물 기준 분류를 고정해 사용한다. 이는 저자 메타데이터가 아니라 분류 판단이다.

| 주 유형 | 모집단 과제 수 | 분모 | 성격 |
| --- | ---: | ---: | --- |
| 기능 요청 | 31 | 89과제 | 분류 판단·집계 |
| 버그 수정·디버깅 | 5 | 89과제 | 분류 판단·집계 |
| 코드 리뷰 | 0 | 89과제 | 분류 판단·집계 |
| 리팩터링 | 6 | 89과제 | 분류 판단·집계 |
| 테스트 작성 | 0 | 89과제 | 분류 판단·집계 |
| 환경 설정·빌드 | 16 | 89과제 | 분류 판단·집계 |
| 그 밖에 | 31 | 89과제 | 분류 판단·집계 |

코드 리뷰와 테스트 작성은 모집단에 단독 과제가 없다. 다른 유형을 코드 리뷰로 바꾸거나 DeepSWE 과제를 넣어 빈 유형을 채우지 않는다.

## 결과를 보기 전 inventory 고정

89과제의 실행 가능성을 확인하기 전에 다음 필드를 과제 ID 순으로 정렬한 inventory를 만든다.

```
benchmark revision
task ID
task tree SHA-256
instruction SHA-256
task.toml SHA-256
container image reference와 image SHA
verifier source tree SHA-256
verifier command와 dependency lock SHA-256
주 유형과 분류표 revision
```

inventory hash는 위 레코드를 키 이름 순서가 고정된 공백 없는 UTF-8 JSON으로 직렬화한 뒤 계산한 SHA-256이다. 배열은 task ID 오름차순으로 고정한다. 구현이 생기기 전에는 임의의 hash를 문서에 채우지 않는다.

`task tree SHA-256`은 `.git`과 실행 중 생성된 파일을 제외한 상대 경로, 파일 종류, mode, 크기와 파일 SHA-256을 상대 경로 오름차순으로 기록한 manifest의 SHA-256이다. symlink는 링크 대상 문자열을 hash 입력으로 삼는다. verifier 의존성 lock이 없는 과제는 `tests/test.sh`의 정확한 명령과 직접 pin을 별도 manifest로 남기고, 전이 의존성을 고정하지 못했다는 사실을 실행 가능성 판정에 기록한다.

실행 불가능한 과제가 있으면 모델 응답을 보기 전에 과제 ID, 제외 사유, 확인 시각, 확인 코드 revision을 inventory에 기록한다. 허용하는 사유는 고정 image를 가져오거나 시작할 수 없음, 필수 task 파일 누락, 고정 verifier 의존성을 준비할 수 없음, verifier를 원형 그대로 호출할 수 없음이다. 낮은 통과율, 긴 실행 시간, 불리한 결과는 사전 제외 사유가 아니다.

제외 전 89과제, 제외 과제, 실행 가능한 과제를 각각 분모로 남긴다. 제외가 생기면 제외 전 inventory hash와 실행 대상 inventory hash를 둘 다 보존한다.

## 선별 실행의 고정 조건

| 항목 | 값 | 성격 |
| --- | --- | --- |
| 모델 | `gpt-5.4`, 제공자 보고 revision을 trial마다 기록 | 고정 조건·실행 시 확인 |
| 생성 설정 | temperature `0`, reasoning effort `none`, 최대 completion 2,048 token | 고정 설정·결정론 보장 아님 |
| 실행기 | Harbor `0.22.0`, instrumented Terminus 2 `2.0.0` | 고정 조건 |
| 동시성 | native trial 8개 | 비교 통제 |
| 채점 | 승인된 verifier revision | 승인 전 조건 |
| 반복 | 과제당 최대 20회. 조기 부적격 규칙은 아래와 같음 | 일부 승인·세부 승인 필요 |
| 증거 | [재현 계약](reproducibility-contract.md)의 필수 묶음 | 실행 전 차단 조건 |

선별의 `none` 결과는 과제를 고르는 자료다. 평가는 시간대와 조건을 맞춘 `none`을 각 task×반복 블록 안에서 다시 실행한다. 선별 결과를 평가의 동시 대조군으로 재사용하지 않는다.

## 평가 적격 기준 B — 세부 승인 대기

| 항목 | 기준 B | 상태·성격 |
| --- | --- | --- |
| 최대 반복 | 과제당 20회 | 사용자 선택 |
| 총 통과 | 18/20 이상 | 사용자 선택. 9/10으로 환산하지 않음 |
| 전후반 | B-2인 차이 1 이하를 gate로 쓸지 진단 지표로만 쓸지 | 승인 필요 |
| 허용 실패 | 정상 종료한 verifier의 품질 실패만 허용 | 아래 객관화 제안 승인 필요 |
| 유형별 선정 | 비어 있지 않은 5유형에서 각 3개 | 일정 계산 시나리오·미승인 |
| 최종 과제 수 | 미정 | task 군집과 과제 간 이질성을 반영한 표본 설계 뒤 승인. 15과제는 상한이 아님 |

18/20이면 전후반은 최악에도 10/10과 8/10이다. 따라서 “각 절반 8/10 이상”은 총 통과 조건과 중복되어 시간에 따른 쏠림을 따로 제한하지 못한다.

### B-2 영향과 시간 진단

B-2는 1–10회와 11–20회의 통과 횟수 차이를 1 이하로 요구하는 보수적 임의 후보다. 총 18/20 이상과 F1을 통과해도 B-2를 별도 gate로 쓰면 10/10·8/10은 제외된다.

| 후보 | `|1–10회 통과 - 11–20회 통과|` | 포함·제외 | 판단 |
| --- | ---: | --- | --- |
| H0 | 0 | 전반·후반 통과 횟수가 같아야 함. 19/20은 구조상 제외 | 임의값·지나치게 엄격 |
| B-2, 기존 H1 | 1 이하 | 10회·9회와 9회·9회는 허용하고 10회·8회는 제외 | 보수적 임의 후보·추천 보류 |
| H2 | 2 이하 | 10/8까지 허용 | 임의값·총 18/20과 사실상 중복 |
| D1 진단 지표 | gate에 사용하지 않음 | 전후반 차이를 기록하되 평가 적격 여부에는 사용하지 않음 | 실패 위치만으로 제외하지 않는 대안 |

정확히 18/20인 과제에서 두 실패의 위치가 20개 trial에 균등하게 배치된다고 가정하면, B-2가 제외하는 같은 절반 배치는 `2×C(10,2)÷C(20,2)=90/190=47.37%`다. 19/20과 20/20은 B-2 때문에 제외되지 않는다. 전체 탈락 비중은 정확히 18/20인 과제 수에 따라 달라지므로 선별 전에는 계산할 수 없다. 47.37%는 관측값이 아니라 실패 위치의 조합 계산이며 실제 시간 변화가 있었는지 보여주지 않는다.

| 사용 방식 | 평가 적격 gate | 편향 위험 | 조기 종료 제안 |
| --- | --- | --- | --- |
| B-2 gate | 총 18/20·F1·전후반 차이 1 이하 | 무작위로 두 실패가 같은 절반에 놓인 정확히 18/20 과제를 제외한다. 19/20·20/20과 실패가 나뉜 과제를 더 남겨 ceiling 쪽으로 치우칠 수 있다 | 유효한 품질 실패가 같은 절반에서 2회가 되거나 전체 3회가 되면 새 trial 예약 중단 |
| D1 진단 지표 | 총 18/20과 F1만 사용 | 실패 위치만으로 제외하지 않지만 선별 자료만으로 시간 변동을 막았다고 말할 수 없다 | 시간 진단으로 중단하지 않음. 유효한 품질 실패가 전체 3회가 되면 새 trial 예약 중단 |

B-2 gate는 시간대 쏠림을 보수적으로 거르지만 작은 실패 수에서 우연한 위치와 시간 변화를 구분하지 못한다. D1은 선별에서 시간 안정성을 증명하지 않고 다음 값을 과제별로 남긴다.

- 전반부·후반부 통과 횟수와 차이
- 실패 trial 번호와 최장 연속 실패 길이
- trial 순서의 pass/fail 열과 누적 통과율
- 모델 revision, verifier revision·effective SHA, 실행 소스와 비교 통제 설정

모델 revision, verifier revision·effective SHA, 실행 소스, 모델 요청 설정이나 병렬도가 실행 중 바뀌면 시간 진단값과 관계없이 hard stop한다. 변경 전후 trial을 한 선별 분모로 합치지 않는다.

평가는 각 task×반복 block에 contemporaneous `none`을 넣고 조건 순서를 block 안에서 무작위화한다. D1을 선택하면 기본 분석은 총 18/20과 F1만 통과한 전체 과제를 사용하고, B-2에 걸리는 과제를 제외한 분석과 평가 전반부·후반부 분석을 민감도 분석으로 함께 계산한다. 기본 분석의 도입 판단이 둘 중 하나에서 바뀌면 `time_sensitive_inconclusive`로 표시하고 과제나 문턱을 사후 변경하지 않는 안을 제안한다. 이 판정 규칙과 B-2·D1 중 어느 방식을 쓸지는 아직 승인되지 않았다.

### 실패 유형 규칙 제안 F1

`trial`은 실행 manifest에 미리 적은 task×반복 한 건이고, `attempt`는 그 trial을 실행하거나 재시도한 한 번의 시도다. 품질 분모에는 완전한 증거와 유효한 verifier 결과가 있는 trial을 최대 한 번 넣는다. 모든 attempt와 발생 비용은 품질 분모와 별도로 원장에 남긴다.

`품질 실패`는 Harbor process와 verifier가 timeout·예외 없이 끝났고, binary reward와 구조화 test 결과가 일치하며, 필수 증거가 완전한 trial에서 reward가 0인 경우다. 그중 `wrong_answer`와 `wrong_format`만 기준 B가 허용하는 최대 2회의 실패로 센다. category는 실행 소스에 고정한 분류기 revision이 pytest trace의 활성 예외 줄과 test ID로 계산하며 사람이 결과를 보고 바꾸지 않는다. JSON·CSV·YAML parse 오류, 명시한 출력 모양 assertion과 필수 산출물 누락만 `wrong_format`이고, 그 규칙에 걸리지 않은 assertion 실패는 `wrong_answer`다.

| 결과 분류 | 객관적 기준 | 품질 분모 | 재시도 제안 | 과제 처리 제안 |
| --- | --- | --- | --- | --- |
| `pass` | 정상 종료, reward 1, 구조화 test 전부 통과, 필수 증거 일치 | 통과 1 trial | 없음 | 계속 선별 |
| `wrong_answer`·`wrong_format` | 정상 종료, reward 0, 구조화 test 실패와 reward 일치, 필수 증거 완전 | 품질 실패 1 trial | 없음 | 최대 2회 허용, 3회째 부적격 |
| `image_error` | 고정 image를 digest로 가져오거나 시작하지 못함 | 넣지 않음 | 아래 R0·R1 후보 | 복구 실패 시 부적격 |
| `setup_error` | 첫 provider dispatch 전에 task 환경이나 agent 준비 실패 | 넣지 않음 | 아래 R0·R1 후보 | 복구 실패 시 부적격 |
| `provider_error` | provider가 오류 응답을 반환하고 유효한 모델 결과가 없음 | 넣지 않음 | 기존 bounded transport retry만 허용, outer trial retry 없음 | retry 소진 시 부적격 |
| `network_error` | dispatch 수락 여부나 usage가 불명인 연결 실패 | 넣지 않음 | 중복 호출 위험 때문에 자동 retry 없음 | 부적격, 비용·불명 상태 보존 |
| `timeout` | agent·task·verifier의 승인된 deadline 초과 | 넣지 않음 | 자동 retry 없음 | 부적격. 느린 과제를 빼는 편향 기록 |
| `verifier_crash` | 정상적인 test 실패가 아니라 verifier 예외·중단 또는 완전한 구조화 결과 부재 | 넣지 않음 | 모델 재실행 없음. 같은 workspace의 verifier-only replay는 진단에만 사용 | 부적격 |
| `evidence_missing` | 필수 trace·assistant 출력·workspace·stdout·stderr·exit code·usage·hash 중 하나가 없거나 서로 불일치 | 넣지 않음 | 자동 retry 없음 | 부적격, 증거 gate hard stop 후보 |
| `replay_mismatch` | 같은 보존 workspace와 같은 verifier source·명령·의존성으로 판정이 재현되지 않음 | 넣지 않음 | 자동 retry 없음 | 부적격, verifier 범위 조사 전 hard stop 후보 |

image·setup 실패의 retry는 두 후보 중 승인이 필요하다.

- **F1-R0:** 기술 실패를 재시도하지 않는다. 재시도 선택 편향은 없지만 일시적인 준비 장애 하나로 과제를 제외한다.
- **F1-R1:** 첫 provider dispatch 전에 난 image·setup 실패만 같은 trial ID와 고정 artifact로 1회 재시도한다. 새 attempt ID를 쓰고 첫 attempt도 비용·시간 원장에 남긴다. 1회는 통계적으로 정한 값이 아닌 임의의 운영 후보다. 두 번째 attempt가 유효하면 그 trial 결과만 품질 분모에 한 번 넣고, 다시 실패하면 과제를 부적격으로 둔다.

provider의 명시적 retry 가능 응답은 현재 transport 계약의 bounded retry 안에서만 처리한다. dispatch 수락 여부가 불명인 network 오류, timeout, verifier crash, 증거 누락과 replay 불일치는 outer trial retry로 덮지 않는다.

- 실패가 0회면 일관성 조건을 충족한다.
- 실패가 1회면 비교할 두 번째 실패가 없으므로 “일관성 미판정”으로 표시하되 적격을 막지 않는다.
- 실패가 2회면 두 trial의 전체 실패 category 집합과 정렬한 verifier test ID 집합이 모두 같아야 한다. 상위 category 하나만 같은 경우는 일관된 실패로 보지 않는다.
- 허용한 F1-R1 복구를 제외한 기술 오류가 한 번이라도 있으면 해당 과제를 평가 부적격으로 둔다. 이를 품질 실패나 통과로 바꾸거나 분모에서 조용히 빼지 않는다.

F1은 실행과 판정이 불완전한 과제를 제외해 비교 가능성을 높이지만, 느리거나 환경 의존적인 과제를 체계적으로 빼 압축 피해를 작게 보이게 할 수 있다. 두 품질 실패의 category와 test ID가 같아야 한다는 조건도 서로 다른 방식으로 실패하는 과제를 제외해 반복되는 단일 실패 형태 쪽으로 표본을 치우치게 할 수 있다. 현재 분류기는 일부 경우를 `timeout`·`tool_error`·`other`로만 기록하므로 위 세부 category와 attempt 상태를 저장하는 구현·모의 검증이 필요하다. F1-R0·F1-R1 중 하나와 이 편향을 함께 승인하기 전에는 선별하지 않는다.

### 세 번째 실패에서 조기 종료하는 제안

세 번째 **유효한 품질 실패**가 확정되면 18/20이 불가능하므로 그 과제의 새 trial을 예약하지 않는다. B-2를 gate로 승인하면 같은 절반에서 두 번째 유효한 품질 실패가 확정된 때도 B-2 통과가 불가능하므로 새 trial을 예약하지 않는다. D1에서는 실패 위치만으로 중단하지 않는다. 18/20의 증거량을 적은 반복의 같은 통과율로 대체하지 않으며, 조기 종료 과제는 평가 부적격으로만 판정한다.

- 같은 과제는 한 번에 한 trial만 실행하도록 계획한다. 전체 동시성 8은 서로 다른 과제로 채워 세 번째 실패 뒤의 초과 실행을 만들지 않는 것이 원칙이다.
- 조기 종료 신호 전에 이미 시작한 같은 과제 trial이 있으면 취소하지 않고 끝까지 보존한다. 유효한 품질 결과면 실제 관측 분모에 포함하지만, 이미 확정된 부적격 판정을 되돌리지는 않는다.
- 시작하지 않은 계획 trial은 `cancelled_by_futility`로 남기고 품질 분모와 비용에 넣지 않는다. 시작한 trial과 모든 retry의 실제 비용은 결과와 관계없이 비용 원장에 한 번 포함한다.
- 기술 오류로 유효한 품질 결과가 없는 attempt는 품질 분모에 넣지 않고 attempt·비용 원장에는 남긴다. F1을 적용하면 그 과제는 즉시 부적격이며 다른 과제로 바꾸지 않는다.
- 보고에는 `계획 최대 20회`, `실제 완료 trial`, `유효 품질 분모`, `통과`, `품질 실패`, `기술 오류`, `조기 종료 뒤 완료된 trial`을 따로 쓴다. `17/n`을 `17/20`이나 `9/10`으로 바꾸지 않는다.

이 조기 종료 규칙은 일정 계산에서 절감으로 가정하지 않는다. scheduler 구현과 상태 전이 검사는 아직 없으며, 구현·모의 검증·승인을 마치기 전에는 실행하지 않는다.

유형별 3개 일정 시나리오에서 후보가 3개보다 적으면 적격 과제를 모두 표시하고 부족 수를 그대로 남긴다. 다른 유형으로 보충하지 않는다. 코드 리뷰와 테스트 작성처럼 모집단이 0개인 유형에도 다른 과제를 대신 넣지 않는다. 최종 유형별 선정 수와 전체 과제 수는 task 군집과 과제 간 이질성을 반영한 표본 설계와 함께 다시 승인받는다. 이 gate에서 평가를 중단할 수 있다.

승인된 유형별 선정 수보다 적격 과제가 많으면 통과율이나 비용이 좋은 순서로 고르지 않는다. 실행 전에 고정한 selection seed와 정규화 task ID의 hash 순서로 필요한 수만 뽑는다. 아직 선정 수가 승인되지 않았으므로 15과제에서 자르지 않는다.

전체 89과제의 반복 실행 자료가 아직 없으므로 기준 B를 통과할 과제 수는 계산할 수 없다. 15과제는 비어 있지 않은 5유형에서 각 3개를 뽑는 일정 계산 시나리오일 뿐, 예상 적격 과제 수나 최종 표본 수의 상한이 아니다. 18/20 선별은 쉬운 과제와 ceiling에 치우쳐 압축 피해를 작게 볼 수 있으며, 선별된 과제에만 결과를 일반화한다.

## nginx verifier 정적 대조

**확인 결과:** `${http_user_agent}`는 잘못된 Nginx 구현이 아니라 `$http_user_agent`와 같은 변수를 가리키는 중괄호 문법이다. 현재 verifier가 동등한 문법을 거부한다.

- 과제 [instruction](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/nginx-request-logging/instruction.md)은 사용자 에이전트 변수를 로그에 넣고 큰따옴표로 감싸라고 요구한다. 중괄호 표기를 금지하지 않는다.
- Nginx `1.22.1`의 [`log_format` 변수 파서](https://github.com/nginx/nginx/blob/release-1.22.1/src/http/modules/ngx_http_log_module.c#L1609-L1687)는 `$` 다음의 `{`를 열고 `}`까지를 변수 이름으로 읽는다. `$http_user_agent`와 `${http_user_agent}`는 같은 `http_user_agent` 변수로 compile된다. **성격:** 공개 소스 정적 확인.
- 과제 [verifier](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/nginx-request-logging/tests/test_outputs.py#L106-L116)는 nginx.conf 문자열에 정확히 `$http_user_agent`가 들어 있는지만 검사한다. `${http_user_agent}`에는 그 부분 문자열이 없으므로 실패한다. **성격:** 공개 소스 정적 확인.
- 기존 `none` 20회 가운데 최종 명령 trace가 `${http_user_agent}`를 nginx.conf에 남긴 2회는 `test_nginx_config_settings`만 실패했다. 같은 2회에서 `nginx -t`와 동적 로그 형식 검사는 통과했다. **표본·분모:** 해당 구현 2회/전체 20회. **성격:** 비공개 원본에서 집계한 측정·정적 원인 대조.

로그 형식 test는 마지막 큰따옴표 문자열이 실제 요청의 user-agent 값과 같은지까지 비교하지 않는다. 따라서 이 발견은 verifier의 거짓 실패 경로를 확인하지만, 그 test가 모든 잘못된 로그 구현을 잡는다는 뜻은 아니다.

### revision과 fixture

수정본 `nginx-request-logging-verifier-v2`는 네 필수 Nginx 변수를 `$name`과 `${name}` 두 문법으로 인식한다. 그 밖의 test와 임계값은 바꾸지 않는다.

| 항목 | 값 | 성격 |
| --- | --- | --- |
| 원본 `tests/test_outputs.py` SHA-256 | `045cc716c14efde3b0dcff5fc7c85ec5d18bfc6ce66f8b40a418fa2a3a4acda0` | 고정 원본 |
| 수정본 `tests/test_outputs.py` SHA-256 | `20812107bc3bfc541728a2d10e3da0552e907d949e1347a03d33aa26954f8902` | 고정 revision |
| `$http_user_agent` fixture | 통과 | 모델 호출 없는 fixture 1건 |
| `${http_user_agent}` fixture | 통과 | 모델 호출 없는 fixture 1건 |
| 명백한 오답 `$http_referer` fixture | 실패 | 모델 호출 없는 fixture 1건 |
| 고정 원본을 포함한 test module | 6/6 통과 | 2026-09-14 UTC 정적 재검증 |

세 fixture 3/3은 정적 설정 문자열에서 수정한 변수 검사가 의도대로 작동한다는 확인이다. 고정한 Terminal-Bench 2.1 원본 파일의 SHA가 source SHA와 같고, 기존 diff를 적용한 결과가 effective SHA와 같음을 함께 재검증했다. Nginx container 전체를 다시 실행한 결과는 아니다. 조건부 승인은 이 기존 바이트와 세 fixture에만 적용하며, runner는 원본 SHA나 수정 뒤 SHA가 다르면 실행 전에 중단하고 원장·결과에 revision과 두 SHA를 기록한다.

### 기존 기준선에 미치는 영향

기존 `none` 20회의 기록된 nginx 결과 18/20은 그대로 보존한다. 실패한 8·9회는 `${http_user_agent}`를 사용했고, 두 trial 모두 `test_nginx_config_settings`만 실패했으며 `nginx -t`와 나머지 동적 검사는 통과했다. 수정본의 변수 검사에 대한 계산값은 nginx 20/20, 전체 65/100이다. 이는 보존 trace와 당시 verifier 결과에 근거한 **정적 반사실 계산**이며 실제 workspace replay가 아니다. 원본 verifier의 측정값 18/20과 전체 63/100을 수정하거나 새 실행으로 부르지 않는다.

이 정적 반사실 계산에서 회차별 통과 과제 수 범위는 3–4, 폭 1이 된다. 그러나 `log-summary-date-ranges`의 전후반 관측값 집합이 여전히 달라 기존 기준선의 `stop_inconclusive` 결론은 바뀌지 않는다. 새 verifier revision은 새 선별에만 쓰며, 승인 전에는 실행하지 않는다.

## 선별 시간 계산 — 잠정

시간의 입력은 기존 목적 선정 5과제×20회, 100 native trial의 추가 압축 없는 실행이다. trial 벽시계 P50은 76.145초, P90은 93.559초였다. 100 trial의 실제 관측 구간 1,405.368초를 `trial 시간 합계÷병렬도 8`로 나눈 1.4345를 준비·wave 공백 보정값으로 사용했다. **성격:** 과거 측정에서 만든 일정 계산이며, 전체 89과제의 측정이 아니다.

| 기준 | trial 수 | 계산 P50 | 계산 P90 | 조기 종료 반영 | 성격 |
| --- | ---: | ---: | ---: | --- | --- |
| B 최대, 89과제×20회 | 1,780 | 6.77시간 | 8.31시간 | 반영하지 않음 | 계산·기존 5과제 시간의 전체 모집단 투영 |

`ceil(trial 수÷8) × trial 분위수 × 1.4345`로 계산했다. native trial 시간에는 Harbor process 안의 agent 실행과 내장 verifier가 포함된다. 전체 89개 image의 최초 pull, 처음 보는 과제의 setup 꼬리, Blob 최종 검증·replay, 재시도, 승인 대기와 scheduler 구현 시간은 포함하지 않는다. 조기 종료의 절감도 가정하지 않았다.

P50·P90의 원자료가 전체 89과제가 아니라 목적 선정 5과제이므로 이 값은 미래 완료시간의 측정 분위수나 상한이 아니다. 전체 모집단의 실행 시간 범위를 확인하기 전까지 일정 적합 판단은 잠정으로만 쓴다.

## 선별 시작 전 차단 조건

- B-2 gate 또는 D1 진단 지표, 민감도 분석의 판정 불가 규칙을 사용자가 승인한다.
- F1-R0·F1-R1 중 하나와 실패 category·분모 규칙을 사용자가 승인한다.
- 유형별 선정 수, 최종 과제 수와 task 군집·과제 간 이질성을 반영할 표본 설계를 사용자가 승인한다.
- 조건부 승인된 `nginx-request-logging-verifier-v2`의 기존 revision과 두 SHA가 실행 preflight에서 다시 일치한다.
- 89과제 inventory와 제외 사유가 결과 전에 고정된다.
- 실행 manifest, block seed, 고유 trial ID와 [재현 계약](reproducibility-contract.md)이 구현돼 있다.
- Blob 원격 hash 확인 전 로컬 증거를 삭제하지 않는 종료 gate가 연결돼 있다.
