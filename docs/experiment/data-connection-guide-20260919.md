# 실데이터 연결 가이드

KT가 원본 데이터를 공개 저장소에 올리지 않고 자체 환경에서 실제 1과제를 실행하려면 아래 순서대로 진행한다. 여기서 **무호출 확인(preflight)**은 설정과 파일 연결을 검사하되 외부 모델 서비스(provider)의 API를 호출하지 않는 단계다. **결과 JSON**은 실행 상태, 사용량, 판정과 파일 지문을 기계가 읽을 수 있게 남긴 파일이며, **JSON 구조 규칙(Schema)**이 필수 항목과 값의 형식을 정한다.

## 30초 요약

1. 원본 데이터, 연결 주소(endpoint), 인증 정보와 내부 경로는 고객사 환경 밖으로 내보내지 않는다.
2. 공개 실행 설정 파일(YAML)에는 환경변수 이름, 고정 벤치마크 과제 ID와 `runs/` 아래 JSON 출력 이름만 둔다.
3. 먼저 기본 명령으로 무호출 확인을 마친다. `status=checked`는 연결 확인이지 품질 통과가 아니다.
4. 승인된 운영자가 환경변수와 비공개 실행 원장을 준비한 뒤에만 `--execute`를 붙인다.
5. 실행 뒤에는 결과 Schema로 JSON 모양을 확인하고, 기술 완료 여부와 품질 판정을 따로 읽는다. `technical_incomplete`는 오답이 아니다.

이번 문서 작업에서는 모델이나 provider를 호출하지 않았다. 공개된 [실제 1과제 YAML](../../examples/experiment/benchmark.yaml), [기존 실행 연결 코드](../../src/benchmark_run.py), [기존 단일 과제 실행기](../../src/screening_run.py)와 [결과 Schema](../../schemas/experiment-result.schema.json)만 설명한다.

## 먼저 확인할 지원 범위

현재 공개 경로는 임의의 고객 데이터 형식을 받는 범용 실행기가 아니다. 고정된 Terminal-Bench 2.1 revision과 공개 과제 색인에 있는 과제 하나를, KT가 관리하는 비공개 벤치마크 소스 사본(checkout)과 실행 환경에서 돌리는 경로다.

- **가능:** 고객사 환경에 둔 지원 benchmark checkout, 비공개 실행 대상·파일 해시 목록(inventory)과 provider 설정을 공개 저장소에 복사하지 않고 연결한다.
- **불가능:** 고객사 고유 문서나 새 과제를 YAML에 적는 것만으로 실행한다. 공개 과제 색인에 없는 과제는 무호출 확인에서 거부된다.
- **별도 검토 필요:** 고객사 고유 데이터를 새 과제로 연결하려면 입력 연결 코드(adapter), 판정자와 원장 계약을 먼저 설계하고 검증해야 한다. 이 가이드는 그 기능이 이미 있다고 가정하지 않는다.

첫 연결은 고정된 실제 benchmark 과제 하나가 고객사 환경에서 계약대로 실행되고 결과 JSON까지 검증되면 성공이다. 이 한 번의 결과로 제품 도입, 압축 효과나 일반적인 품질을 판단하지 않는다.

## KT가 준비하는 값과 저장소가 고정하는 값

### 고객사 환경에서만 준비하는 값

아래 표에는 값이 아니라 환경변수 이름만 적었다. 실제 주소, 접근 권한을 주는 인증 정보(credential), 조직 계정 식별값(tenant 값)과 개인 경로는 비밀 저장소나 실행 환경에 두고 문서, YAML, 이슈와 결과 설명에 붙여 넣지 않는다.

| 환경변수 이름 | 값의 역할 | 공개 여부 |
| --- | --- | --- |
| `FOUNDRY_ENDPOINT` | KT가 승인한 모델 연결 주소 | 값은 비공개 |
| `SCREENING_OPERATIONAL_LEDGER` | 승인 내용을 채운 비공개 실행 원장 경로 | 파일과 경로 모두 비공개 |
| `TERMINAL_BENCH_ROOT` | 고정 revision의 benchmark checkout 경로 | 원본과 경로 모두 비공개 |
| `SCREENING_INVENTORY` | 해시를 계산한 실행 inventory 경로 | 원본과 경로 모두 비공개 |
| `FOUNDRY_QUEUE_STATE` | 같은 배포 자원(deployment)을 쓰는 순서를 조정하는 queue 상태 경로 | 값은 비공개 |
| `PROVIDER_RPM_LIMIT`, `PROVIDER_TPM_LIMIT` | provider가 허용한 처리량 | 값은 비공개 |
| `TIKTOKEN_CACHE_DIR` | 토큰 수를 세는 고정 도구(tokenizer)의 자료 경로 | 값은 비공개 |
| `NATIVE_BLOB_ACCOUNT_URL`, `NATIVE_BLOB_SPOOL_ROOT` | 비공개 실행 증거의 저장·회수 위치 | 값은 비공개 |

인증은 KT가 승인한 플랫폼 인증 주체(identity) 또는 비밀 관리 절차로 공급한다. 키와 token을 YAML이나 실행 원장에 기록하지 않는다.

KT가 공개 YAML에서 고를 수 있는 것은 공개 색인에 있는 과제 ID와 `runs/` 아래 결과 JSON 이름이다. 다른 과제를 고른 YAML도 source checkout 안에 commit한 뒤 깨끗한 `HEAD`에서 실행해야 한다.

### 저장소가 고정하고 검증하는 값

| 항목 | 고정 내용 | 확인 위치 |
| --- | --- | --- |
| benchmark | Terminal-Bench 2.1 이름, revision, 공개 과제 색인 | [공개 참조 원장](../../ledgers/screening.template.toml) |
| 모델 설정 | `gpt-5.4`, 보고된 revision, `temperature=0`, reasoning 설정 | 공개 참조 원장 |
| 조건 | 추가 압축 없는 기준인 `none` | 공개 참조 원장과 YAML |
| 실행 경로 | `src.screening_run --diagnose-task` | 결과 JSON의 `resolved_contract.runner` |
| 보호 계약 | 재현 묶음(replay bundle), 완전한 증거 보존, 재시도(retry) 설정 | 공개 참조 원장과 결과 JSON |
| 결과 모양 | 상태, 사용량, 비용, 품질, 완료와 산출물 해시 | [결과 Schema](../../schemas/experiment-result.schema.json) |

실행 연결 코드(wrapper)는 비공개 실행 원장을 공개 참조 원장과 비교한다. 비공개 원장에서 바꿀 수 있는 것은 inventory 파일 지문, provider 제한 근거, deployment 분리 근거와 세 승인 필드뿐이다. 모델, 조건, 실행기(runner), 판정 규칙이나 retry를 함께 바꾸면 실행 전에 거부한다.

## 1. 원본 데이터를 저장소 밖에서 준비한다

**파일 지문(SHA-256 해시)**은 파일 내용이 같은지 확인하는 64자리 값이다. 원본을 공개하지 않아도 같은 파일을 썼는지 대조할 수 있지만, 해시 자체도 고객사 검토 전에는 비공개로 취급한다.

1. 고정 revision의 benchmark checkout과 inventory를 저장소 밖 비공개 위치에 둔다.
2. inventory 파일의 SHA-256을 계산한다.
3. 공개 참조 원장을 저장소 밖으로 복사해 비공개 실행 원장으로 쓴다.
4. 허용된 여섯 필드만 채우고, 원본 inventory와 실행 원장의 해시 기록을 함께 보관한다.

```bash
sha256sum '<private-inventory-file>'
cp ledgers/screening.template.toml '<private-directory>/screening.operational.toml'
sha256sum '<private-directory>/screening.operational.toml'
```

비공개 실행 원장에서 채울 필드는 다음뿐이다.

| section.field | 넣을 내용 |
| --- | --- |
| `benchmark.inventory_sha256` | 위에서 계산한 inventory SHA-256 |
| `queue.limits_source_reference` | provider 제한을 확인한 비공개 근거 참조 |
| `queue.deployment_isolation_reference` | 공유 deployment 조정 근거 참조 |
| `approval.preregistered` | 사전 계획 승인 여부 |
| `approval.execution_authorized` | 실제 유료 실행 승인 여부 |
| `approval.reference` | 승인 기록 참조 |

원본 입력, prompt, endpoint 값, credential, tenant 값과 내부 경로는 이 파일에도 넣지 않는다. 환경변수에는 앞 표의 이름에 해당하는 값을 실행 시점에 주입한다.

## 2. 실제 1과제 YAML을 확인한다

[공개 예제](../../examples/experiment/benchmark.yaml)는 합성 입력이 아니라 고정 벤치마크의 실제 과제 하나를 가리킨다.

```yaml
schema_version: 2
experiment: native
endpoint_env: FOUNDRY_ENDPOINT
benchmark:
  name: terminal-bench-2.1
  revision: 7131e4375048a0e408a8fb404b5f499d726b695b
  task: cancel-async-tasks
model: gpt-5.4
condition: none
output: runs/readme-benchmark-result.json
```

YAML에는 endpoint의 **환경변수 이름**만 있고 주소는 없다. 원본 데이터 경로도 없다. 처음에는 이 파일을 그대로 사용한다. 다른 지원 과제를 선택하려면 `benchmark.task`와 충돌하지 않는 새 `runs/` JSON 이름만 바꾸고, 변경한 YAML을 KT의 비공개 fork 또는 승인된 source branch에 commit한다. Runner는 untracked 파일까지 포함해 source checkout이 깨끗한지 확인한다.

## 3. 모델을 부르지 않고 먼저 확인한다

Python 3.12 이상과 `uv`가 있는 깨끗한 commit checkout에서 실행한다.

```bash
uv sync --locked
uv run --locked python run.py experiment examples/experiment/benchmark.yaml
uv run --locked python run.py experiment \
  --verify-result runs/readme-benchmark-result.json
```

첫 명령은 YAML, 현재 Git commit, 공개 참조 원장, 과제 색인과 결과 계약을 확인한다. `--execute`가 없으므로 provider를 호출하지 않는다. 두 번째 명령은 생성된 JSON이 [결과 Schema](../../schemas/experiment-result.schema.json)에 맞는지 검사한다.

무호출 확인이 끝나면 아래 상태가 나온다.

```text
status = checked
outcome = preflight_passed
labels.measured = false
provider_usage.status = not_measured
quality.status = not_measured
completion.technical_status = not_run
```

`checked`는 “실행 전에 확인할 연결이 맞다”는 뜻이다. 모델 답변, 품질과 비용은 아직 측정하지 않았다. Schema 통과도 JSON 모양을 확인할 뿐, 값의 진실성이나 청구서를 보증하지 않는다.

무호출 경로의 현재 clean-checkout 검증 범위는 [검증 기록](../../data/experiment/readme-benchmark-validation-20260920.json)에 있다. 그 기록에도 실제 provider 실행은 포함되지 않았다.

## 4. 승인 뒤에만 실제 실행한다

실행 전 운영자는 다음을 확인한다.

- 환경변수 값과 플랫폼 identity가 실행 세션에만 주입됐는가.
- 비공개 실행 원장이 허용된 여섯 필드만 바꿨는가.
- inventory SHA-256과 실제 파일이 일치하는가.
- provider 처리량 제한, deployment 공유 조정과 유료 실행 승인이 기록됐는가.
- 원본과 실행 산출물이 고객사 관리 경계를 벗어나지 않는가.

현재 공개 참조 원장은 저장소 차원의 비용·호출 수·경과 시간 중단값을 두지 않는다. Provider 제한과 운영자 승인만으로 실행해도 되는지 KT가 먼저 결정해야 한다. 이 가이드는 새 중단 장치를 추가하지 않는다.

모든 값과 승인이 준비된 경우에만 다음 명령을 사용한다.

```bash
uv sync --locked --extra native
uv run --locked python run.py experiment \
  examples/experiment/benchmark.yaml --execute
```

`--execute`는 비공개 실행 원장을 다시 검사한 다음 기존 `screening_run --diagnose-task`에 과제 하나를 넘긴다. 새 실행기나 우회 경로를 만들지 않는다. 이 문서 작업에서는 위 명령을 실행하지 않았다.

## 5. 결과 JSON을 검증하고 판정을 읽는다

실행이 끝났든 중간에 기술적으로 멈췄든 같은 검증 명령을 사용한다.

```bash
uv run --locked python run.py experiment \
  --verify-result runs/readme-benchmark-result.json
```

| 상태 조합 | 쉬운 뜻 | 품질로 셀 수 있는가 |
| --- | --- | --- |
| `checked` + `preflight_passed` | 무호출 확인만 끝남 | 아니요 |
| `completed` + `measurement_completed` + `quality.status=pass` | 기술 실행과 채점이 끝났고 통과 | 예, 이 실행 1건에서만 |
| `completed` + `measurement_completed` + `quality.status=wrong_answer` | 기술 실행과 채점이 끝났고 답이 틀림 | 예, 오답 1건 |
| `completed` + `measurement_completed` + `quality.status=wrong_format` | 기술 실행과 채점이 끝났고 형식이 틀림 | 예, 형식 오답 1건 |
| `failed` + `technical_incomplete` | 실행이나 증거 수집이 끝나지 않음 | 아니요. 오답으로 바꾸지 않음 |

`quality.status=unknown` 또는 `not_measured`도 품질 미확정이다. 기술 미완료를 오답으로, 관측되지 않은 usage를 0으로 바꾸지 않는다. `completion.operator_status=stopped`는 운영자가 중간에 멈춘 기록이며 품질 판정과 별개다.

한 번의 `pass`나 `wrong_answer`는 해당 과제의 해당 실행만 설명한다. `temperature=0`도 같은 답을 보장하지 않으며, 반복 없이 조건 간 순위나 비열등성을 말할 수 없다.

## 6. 어떤 해시를 보존할지 확인한다

| 기록 | 무엇을 묶는가 | 보관 위치 |
| --- | --- | --- |
| `lineage.source_commit` | 실행한 공개 source commit | 결과 JSON |
| `lineage.config_sha256` | 실제 1과제 YAML | 결과 JSON |
| `lineage.ledger_sha256` | 공개 참조 원장 | 결과 JSON |
| `resolved_contract.execution_ledger_sha256` | 승인된 비공개 실행 원장 | 결과 JSON |
| `lineage.source_sha256` | 증거에 남은 입력 출처 | 확보된 경우 결과 JSON |
| `artifacts`의 SHA-256 | summary, attempt와 provenance 등 산출물 | 결과 JSON |
| inventory·원본·최종 JSON SHA-256 | 고객사가 보관한 비공개 파일 | 고객사 비공개 해시 기록 |

최종 JSON도 별도로 해시한다.

```bash
sha256sum runs/readme-benchmark-result.json
```

파일을 다른 위치로 전달할 때는 바이트 수와 SHA-256을 함께 대조한다. 해시 일치가 품질 통과를 뜻하지는 않는다. 같은 파일이라는 사실만 확인한다.

## 7. 네 종류의 수치를 섞지 않는다

| 수치 | 무엇을 재는가 | 다른 수치와의 경계 |
| --- | --- | --- |
| 로컬 토큰 측정 | 고정 tokenizer로 로컬에서 센 입력·출력 또는 실제 변경 구간 | Provider 청구 토큰이 아님 |
| 전체 API usage | Provider가 보고한 모든 모델 요청의 입력·cache·출력 token | 변경 구간만의 값이 아님 |
| 계산 비용 | 완결된 API usage와 원장 단가로 계산한 USD | 실제 청구서가 아님 |
| 실제 청구서 | Provider가 별도 청구한 금액 | 결과 JSON 밖에서 대사해야 함 |

공개 1과제 YAML의 `condition=none`은 추가 압축 없는 기준이므로 압축 변경 구간 절감을 만들지 않는다. 나중에 압축 조건을 별도로 비교하더라도 **실제 변경 구간 토큰**은 바뀐 문자열 구간만 센 로컬 값이고, `provider_usage`는 한 실행에서 발생한 모델 요청 전체다.

`cost.calculated_usd`가 있어도 `cost.invoice_reconciled=false`라면 계산값을 청구 금액이라고 쓰지 않는다. `provider_usage.status=requires_review`이거나 값이 `null`이면 미확정으로 남긴다.

## 8. 공개와 비공개 산출물을 나눈다

| 자료 | 기본 등급 | 처리 원칙 |
| --- | --- | --- |
| 고객 원본·benchmark checkout·inventory | 비공개 원본 | 저장소, 이슈, PR과 공개 첨부에 올리지 않음 |
| endpoint·credential·tenant 값·내부 경로 | 비공개 운영 정보 | 환경과 비밀 관리 도구 밖으로 내보내지 않음 |
| 비공개 실행 원장·queue·원본 증거 | 비공개 실행 자료 | 고객사 보존 정책에 따라 접근 제한 |
| `runs/` 아래 결과와 해시 기록 | 검토 전 비공개 | `.gitignore` 대상이며 자동 공개하지 않음 |
| 검토한 집계·가공 문서 | 승인 뒤 공개 가능 | 원본 행과 운영 값을 제거하고 공개 허용 목록 검사를 통과해야 함 |

공개 등급과 금지 경로는 [공개 범위 계약](../publication.md)을 따른다. 결과 JSON이 Schema를 통과했다고 공개 승인이 생기는 것은 아니다. 고객 데이터 반출 금지는 실행 성공보다 우선한다.

## 자주 막히는 경우

| 보이는 결과 | 먼저 확인할 것 | 해석 |
| --- | --- | --- |
| `preflight_error`와 dirty checkout 메시지 | 수정·미추적 파일이 없는 commit checkout인지 | Provider 호출 전 중단 |
| `technical_incomplete`와 endpoint 환경변수 메시지 | `FOUNDRY_ENDPOINT` 값이 실행 세션에 있는지 | 품질 오답 아님 |
| 실행 원장 불일치 | 허용된 여섯 필드 외에 바뀐 값이 없는지 | 고정 계약 보호로 중단 |
| `provider_usage.status=requires_review` | unknown usage attempt와 원본 증거 | 0으로 대체하지 않음 |
| `wrong_answer` | Terminal-Bench 판정 증거와 verifier revision | 기술 실행은 완료, 품질은 오답 |
| 결과 JSON Schema 실패 | 누락·잘못된 타입·알 수 없는 필드 | 공개나 집계 전에 수정 필요 |

같은 오류를 자동 재전송하지 않는다. 특히 provider가 요청을 처리했는지 불명확하면 원본 요청 식별자, 마지막 응답과 usage 불확실성을 보존한 뒤 운영자가 재실행 여부를 결정한다.

## 이 절차로 말할 수 있는 것과 없는 것

**관측할 수 있는 것**

- 고정된 과제 하나가 어떤 source, YAML과 원장 해시로 실행됐는지
- Provider usage가 완결됐는지, 기술 실행과 품질 판정이 각각 무엇인지
- 계산 비용이 있는지, 실제 청구서와 대사됐는지

**가능한 설명**

- 실행 간 usage나 비용이 다르면 요청 수, cache, 모델이 밟은 경로와 provider 동작이 함께 영향을 줬을 수 있다.
- 품질이 다르면 모델 비결정성, 실행 환경이나 판정 과정도 가능한 설명이다.

**이 절차만으로 말할 수 없는 것**

- 차이가 압축 때문에 생겼다는 인과 관계
- 다른 모델·과제·고객사 고유 데이터에서도 같은 결과가 난다는 일반화
- 압축기 순위, 품질 비열등성, 모집단 절감률이나 실제 청구 절감

현재 경로는 조건당 1회 연결 확인에 알맞다. 비교 결론이 필요하면 입력 adapter와 판정자를 검증하고, 바뀌는 축, 반복 수, 중단 조건과 청구서 대사 방법을 별도 실험 설계로 먼저 고정한다.

## 실행 전 마지막 확인

- [ ] 원본 데이터와 모든 운영 값은 공개 저장소 밖에 있다.
- [ ] 실행 source는 commit됐고 `git status --porcelain` 출력이 비어 있다.
- [ ] YAML의 과제는 공개 색인에 있고 출력은 `runs/*.json`이다.
- [ ] 무호출 결과가 `checked` + `preflight_passed`로 검증됐다.
- [ ] 비공개 실행 원장은 허용된 여섯 필드만 채웠다.
- [ ] Provider 제한, 공유 deployment 조정과 유료 실행 승인이 있다.
- [ ] `--execute` 뒤 JSON Schema, 상태, usage, 품질과 해시를 각각 확인한다.
- [ ] 공개 전 [공개 범위 계약](../publication.md)과 파일 허용 목록 검사를 통과한다.

관련 근거는 [재현 계약](reproducibility-contract.md), [실제 1과제 요청 Schema](../../schemas/benchmark-request.schema.json), [결과 Schema](../../schemas/experiment-result.schema.json), [공개 참조 원장](../../ledgers/screening.template.toml)과 [기존 runner](../../src/benchmark_run.py)에서 확인할 수 있다.
