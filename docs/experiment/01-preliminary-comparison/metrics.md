# 1차 실험 과제별 변경 조건 대조표

이 문서는 [1차 실험 한 장 요약](README.md)의 조건별 합계를 과제별로 펼친
상세 매트릭스다. 문자열이 실제로 달라진 23조건에는 같은 과제의 `none`을
나란히 두었다. 과제 순서는 기존 inventory 순서이며 통과 여부, 감소율이나
비용으로 다시 정렬하지 않았다.

## 표를 읽는 방법

- **변경 구간 로컬 토큰**은 실제로 달라진 문자열만 `tiktoken 0.14.0`의
  `o200k_base`로 다시 센 값이다. 전체 요청 토큰이나 청구 토큰이 아니다.
- **변경 구간 기준 감소율**의 분모는 해당 행의 변경 전 로컬 토큰이다.
- 판정은 과제 내장 채점기가 기록한 `pass`와 `wrong_answer`를 그대로 썼다.
- **API 계산 비용**은 제공자 사용량에 고정 가격표를 적용한 값이며 소수 셋째
  자리까지 표시했다. 실제 청구서와 대사한 금액은 아니다.
- 압축 조건과 `none`은 각각 한 번 실행했다. 같은 과제라는 이유만으로 요청 수,
  캐시 상태와 실행 경로가 같다고 보거나 차이를 압축 효과로 귀속하지 않는다.

## 문자열이 달라진 23조건

| 과제 | 압축 조건 | 변경 구간 수 | 변경 구간 로컬 토큰 (전) | 변경 구간 로컬 토큰 (후) | 변경 구간 기준 감소율 | 압축 조건 판정 | 압축 조건 API 계산 비용 | 같은 과제 `none` 판정 | 같은 과제 `none` API 계산 비용 |
|---|---|---:|---:|---:|---:|---|---:|---|---:|
| [`crack-7z-hash`](tasks.md#과제와-관측값) | Headroom | 18 | 21,456 | 11,502 | 46.4% | `pass` | `$0.338` | `pass` | `$0.810` |
| [`crack-7z-hash`](tasks.md#과제와-관측값) | LLMLingua-2 | 24 | 40,112 | 20,712 | 48.4% | `pass` | `$0.191` | `pass` | `$0.810` |
| [`dna-assembly`](tasks.md#과제와-관측값) | LLMLingua-2 | 7 | 490 | 231 | 52.9% | `wrong_answer` | `$0.161` | `wrong_answer` | `$0.262` |
| [`modernize-scientific-stack`](tasks.md#과제와-관측값) | Headroom | 5 | 205 | 160 | 22.0% | `pass` | `$0.062` | `pass` | `$0.073` |
| [`modernize-scientific-stack`](tasks.md#과제와-관측값) | LLMLingua-2 | 3 | 123 | 72 | 41.5% | `pass` | `$0.036` | `pass` | `$0.073` |
| [`torch-tensor-parallelism`](tasks.md#과제와-관측값) | LLMLingua-2 | 1 | 46 | 21 | 54.3% | `wrong_answer` | `$0.029` | `wrong_answer` | `$0.039` |
| [`gcode-to-text`](tasks.md#과제와-관측값) | LLMLingua-2 | 7 | 518 | 252 | 51.4% | `wrong_answer` | `$0.133` | `wrong_answer` | `$0.064` |
| [`log-summary-date-ranges`](tasks.md#과제와-관측값) | squeez | 2 | 6,654 | 1,652 | 75.2% | `wrong_answer` | `$0.037` | `wrong_answer` | `$0.029` |
| [`log-summary-date-ranges`](tasks.md#과제와-관측값) | Headroom | 2 | 260 | 188 | 27.7% | `wrong_answer` | `$0.054` | `wrong_answer` | `$0.029` |
| [`log-summary-date-ranges`](tasks.md#과제와-관측값) | LLMLingua-2 | 2 | 6,842 | 3,206 | 53.1% | `wrong_answer` | `$0.040` | `wrong_answer` | `$0.029` |
| [`llm-inference-batching-scheduler`](tasks.md#과제와-관측값) | LLMLingua-2 | 6 | 288 | 138 | 52.1% | `wrong_answer` | `$0.323` | `pass` | `$0.609` |
| [`model-extraction-relu-logits`](tasks.md#과제와-관측값) | LLMLingua-2 | 3 | 207 | 102 | 50.7% | `wrong_answer` | `$0.074` | `wrong_answer` | `$0.101` |
| [`overfull-hbox`](tasks.md#과제와-관측값) | LLMLingua-2 | 10 | 660 | 340 | 48.5% | `pass` | `$0.105` | `wrong_answer` | `$0.204` |
| [`prove-plus-comm`](tasks.md#과제와-관측값) | LLMLingua-2 | 7 | 446 | 210 | 52.9% | `pass` | `$0.043` | `pass` | `$0.027` |
| [`raman-fitting`](tasks.md#과제와-관측값) | LLMLingua-2 | 10 | 385 | 195 | 49.4% | `wrong_answer` | `$0.096` | `wrong_answer` | `$0.128` |
| [`sqlite-with-gcov`](tasks.md#과제와-관측값) | LLMLingua-2 | 4 | 284 | 140 | 50.7% | `pass` | `$0.104` | `pass` | `$0.229` |
| [`vulnerable-secret`](tasks.md#과제와-관측값) | LLMLingua-2 | 4 | 280 | 128 | 54.3% | `pass` | `$0.062` | `pass` | `$0.065` |
| [`video-processing`](tasks.md#과제와-관측값) | LLMLingua-2 | 6 | 438 | 192 | 56.2% | `wrong_answer` | `$0.173` | `wrong_answer` | `$0.150` |
| [`chess-best-move`](tasks.md#과제와-관측값) | LLMLingua-2 | 14 | 1,008 | 420 | 58.3% | `wrong_answer` | `$0.232` | `wrong_answer` | `$0.112` |
| [`schemelike-metacircular-eval`](tasks.md#과제와-관측값) | Headroom | 28 | 8,344 | 5,852 | 29.9% | `wrong_answer` | `$0.946` | `wrong_answer` | `$0.565` |
| [`schemelike-metacircular-eval`](tasks.md#과제와-관측값) | LLMLingua-2 | 25 | 7,450 | 4,500 | 39.6% | `wrong_answer` | `$0.679` | `wrong_answer` | `$0.565` |
| [`build-pov-ray`](tasks.md#과제와-관측값) | LLMLingua-2 | 13 | 923 | 455 | 50.7% | `wrong_answer` | `$0.362` | `pass` | `$0.600` |
| [`feal-differential-cryptanalysis`](tasks.md#과제와-관측값) | LLMLingua-2 | 8 | 304 | 156 | 48.7% | `pass` | `$0.101` | `pass` | `$0.444` |
| **합계** | **23조건** | **209** | **97,723** | **50,824** | **48.0%** | **`pass` 9 · `wrong_answer` 14** | **별도 행 합계** | **비교용 단일 `none`** | **과제별 중복 표시** |

## 압축기를 적용했지만 문자열이 달라지지 않은 55조건

| 범위 | 조건 수 | `pass` | `wrong_answer` | API 계산 비용 합 |
|---|---:|---:|---:|---:|
| squeez·Headroom·LLMLingua-2 중 기록된 변환 문자열 변경이 0건인 조건 | 55 | 20 | 35 | `$12.335` |

55조건에는 압축 후보가 없었던 경우와, 후보가 있었지만 해당 프로필의 규칙이
문자열을 바꾸지 않은 경우가 함께 있을 수 있다. 현재 공개 집계로 두 경우를
나누지는 못한다. `$12.335`는 각 조건의 정밀 API 계산 비용을 합한 뒤 소수
셋째 자리로 표시한 값이며 실제 청구서가 아니다.

## 표에서 보이는 관측

이 23조건에서는 변경 구간 기준 감소율이 22.0%인 `pass`와 75.2%인
`wrong_answer`가 함께 있었고, 48%대에서도 두 판정이 모두 나타났다. 압축 조건
비용도 같은 과제의 `none`보다 낮은 행과 높은 행이 함께 있다. 이 표에서는
감소율이 클수록 통과하거나 비용이 낮아지는 순서가 보이지 않는다. 조건당 1회인
예비 관측이므로 상관이나 인과가 없다고 일반화하지 않는다.

## 출처

- [26과제와 네 조건의 쉬운 설명](tasks.md)
- [조건별 품질·비용과 변경 구간 토큰 원문](preliminary-comparison-20260916.md)
- [1차 실험 한 장 요약](README.md)
