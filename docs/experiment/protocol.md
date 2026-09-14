# 1차 실험 규약

이 문서는 고정 조건과 사전 중단 규칙을 기록한다. 설계 판단이며 결과 문서가 아니다. 현재는 추가 압축 없는 기준선만 측정했고, 압축 비교는 실행하지 않았다.

## 질문과 개입

질문은 코드 어시스턴트 워크로드에서 식별된 로그 후보만 줄였을 때 입력 크기, 품질, 전체 호출 비용이 어떻게 달라지는가이다. 코드, 지시문, assistant 이력은 바꾸지 않는다.

| 조건 | 실제 개입 | 분류 판단 |
| --- | --- | --- |
| `none` | 추가 압축 없음. Harbor의 기존 출력 생략은 유지 | 기준선 |
| `squeez` | 앞 30개 내용 줄을 남기고 후보의 뒤쪽을 삭제 | 버리기·손실 |
| `Headroom` | 반복 경로의 공통 접두어를 한 번만 표시하고 역변환 검사 | 묶기·바이트 복원 가능 |
| `LLMLingua-2` | 후보 안에서 남길 token을 선택 | token 선택·손실 |

## 고정 조건

| 항목 | 고정값 | 성격 |
| --- | --- | --- |
| 벤치마크 | Terminal-Bench 2.1, revision `7131e4375048a0e408a8fb404b5f499d726b695b` | 설계 판단 |
| 과제 | 목적 선정 영어 5과제: `cancel-async-tasks`, `log-summary-date-ranges`, `multi-source-data-merger`, `nginx-request-logging`, `openssl-selfsigned-cert` | 설계 판단 |
| 한 반복 | 5과제를 각각 한 번 실행하고 내장 채점하는 묶음 | 정의 |
| 모델 | `gpt-5.4`, 제공자 보고 revision `gpt-5.4-2026-03-05` | 고정 조건 |
| 생성 설정 | temperature `0`, reasoning effort `none`, 최대 completion `2,048` token | 고정 조건·결정론 보장 아님 |
| 실행 환경 | cloud VM, Linux kernel `6.17.0-1022-azure`, 8 vCPU | 측정 조건 |
| 실행기 | Harbor `0.22.0`과 그 버전에 포함된 instrumented Terminus 2 `2.0.0` | 고정 조건 |
| 병렬도 | native trial 8개 | 비교 통제 |
| 배포 한도 | 300,000 TPM, 3,000 RPM | 실행 시점 운영값 |
| 로컬 tokenizer | tiktoken `0.14.0`, `o200k_base` | 계산 조건 |
| 채점 | 각 과제의 내장 native verifier를 변경 없이 사용 | 고정 조건 |
| 기준선 실행 소스 | `2984a3879252d51d1681b9d4f6b3bf4f4871a12e` | 측정 계보 |
| 일정 상한 | 2026-09-17 | 운영 조건 |

temperature와 reasoning effort는 전송 설정이다. 같은 출력, 결정론, 무손실 관측을 보장하는 통제로 해석하지 않는다. 캐시 읽기 token도 관측하지만 통제했다고 주장하지 않는다.

## 실행 경로

cloud native 실행은 [`src/native_run.py`](../../src/native_run.py)가 조정하고 [`src/live_transport.py`](../../src/live_transport.py)가 보호 검사 뒤 요청을 전송한다. [`accounting.py`](../../accounting.py)는 별도의 로컬 Ollama 기록을 집계하는 경로이며, 이번 cloud 기준선의 실행기나 전송기가 아니다.

## 보호와 지표

후보 선택은 식별된 로그 구간에만 적용한다. 코드, 코드가 섞인 출력, 구조화 자료, 지시문, assistant 이력, 역할과 요청 설정은 보호한다. 보호 위반은 원문으로 되돌려 계속하지 않고 실행을 중단한다.

모든 조건에서 다음을 같은 단위로 기록한다.

- 제공자 보고 입력 token, 출력 token, cached input token
- `o200k_base`로 다시 센 message-content 입력 token과 보이는 assistant 출력 token
- 과제당 turn 수, 논리 호출 수, 재시도를 포함한 총 HTTP 호출 수
- 같은 명령과 같은 하위 명령의 재실행 횟수
- 내장 통과 여부와 `wrong_answer`, `wrong_format`, `timeout`, `tool_error`, `other` 실패 분류
- `compress_seconds`, `transport_seconds`, `model_seconds`
- LLMLingua-2의 worker inference, serialization wait, 전체 압축 벽시계

입력 token만 줄고 출력 token, 호출 수, 재실행, 비용이 늘면 비용 절감으로 판정하지 않는다. 실패 분류는 관측된 형태이며 압축이 원인이라는 진단이 아니다.

## 사전 중단 규칙

주판정은 한 반복에서 통과한 과제 수의 관측 범위다. 표본 표준편차는 보조 설명으로만 쓴다.

| 판단 시점 | 사전 규칙 | 다음 행동 | 성격 |
| --- | --- | --- | --- |
| 5회 | 통과 과제 수 범위의 폭이 `1`을 넘으면 중단 | 판정기·운영 경로·설계를 점검 | 운영 판단. 통계적 신뢰구간 아님 |
| 5회 | 폭이 `0` 또는 `1`이면 계속 | 10회까지 수집. 안정됐다고 쓰지 않음 | 운영 판단 |
| 10회 | 1–5회와 6–10회의 최소·최대 및 과제별 관측값 집합이 같음 | 기준선 범위 수집 종료 | 계산 규칙 |
| 10회 | 두 절반이 다름 | 총 20회까지 연장 | 계산 규칙 |
| 20회 | 1–10회와 11–20회가 다시 다름 | 판정 불가로 중단. 30회로 늘리거나 과제를 바꾸지 않음 | 계산 규칙 |

보호 위반, 필수 기록 누락, 설정 또는 model revision 변화, 회수 검증 실패도 중단 사유다. 압축 조건은 받아들인 기준선과 같은 반복 수를 사용한다.

## 실행 순서

1. `none` 기준선을 실행한다.
2. 기준선 중단 규칙의 결과를 확인한다.
3. 압축 비교 진행 여부를 사람이 결정한다.
4. 진행할 때만 squeez, Headroom, LLMLingua-2를 같은 규약으로 실행한다.

후보를 통째로 삭제하는 조건은 없다. 2026-09-14 기준선은 20회에서 판정 불가로 중단됐으며, 세 압축 조건은 아직 실행하지 않았다.
