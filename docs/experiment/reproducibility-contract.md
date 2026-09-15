# 선별·평가 재현 계약

**상태:** 이 계약으로 선별을 세 번 시작했지만 기술 결함 때문에 유효한 품질 결과는 0건이다. 수정한 상태 보존 경로의 모델 호출 없는 검증은 끝났고, 새 source commit의 선별은 아직 시작하지 않았다. 이 계약의 필수 증거가 빠진 실행은 품질 분모에 넣지 않는다.

## 기록 단위

`run`은 한 과제 목록, 실행 source commit, 원장과 실행 manifest를 공유하는 묶음이다. `trial`은 한 과제·반복·조건의 논리적 평가 단위다. `attempt`는 `trial` 안에서 실제로 시작한 실행이며, provider 요청은 `attempt` 안에서 고유한 요청 위치와 provider request ID를 가진다.

계획 `trial` 수와 실제 `attempt` 수를 섞지 않는다. 준비 재시도는 `attempt`를 하나 늘리지만 품질 분모와 계획 `trial`을 늘리지 않는다. provider transport 내부 재시도도 별도 HTTP attempt로 기록하며 논리 요청 수와 구분한다.

## 실행 전에 고정하는 항목

- 실행 source commit 전체 SHA
- 원장 원문과 SHA-256
- 정규화한 과제 목록과 SHA-256
- 모델 이름·provider 보고 revision·요청 설정
- agent, runner, task와 컨테이너 이미지 SHA
- verifier source, 명령, 직접 의존성과 revision SHA
- 압축기 이름, 버전, 프로필, 적용 위치와 artifact SHA
- 조건 순서 seed, 생성 방법, 모든 `trial` ID와 계획 순서
- 가격표의 통화, 단위, 적용 시각과 원본 hash
- 종료 시각, 비용 상한, 병렬도와 배포 TPM·RPM

source commit은 실행 전에 커밋된 깨끗한 worktree와 같아야 한다. 실행 중 소스나 원장이 달라지면 중단한다.

## `trial`과 요청 증거

각 `trial`과 `attempt`에 다음을 남긴다.

- 과제 ID, 반복 번호, 조건과 계획·실제 시작 순서
- `trial` ID, `attempt` ID와 재시도 번호
- immutable artifact manifest hash
- 새 컨테이너와 새 workspace의 실행 식별자
- 시작·종료 시각, process ID, exit code와 timeout 상태
- provider request ID, HTTP attempt, 상태와 request·response SHA-256
- 전체 tool trace와 assistant 출력
- provider 입력·cache 입력·출력 token, 로컬 token과 비용 계산값
- 명령별 stdout·stderr·exit code·시간과 같은 명령 재실행 횟수
- 과제당 turn 수와 총 모델 호출 수
- verifier stdout·stderr·exit code, test별 결과와 native reward
- 최종 workspace와 verifier가 읽은 컨테이너 상태의 재생 묶음
- Blob payload와 manifest의 크기·SHA-256·업로드와 검증 읽기 상태

필수 값이 없으면 `null`이나 결측 상태로 남긴다. 누락값을 0이나 통과로 바꾸지 않는다.

## 준비 재시도

provider 호출 전에 이미지 또는 환경 준비가 실패한 경우에만 동일한 artifact로 정확히 한 번 다시 시도한다.

- 같은 `trial` ID 아래 새 `attempt` ID를 사용한다.
- 첫 실행과 같은 immutable artifact와 hash를 사용한다.
- 실패한 컨테이너와 workspace를 재사용하지 않는다.
- 품질 실패, provider 호출 뒤 오류, timeout, verifier 오류와 증거 누락은 다시 시도하지 않는다.
- 두 `attempt`의 시간, 비용과 오류는 모두 남긴다.
- 두 번째 `attempt`가 유효하면 품질 결과는 `trial` 분모에 한 번만 넣는다.

artifact나 설정을 바꾸는 복구는 재시도가 아니라 새 revision이다. 현재 실행을 중단하고 새 source commit과 manifest로 시작한다.

## 중단·재개와 중복 방지

상태 데이터베이스는 `(task, repetition, condition)`의 `trial`을 하나만 허용하고 `(trial, attempt number)`와 `(attempt, logical request, HTTP attempt)`를 고유하게 만든다.

중단 시 실행 중이던 `attempt`는 자동으로 다시 실행하지 않고 `paused`로 둔다. 보존 증거로 provider 호출 여부, 결과와 비용을 정적으로 확정한 뒤에만 상태를 해소한다. 같은 `trial`을 새 ID로 다시 예약해 분모나 비용에 중복 집계하지 않는다.

세 번째 품질 실패 뒤 시작하지 않은 계획은 `cancelled_by_futility`로 보존한다. 실제로 시작한 `attempt`는 결과와 무관하게 비용에 포함한다.

## 최종 workspace와 verifier 재실행

verifier 실행 직전 다음 상태를 보존한다. 상태 재생 묶음 revision 2부터 컨테이너 writable layer의 변경 경로는 NUL 문자로 경계를 구분한 한 개의 tar 파일에 넣고, 마운트는 대상 경로 순서로 고정한다.

- workspace와 마운트 파일의 상대 경로, 종류, mode, uid·gid, symlink 대상, 크기와 SHA-256
- 컨테이너 이미지 SHA, writable layer의 변경·삭제 경로와 내용 hash
- verifier가 읽는 서비스·process·container 상태와 로그
- 민감한 환경 변수 값과 호스트 경로를 원문 대신 SHA-256으로 바꾼 inspect 기록

보존한 상태를 같은 이미지와 verifier revision에 복원한 뒤 모델 호출 없이 verifier를 한 번 더 실행한다. 두 번째 실행은 첫 verifier 명령의 900초 제한이 끝난 뒤, 같은 컨테이너를 내리기 전에 수행한다. 복원 가능한 파일 상태 hash, verifier source·명령·의존성 hash, test별 pass/fail, exit code와 reward가 모두 같아야 재생 검사가 통과한다.

실행 중인 process의 메모리 상태는 파일 archive로 재구성하지 않는다. 첫 판정 뒤에도 같은 컨테이너를 유지하며, 판정 직전과 파일 복원 직전의 process 목록이 다르거나 archive가 제외한 소켓 목록이 달라지면 재실행하지 않고 상태 복원 실패로 분류한다. 두 목록이 같아도 process 메모리의 byte 단위 일치를 증명한 것은 아니다.

같은 상태에서 판정이 달라지면 verifier 변동으로 분류한다. 상태 복원이 불완전하면 모델 실행 변동과 verifier 변동을 구분할 수 없으므로 유효한 품질 결과로 세지 않는다.

기존 목적 선정 5과제의 20회 기준선은 최종 workspace와 컨테이너 상태를 이 계약대로 보존하지 않았다. 그 측정은 기존 범위에서 유지하지만 새 선별 자료로 재사용하지 않는다.

## Blob 보존과 회수

각 결과는 먼저 실행 VM의 로컬 spool에 원자적으로 확정한다. payload를 먼저 올리고 manifest를 마지막에 올린다. 각 객체를 다시 읽어 크기와 SHA-256을 확인하기 전에는 업로드 완료로 표시하지 않는다.

Blob 연산은 payload 쓰기, manifest 쓰기, payload 검증 읽기와 manifest 검증 읽기의 시작·성공 횟수를 따로 기록한다. 시작했지만 성공 응답을 확인하지 못한 연산은 비용 미확정으로 남긴다. 재시도로 성공해도 앞선 미확정 연산을 0으로 바꾸지 않는다.

네트워크나 Blob 오류가 나면 모델 실행을 즉시 버리지 않는다. 로컬 payload를 보존하고 제한된 background 재시도를 수행한다. 최종 flush 뒤에도 확인되지 않으면 상태는 `retrieval_pending`이며 완료로 바꾸지 않는다.

종료 순서는 다음과 같다.

1. 모든 payload와 manifest를 Blob에서 다시 읽어 SHA-256을 확인한다.
2. 별도 수집 환경에서 실제 크기의 결과를 내려받아 같은 hash를 확인한다.
3. 누락·중복 `trial`, `attempt`, 요청 ID와 비용 합계를 검사한다.
4. 필요한 verifier 재생 검사가 같은 판정을 내는지 확인한다.
5. 그 뒤에만 로컬 spool 정리와 VM deallocate를 허용한다.

Blob ETag를 내용 hash 대신 쓰지 않는다. 원격 hash 확인 전에는 로컬 증거를 삭제하지 않는다.

## 비용 기록

provider, VM, Blob 쓰기, Blob 검증 읽기와 network 비용을 구성요소별로 기록한다. 같은 통화와 가격 시점을 네 조건에 적용한다.

VM 비용은 실제 활성 구간을 동시에 실행 중인 `attempt`끼리 나눈다. 각 worker에 VM 전체 단가를 반복해서 곱하지 않으며 배분 합계가 VM 활성 구간 총액과 맞아야 한다.

비용이 확정되지 않은 구성요소가 하나라도 있으면 직접 귀속 총비용은 결측으로 둔다. 확인된 소계와 결측 구성요소 수는 함께 남긴다. 실제 지출 0과 계측 누락을 같은 값으로 기록하지 않는다.

공유 idle, 승인 대기, 일회성 준비와 Blob 장기 보관 비용은 별도 항목이다. 평가 주 비용에는 넣지 않지만 전체 운영비 설명에서 빠뜨리지 않는다.

## 분석 재현

평가 배열은 `반복 × 과제 × 네 조건` 순서를 고정한다. 같은 반복 실행의 `none`과 세 압축 조건을 함께 재표집해 짝 구조와 공유 `none` 상관을 보존한다.

주 분석과 길이 2의 시간 상관 민감도 분석에 서로 다른 용도별 seed를 쓴다. base seed `20260915`, numpy `PCG64`, percentile bootstrap 50,000회, 분위수 계산법 `linear`와 배치 크기를 manifest에 기록한다. 합성 자료 검증은 독립 seed `2026091501`을 쓴다.

분석 코드, 입력 배열, 결과와 manifest에는 실행 source commit을 기록한다. 평가 뒤 관측한 상관이나 분산으로 주 분석의 반복 수, 문턱 또는 신뢰구간을 바꾸지 않는다.

## 공개와 비공개 경계

| 비공개 Blob 원본 | 공개 문서에 허용 |
| --- | --- |
| 계정·테넌트·구독·리소스 식별자 | 공개 벤치마크·과제·도구·모델 이름과 공개 revision |
| endpoint, 비공개 host와 절대 경로 | 공개 저장소 상대 경로와 비식별 실행 환경 |
| provider request·response ID 원문 | 요청 수, 상태 분포와 hash 대조 결과 |
| 전체 prompt, tool trace와 assistant 출력 | 집계 token·호출·시간·실패 분류 |
| 최종 workspace 원문과 재생 archive | workspace hash와 재생 판정 일치 여부 |

환경, 도구, 버전, 날짜, 표본, 분모, 모델, 병렬도와 가격 시점은 수치를 해석하는 조건이므로 공개 집계에서 지우지 않는다. 식별자와 비공개 위치를 재현 조건과 섞지 않는다.
