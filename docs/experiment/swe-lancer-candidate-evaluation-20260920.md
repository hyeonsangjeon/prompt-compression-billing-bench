# SWE-Lancer 3차 벤치마크 후보 평가

## 결론

SWE-Lancer는 이번 검토에서 **보류**로 분류했다. 고정 과제 한 건의 실행 관문까지 진행했지만 credential, provider pin, 격리 sandbox 조건을 충족하지 못해 worker·model·provider를 시작하기 전에 종료됐다. 실제 trace와 grader 결과는 없다.

이 결론으로 후보 평가 카드는 닫을 수 있다. 다만 “제한된 3차 진단 후보로 채택”한 것은 아니다. 실제 한 건을 다시 시도하려면 아래의 직접 조건을 별도 작업에서 먼저 갖춰야 한다.

## 무엇을 고정했나

선택 규칙은 task 내용을 보기 전에 공식 README의 단일 `ic_swe` 예시로 정했다.

| 항목 | 고정값 |
|---|---|
| task | `28565_1001`, `split=diamond`, `task_type=ic_swe` |
| upstream | `openai/frontier-evals` commit `51052cede8cc608f95bb00346635e03759013e5a` |
| solver SHA-256 | `860c8bf2e65d02de9d768ff36fee6d80bb8d3dfa9955e6b83ad983ea49c62012` |
| catalog SHA-256 | `5c3a6d4570b49be0d9fced98f5b32487420b16f25c98d6658830e31fa03f049a` |
| 선택 행 | 2,761 UTF-8 bytes, SHA-256 `ff7ea7f9d37739a30adff1d26f51eb3baee87a1cad421d4e1cc17c26adb19702` |
| image manifest | `sha256:b6ee529bbc589b251d2e287aa28068ea4f7e69b3eac2927b393091ac968e7587` |
| runtime | Python 3.12.13 |
| provider/model 설정 | `openai/gpt-4o` |

task 본문, reference answer와 raw catalog 행은 공개하지 않는다. 이 문서의 task ID는 고정 upstream README에 공개된 실행 예시를 가리킨다.

## 무엇을 실행했나

실행 승인을 연결한 private ledger에 fresh UTC deadline을 넣고 `--execute`를 한 번 호출했다. 전체 attempt 한도는 4,920초, cleanup reserve는 120초, attempt와 run의 계산 비용 상한은 각각 USD 20.00이었다.

관문은 2026-09-20T03:28:18.991196619Z부터 2026-09-20T03:28:23.409942658Z까지 4.417423510초 동안 실행됐다. 결과는 exit 2와 `technical_preflight_failure`였다. source, catalog, 선택 행, runtime과 supervisor 지문은 일치했고, 실행 전 조건 7개가 남아 fail closed 됐다.

남은 조건은 다음과 같다.

1. 실행 process에 `OPENAI_API_KEY`가 없음
2. 실제 사용 권한이 확인되지 않음
3. reported model revision이 고정되지 않음
4. 공식 input/output 단가가 고정되지 않음
5. 가격 출처 URL과 revision 또는 조회 시각이 고정되지 않음
6. task-owned Docker/Alcatraz endpoint가 없음
7. run별 network isolation과 cleanup 근거가 없음

선택 image의 registry manifest는 HEAD 요청에서 HTTP 200과 고정 digest를 반환했다. image body는 내려받지 않았다. 이 요청은 image 접근성 확인이며 provider 요청과는 별개다.

## 관측한 값과 관측하지 않은 값

| 항목 | 관측 |
|---|---:|
| logical model request | 0 |
| provider HTTP attempt | 0 |
| tool call / result | 0 / 0 |
| retry | 0 |
| trace event | 0 |
| provider usage record | 0 |
| grader | 미시작 |

provider 요청이 없었으므로 계산된 provider 비용은 USD 0.00이다. 단가와 가격 출처는 확인하지 못했고 invoice도 관측하지 않았다. host compute 비용도 측정하지 않았다.

같은 result 경로를 다시 사용한 통제는 exit 3으로 거부됐고 원 bytes와 SHA-256을 유지했다. 기존 v4 red, v5 `not_ready`와 후보 check 기록도 수정하지 않았다. private 판정 검증 18/18과 과거 기록 보존 대사 4/4를 통과했다. 이 분모는 계약과 보존 검사의 수이며 model이나 grader 정확도가 아니다.

## 해석 한계

이번 기록은 한 task의 실행 준비 경로만 평가한다. SWE-Lancer trace, task 품질, 대표성, benchmark pass rate, 비열등성, 모집단 비용이나 invoice를 측정한 결과가 아니다. 실제 trace가 없으므로 request body, model-visible message, tool 결과, provider usage와 grader outcome을 재현하는 자료도 아니다.

## 별도 후속 조건

다시 실행하려면 다음을 별도 Backlog에서 준비한다.

1. credential 값을 기록하지 않은 채 bounded process에 주입하고 실제 사용 권한을 확인한다.
2. 검토된 공식 근거로 model revision과 input/output 단가를 고정한다.
3. 고정 image digest를 실행할 task-owned Docker/Alcatraz endpoint를 제공하고 외부망 차단과 cleanup을 관측한다.
4. 같은 task에 새 result 경로와 새 절대 deadline을 발급한다.

공개 template인 [`ledgers/swe-lancer.template.json`](../../ledgers/swe-lancer.template.json)은 승인과 private evidence pin이 비어 있어 실행용이 아니다. [`src/swe_lancer_admission.py`](../../src/swe_lancer_admission.py)는 result를 먼저 배타 예약하고 source·evidence 지문과 deadline을 검사하지만 worker나 provider를 시작하지 않는다. 설정이 적혀 있다는 사실만으로 격리나 권한이 검증됐다고 판정하지 않는다.

기계 판정은 [`data/experiment/swe-lancer-candidate-evaluation.json`](../../data/experiment/swe-lancer-candidate-evaluation.json)에 있다. private task body, raw trace, credential, endpoint 값, container 식별자와 실행 경로는 포함하지 않았다.
