# 선별·평가 재현 계약

**상태:** 실행 전 계약이다. 스케줄러와 replay fixture는 아직 구현하지 않았고 모의 검증도 실행하지 않았다. 이 계약을 충족하지 않은 run은 선별이나 압축 비교의 증거로 채택하지 않는다.

## 증거 단위

`run`은 한 inventory, 실행 소스, 원장, randomization manifest를 공유하는 묶음이다. `trial`은 한 task·반복·조건의 평가 단위다. `attempt`는 trial 안의 실제 실행 또는 retry이며, provider 요청은 attempt 안에서 고유 request ID를 가진다.

| 단위 | 필수 식별자 | 중복 방지 규칙 |
| --- | --- | --- |
| run | run ID, source commit, ledger hash, inventory hash, randomization manifest hash | 같은 manifest hash의 재수집은 새 run으로 세지 않음 |
| trial | run ID, task ID, repetition, condition으로 만든 고유 trial ID | 완료 trial은 resume 뒤 다시 분모에 넣지 않음 |
| attempt | trial ID와 증가하는 attempt number | 같은 attempt 레코드의 재업로드는 한 번만 수집 |
| provider request | provider request ID와 로컬 request hash | 같은 응답 레코드를 비용에 두 번 넣지 않음 |

실제 retry가 새 provider 요청을 만들면 새 attempt 또는 request ID로 기록하고 실제 사용량·비용에 한 번 포함한다. retry는 품질 분모의 새 trial이 아니다. F1-R1을 유발한 실패 attempt에는 provider 요청이 없어야 한다.

trial ID는 `run ID`, 정규화 task ID, repetition과 condition을 길이 구분자로 연결한 값의 SHA-256으로 만든다. attempt ID는 trial ID와 1부터 증가하는 attempt number로 만든다. 문자열을 단순 이어 붙이지 않으며, 같은 randomization manifest에서 같은 trial tuple은 언제 다시 계산해도 같은 ID가 나와야 한다.

## F1-R1 준비 retry 계약

F1-R1은 첫 provider dispatch 전에 발생한 `image_error` 또는 `setup_error`에만 적용한다. 첫 attempt와 동일한 준비 작업을 동일한 immutable artifact와 hash로 정확히 1회 다시 시도한다. artifact에는 task tree, instruction, image digest, verifier source·dependency, agent·runner·adapter commit과 요청 설정이 포함된다.

- retry는 같은 trial ID와 새 attempt ID를 사용한다.
- 실패한 container와 workspace는 폐기하고 fresh container·fresh workspace를 만든다.
- 첫 attempt의 filesystem layer, process, service, cache 또는 임시 파일을 retry에 연결하지 않는다.
- artifact나 hash가 달라지면 retry하지 않고 run을 멈춰 새 revision 승인을 요청한다.
- 두 번째 attempt가 유효하면 품질 분모에는 trial 결과를 한 번만 넣고 두 attempt의 시간·비용은 모두 원장에 넣는다.
- 두 번째 준비 attempt가 실패하면 추가 retry 없이 해당 과제를 부적격으로 둔다.
- `wrong_answer`·`wrong_format`을 포함한 품질 실패와 provider dispatch 뒤 오류에는 F1-R1을 적용하지 않는다.

정확히 1회라는 한도는 통계적으로 도출한 값이 아니라 일시적 준비 장애 한 번을 허용하기 위한 임의의 운영 규칙이다. retry attempt는 원래 attempt와 `artifact_manifest_hash`가 같고 `container_instance_id`와 `workspace_instance_id`가 달라야 한다. 이 불변식을 model-free contract test로 확인하기 전에는 선별을 시작하지 않는다.

## pause·resume·retry 상태

| 상태 | 들어가는 조건 | 분모·비용 규칙 |
| --- | --- | --- |
| `planned` | manifest에 있고 아직 시작하지 않음 | 품질 결과 없음·비용 0 |
| `running` | attempt를 만들고 실행 자원을 할당함 | 발생한 provider 요청은 비용 원장에 기록 |
| `paused` | 새 attempt를 시작하지 않고 현재 상태를 고정함 | 완료 trial을 되돌리지 않음 |
| `retried` | F1-R1 허용 범위의 준비 실패 뒤 같은 trial ID로 두 번째 attempt를 시작함 | 품질 분모는 하나·두 attempt의 실제 시간·비용을 각각 한 번 포함 |
| `completed` | verifier 결과와 필수 증거가 모두 확정됨 | 품질 분모에 한 번 포함 |
| `failed` | 재시도 한도 또는 증거 gate를 통과하지 못함 | 성공 trial로 바꾸지 않고 실패 유형과 발생 비용 기록 |
| `cancelled_by_futility` | 기준 B에서 세 번째 유효 품질 실패가 확정된 뒤 아직 시작하지 않은 계획 trial | 품질 분모와 비용은 0. 계획 최대 반복과 취소 사유는 유지 |
| `superseded` | 실행 전에 승인된 새 manifest가 기존 계획을 대체함 | 주분석 분모에서 제외하되 이미 든 비용은 지우지 않음 |

허용 전이는 manifest revision에 고정한다. `completed`에서 `running`으로 돌아갈 수 없고, resume는 `planned` 또는 `paused`만 시작한다. retry는 새 trial을 만들지 않으며 attempt number 2를 넘길 수 없다. `cancelled_by_futility`는 다시 시작하지 않으며, 조기 종료 전에 시작한 trial은 완료·증거·비용을 보존한다. 수집기는 trial ID, attempt ID와 provider request ID에 unique constraint를 두고 같은 Blob을 다시 읽어도 합계가 늘지 않아야 한다.

## 필수 재현 묶음

### 입력과 요청

- 정규화 전 입력 hash와 정규화 입력
- 정규화 규칙 revision과 정규화 입력 SHA-256
- 전체 message role·순서·content hash
- 모델 이름과 제공자 보고 revision
- temperature, reasoning effort, completion 한도와 전송한 전체 요청 설정
- provider request ID, 응답 ID, HTTP 상태와 retry 연결

정규화는 줄바꿈을 LF로 바꾸고, JSON 객체 키를 정렬하며, 의미 있는 문자열 공백과 배열 순서는 바꾸지 않는다. 원문과 정규화 입력을 모두 비공개 묶음에 남기고 각각 hash를 기록한다.

### 실행 소스와 환경

- agent, runner와 adapter의 전체 Git commit SHA
- task revision, task tree SHA-256과 instruction hash
- container image reference와 content digest
- Harbor, Terminus, Python과 주요 runtime 버전
- VM kernel, vCPU 수, 병렬도, 실행 시점 TPM·RPM
- compressor 이름·버전·profile·target·artifact hash

`main`의 최신 상태가 아니라 trial에 기록한 source commit과 image digest가 원본이다. 실행 중 checkout, 원장 또는 verifier를 바꾸지 않는다.

### 행동과 결과

- 전체 tool trace와 assistant 출력
- 각 provider 요청·응답의 원문과 usage
- stdout, stderr, exit code, 시작·종료·경과 시간
- turn 수, 논리 호출 수, 실제 HTTP 호출 수와 같은 명령 재실행
- 압축 전후 hash, 보호 구간 hash와 압축 시간 세부 항목
- 최종 workspace 재생 묶음과 파일 manifest

공개 문서에는 원문 trace나 assistant 출력을 싣지 않는다. 집계에 사용한 private 원본은 삭제하지 않는다.

### verifier

- verifier source tree와 SHA-256
- 원본 verifier 파일 SHA-256, 승인된 revision ID와 유효 verifier 파일 SHA-256
- 실행 명령, 환경 변수 이름과 dependency lock/hash
- stdout, stderr, exit code와 구조화 test 결과
- verifier가 실제로 읽은 workspace manifest
- 승인된 verifier revision과 변경 사유

verifier 결함을 발견하면 실행 중 즉시 고치지 않는다. 영향 범위를 보고하고 새 revision을 승인받은 뒤 새 run으로 시작한다. 서로 다른 verifier revision의 pass-rate를 한 분모에 합치지 않는다.

## randomization manifest

manifest에는 seed, 생성 알고리즘 revision, inventory hash, task·유형·반복·조건, block ID, 계획 순서, trial ID와 F1-R1 revision을 넣는다. 평가 block은 task×반복이며 네 조건을 한 번씩 포함한다. 선별 manifest에는 과제당 최대 20개 trial과 조기 종료 전이 규칙을 모두 넣고, 실제로 시작하지 않은 trial도 `cancelled_by_futility` 상태로 남긴다. 각 attempt에는 artifact manifest hash, container instance ID, workspace instance ID와 provider dispatch 시각 또는 미발생 상태를 기록한다.

manifest는 첫 trial 전에 비공개 Blob과 로컬에 함께 고정한다. pause·resume·retry는 같은 manifest를 사용한다. 계획에 없던 trial을 실행하면 별도 protocol deviation으로 기록하고 주분석 분모에 자동 편입하지 않는다.

## workspace replay gate

각 trial은 verifier가 읽은 최종 workspace와 task container의 verifier-visible 상태를 보존한다. archive manifest에는 상대 경로, 파일 종류, mode, uid·gid, symlink 대상, 크기와 SHA-256을 넣는다. 과제가 workspace 밖의 시스템 설정이나 상태 디렉터리를 바꾸면 고정 base image에 적용할 writable-layer diff도 묶음에 넣는다. 원격 공개 문서에는 비공개 절대 경로나 원문을 싣지 않는다.

socket, process, service, container와 network 상태처럼 파일 archive만으로 복원되지 않는 상태는 상태 캡처와 재시작 절차를 따로 둔다. verifier가 그 상태를 읽는데 재생할 방법이 없으면 fixture 통과로 간주하지 않는다.

모의 검증은 다음이 모두 같을 때만 통과한다.

```
workspace manifest hash
verifier source·명령·의존성 hash
구조화 test별 pass/fail
verifier exit code와 최종 reward
```

같은 fixture의 반복 판정이 달라지면 판정기 비결정성으로 분류한다. workspace가 달라 재생할 수 없으면 모델 변동과 판정기 변동을 가를 수 없으므로 해당 trial은 원인 진단용 재현 증거가 불완전하다.

기존 목적 선정 5과제×20회 기준선은 최종 workspace와 container rootfs를 보존하지 않아 이 replay gate를 충족하지 않는다. 그 측정은 기존 범위에서 유지하되 새 선별의 적격 판정 자료로 재사용하지 않는다.

## Blob 보존과 종료 gate

trial 증거는 먼저 실행 VM의 local spool에 원자적으로 확정한다. payload를 올린 뒤 manifest를 마지막에 올린다. Blob 쓰기 실패는 완료된 로컬 증거를 지우지 않으며 background retry 대상으로 남긴다.

run 종료에는 다음 순서가 필요하다.

1. Blob 객체별 크기와 SHA-256을 원격 manifest와 대조한다.
2. 별도 수집 호스트가 manifest와 payload를 내려받아 같은 hash를 확인한다.
3. 누락 trial, 중복 trial·attempt·request ID와 비용 합계를 검사한다.
4. 승인된 표본의 replay fixture가 같은 판정을 내는지 확인한다.
5. 그 뒤에만 VM spool 정리와 deallocate를 허용한다.

Blob의 ETag만으로 내용 hash 확인을 대신하지 않는다. 원격 hash 확인 전에는 로컬 증거를 삭제하지 않는다. 업로드가 끝나지 않으면 run은 `retrieval_pending` 또는 `incomplete`이며 성공으로 바꾸지 않는다.

## 공개와 비공개 경계

| 비공개 Blob 원본 | 공개 문서에 허용 |
| --- | --- |
| 계정·테넌트·구독·리소스 식별자 | 공개 benchmark·task·도구·모델 이름과 공개 revision |
| endpoint, 비공개 host와 내부 절대 경로 | 상대 문서 링크와 비식별 실행 환경 |
| provider request·response ID 원문 | request 수, 상태 분포와 hash 대조 결과 |
| 전체 prompt, tool trace, assistant 출력 | 집계 token·호출·시간·실패 유형 |
| 최종 workspace 원문과 replay archive | workspace hash와 replay 판정 일치 여부 |

환경·도구·버전·날짜·표본·분모·모델·병렬도는 재현 조건이므로 공개 집계에서 지우지 않는다. 식별자와 비공개 위치를 재현 조건과 섞지 않는다.

## 구현 전 차단 조건

- 현재 runner의 목적 선정 5과제 고정 목록을 전체 inventory 입력으로 바꾸는 구현이 없다.
- task×반복 block randomization과 idempotent resume 집계가 없다.
- 최종 workspace replay archive와 같은 판정 확인 경로가 없다.
- 새 세 문서는 설계이며 이 항목들이 구현됐다는 증거가 아니다.

따라서 [선별 규약](screening-protocol.md)과 [평가 규약](evaluation-protocol.md)의 승인만으로 실행을 시작하지 않는다. 구현, model-free 검사와 별도 실행 승인이 필요하다.
