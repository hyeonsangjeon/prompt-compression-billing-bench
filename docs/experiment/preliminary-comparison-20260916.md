# 무압축과 세 압축 조건의 예비 비교 관측

이 파일은 공개 검토용 초안이다. 원본 요청·응답, 내부 경로, provider request ID는 포함하지 않는다. 아래 수치는 7개 과제에서 `none`, `squeez`, `Headroom`, `LLMLingua-2`를 한 번씩 실행한 28개 조건 관측이다. 같은 과제의 네 조건은 서로 연결돼 있으므로 28개 독립 과제로 세지 않는다. 이 결과는 비열등성, 모집단 비용 절감, 압축기 순위를 입증하지 않는다.

| 선정 집단 | 과제 | 조건 관측 | pass / wrong_answer | 실제 변경이 있었던 조건 |
|---|---:|---:|---:|---:|
| 첫 실행 과제 | `cancel-async-tasks` 1개 | 4 | 0 / 4 | 0 |
| 보존된 무압축 기록에서 허용 로그 후보가 확인된 과제 | 5개 | 20 | 12 / 8 | 6 |
| 기존 후보 소진 뒤 새 무압축 실행에서 후보를 확인한 과제 | `extract-elf` 1개 | 4 | 2 / 2 | 0 |
| 합계 | 7개 | 28 | 14 / 14 | 6 |

세 집단은 전체 89개 과제의 대표 표본이 아니다. 두 번째 집단의 다섯 과제는 품질이나 예상 절감률이 아니라, 보존된 무압축 기록에서 보호 규칙을 통과한 로그 후보가 확인된 순서로 골랐다. 그 후보를 모두 실행한 뒤에는 아직 비교하지 않은 과제 중 사전 고정 과제 목록 순서상 첫 과제에서 새 `none` 실행을 먼저 완료했고, 그 실행에서 후보를 확인한 뒤에만 세 번째 집단의 네 조건을 실행했다. 실제 새 실행에서는 모델 경로가 달라 후보가 없거나 변환기가 바꾸지 않은 조건도 있었다.

## 측정 조건

- 소스: 첫 실행 과제는 `c079b143a9f51eeb823b52f39d02ec7a2a9fa87a`, 나머지 여섯 과제는 `5e1f8655950471ea15b1b428632b074070dda020`
- 모델: `gpt-5.4`, provider 보고 모델 `gpt-5.4-2026-03-05`, `temperature=0`, `reasoning_effort=none`
- 실행: `cancel-async-tasks`의 네 조건은 순차 실행했다. 나머지 여섯 과제는 `none`·`squeez`·`Headroom`을 병렬 실행하고, `LLMLingua-2`는 CPU 경합을 피하려고 세 조건 종료 뒤 단독 실행했다.
- 각 조건은 같은 과제 이미지·과제 파일·채점기에서 새 컨테이너와 새 작업공간으로 시작했다. 보존 기록에서 후보를 확인한 다섯 과제에서는 첫 모델 입력의 의미 있는 내용이 조건 간 같았고, 달랐던 한 줄은 무작위 컨테이너 hostname이 들어간 `root@…:/app#` 셸 프롬프트뿐이었다.
- provider 입력·캐시·출력 토큰은 provider가 보고한 사용량이다. API 비용은 이 사용량에 고정 가격표를 곱한 계산값이며 청구서 대사액이 아니다.
- 나머지 여섯 과제의 조건별 원장 가상 머신 비용은 서로 다른 프로세스에서 겹침을 알지 못해 최종값으로 쓰지 않는다. 아래 사후 배분은 모든 조건의 실제 작업 구간을 시작·종료 시점으로 나누고, 각 구간의 비용을 그때 실행 중인 조건에 균등 배분했다. 시간당 단가는 `$0.403`이다. 원장 원값은 그대로 보존한다.
- 원격 증거 확인은 모든 조건에서 작업공간 저장, 복원, 재채점 판정 일치, 시도 자료 해시, 묶음 자료 해시를 모두 통과했다.

## 횟수 정의

- **provider 논리 요청**: 원장 `logical_model_calls`; 외부 API에 보낼 모델 요청 한 건이다.
- **HTTP 시도**: 원장 `total_model_calls`; 전송 재시도를 포함한 provider HTTP 시도 수다.
- **Harbor 단계**: 원장 `turns`; Harbor가 기록한 완료된 agent 단계 수이며 HTTP 시도 수와 다른 단위다.
- **허용 로그 후보 처리**: 원장 `compressor.completed_calls`; 보호 규칙을 통과한 로그 후보가 조건 adapter를 완료한 횟수다. `none`도 후보를 그대로 통과시키므로 0이 아닐 수 있다.
- **실제 변경**: 원장 `compressor.changed_occurrences`; adapter 전후 바이트가 달라진 후보 수다.
- **LLMLingua-2 worker 추론**: 원장 `compressor.worker_inference_calls`; `LLMLingua-2` worker가 실제 추론한 횟수다. 다른 조건에는 같은 worker가 없으므로 0이다.

## 별도 집단: `cancel-async-tasks`

이 과제는 허용 로그 후보를 선별 조건으로 쓰기 전에 실행했다. 네 조건 모두 `wrong_answer`였고, 작업공간 복원 뒤 재채점도 같은 판정이었다. 네 조건에서 변환기 adapter 호출과 실제 변경은 모두 0건이었다.

- 비교 원장: `preliminary-20260916T022024Z-c68388c9`
- 비교 manifest 파일 SHA-256: `58027a8ca71d05afb30cf0cb4a8610e2af0c308d860b4edf1f26a0521a3e01c2`
- 비교 manifest 내용 SHA-256: `c4f8ce229b3dd4ef8e26f36eea14ae427569ef59a51fc376d295b75e542cbf2a`
- 비교 상태 파일 SHA-256: `fa48366cf818a9bbaa1dedec83ebc5df2c306b4158d28229c40c8173703dd7c1`
- 이미지 digest: `sha256:84c7fae6b256dcc56a350790e2a9715eefc7dad662a9d8e8a472363aa71ef18d`
- 과제 파일 tree SHA-256: `1b6e83a625ffda559bf8511bcf0c708bcb26b04ffd8923b1dc90f14c19ddddaa`
- 채점기 source tree SHA-256: `205c267bd18adccf19239f50f82f2e60caa32cb06065219046de30d8985c3175`

| 조건 | 품질 | provider 논리 요청 / HTTP 시도 | Harbor 단계 | 허용 로그 후보 처리 / 실제 변경 | 입력 / 캐시 / 출력 토큰 |
|---|---:|---:|---:|---:|---:|
| none | wrong_answer | 2 / 2 | 확인 안 됨 | 0 / 0 | 2,375 / 1,152 / 593 |
| squeez | wrong_answer | 2 / 2 | 확인 안 됨 | 0 / 0 | 2,527 / 1,024 / 542 |
| Headroom | wrong_answer | 4 / 4 | 확인 안 됨 | 0 / 0 | 7,610 / 4,224 / 991 |
| LLMLingua-2 | wrong_answer | 2 / 2 | 확인 안 됨 | 0 / 0 | 2,544 / 0 / 585 |

이 초기 원장은 Harbor 단계 수를 별도 필드로 보존하지 않았다. 확인 안 된 값을 provider 요청 수나 0으로 대신하지 않았다.

| 조건 | provider 계산 비용 | 기록된 활성 가상 머신 비용 | 확인된 Blob·network 비용 | 직접 비용 합 | 작업 / 조건 전체 시간(초) |
|---|---:|---:|---:|---:|---:|
| none | $0.012241 | $0.011456 | $0.0000432 | $0.023740 | 102.337 / 113.223 |
| squeez | $0.012144 | $0.008764 | $0.0000432 | $0.020951 | 78.292 / 82.797 |
| Headroom | $0.024386 | $0.010150 | $0.0000432 | $0.034579 | 90.668 / 142.629 |
| LLMLingua-2 | $0.015135 | $0.009942 | $0.0000432 | $0.025120 | 88.809 / 207.622 |

네 작업 구간은 서로 겹치지 않았다. 기록된 활성 가상 머신 비용 합은 `$0.040311902`다. 이 값은 공유 idle, 승인 대기, 일회성 준비, Blob 보존 비용, 계측되지 않은 network를 포함하지 않는다.

| 조건 | 조건 run ID | run summary SHA-256 | attempt 파일 SHA-256 |
|---|---|---|---|
| none | `preliminary-none-20260916T022026Z-944c88e1` | `e271bc1c03cf646f118addc2b04e6d1096fca4332f14a3abf9e5e191a9c7f972` | `8520741463753ac5f09216a2a4447d3f9b52778ab36958ee4bcd00d898f8753b` |
| squeez | `preliminary-squeez-20260916T022225Z-37bbde5e` | `f81d1763aea0e36c07e4e289ba1f2531e27abe78fdd96d90f3cf3c7e19db9d09` | `95cc34ab743b77381860053656a883835d8b48ba8e65099c09c3d3b5441254a4` |
| Headroom | `preliminary-headroom-20260916T022729Z-350beb1a` | `25c326bcd30d51ad74ab14d5e1739189a9d96b5680c5b6084096862a15469b58` | `fc52e47d32a7ce5ef3a2e80d82c63323be85697e08b8e55f702a3444c715a9b9` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T022355Z-67a07031` | `dd13acc029adb2b281685a01be42788a1a861fb498eac71f5a09e4bd4b3c8a93` | `cc35275f4e9b2734645a036a44136d0e1f5baf7f323ccdcbf8bcad7d8cf44358` |

이 초기 비교는 조건별 별도 결과 파일 대신 비교 상태 파일 안에 조건 결과를 보존했다. 위 표는 각 조건의 실제 run summary와 attempt 파일 해시를 연결한다.

## `crack-7z-hash`

- 비교 원장: `preliminary-candidate-continuation-20260916T034044Z-a7387c9f`
- 비교 manifest 파일 SHA-256: `b432887f2974610ed4c9ad82a418ac0cafbf546edab35159b98ebe09d6341f8b`
- 비교 manifest 내용 SHA-256: `2a5cd56e0d2905650ecd52d4f4064a07fe4b12a1ead08d1ed07d8d30928ad498`
- 이미지 digest: `sha256:0f4453abd774c5a3d3d7e66ba28fae88ec2e49ada3a993b324ebc16c348666d3`
- 과제 파일 tree SHA-256: `1abd0cb371b37e665eb35f40d6e6d49fb4559866c2fc1f6e5d6db0fdd5428d7d`
- 채점기 source tree SHA-256: `c196b31f22e2f89855e85551fba964e4a75dd77b96475d90f4ff6cf5a4cc37ee`

| 조건 | 품질 | provider 논리 요청 | HTTP 시도 | Harbor 단계 | 허용 로그 후보 처리 | 실제 변경 | LLMLingua-2 worker 추론 | 입력 / 캐시 / 출력 토큰 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | pass | 53 | 53 | 53 | 148 | 0 | 0 | 1,217,052 / 1,082,624 / 13,538 |
| squeez | pass | 24 | 24 | 24 | 45 | 0 | 0 | 261,471 / 138,880 / 7,123 |
| Headroom | pass | 20 | 20 | 20 | 87 | 18 | 0 | 233,658 / 146,432 / 5,575 |
| LLMLingua-2 | pass | 15 | 15 | 15 | 24 | 24 | 24 | 159,676 / 128,000 / 5,311 |

| 조건 | provider 계산 비용 | 원장 가상 머신 비용 | 겹침 사후 배분 가상 머신 비용 | 확인된 Blob·network 비용 | 사후 배분 직접 비용 합 | 작업 / 조건 전체 시간(초) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.809796 | $0.096744 | $0.066055 | $0.0000432 | $0.875894 | 864.212 / 869.605 |
| squeez | $0.448043 | $0.050960 | $0.020269 | $0.0000432 | $0.468355 | 455.228 / 459.609 |
| Headroom | $0.338298 | $0.031338 | $0.010447 | $0.0000432 | $0.348788 | 279.945 / 284.162 |
| LLMLingua-2 | $0.190855 | $0.034335 | $0.034335 | $0.0000432 | $0.225233 | 306.711 / 435.954 |

가상 머신 사후 배분 합은 실제 작업 구간 합집합 `1,171.167026초`, `$0.131105642`이며 조건별 배분 합과 일치한다. 세 병렬 조건과 단독 `LLMLingua-2`의 시간은 같은 운영 조건이 아니므로 조건 전체 시간을 압축기 속도 비교로 읽으면 안 된다.

| 조건 | 후보 입력 UTF-8 바이트 | adapter 출력 UTF-8 바이트 | 실제 변경 후보 입력 → 출력 | 직접 변환 전후 토큰 |
|---|---:|---:|---:|---:|
| none | 479,874 | 479,874 | 변경 없음 | 기록하지 않음 |
| squeez | 28,244 | 28,244 | 변경 없음 | 기록하지 않음 |
| Headroom | 210,130 | 181,312 | 62,388 → 33,570 바이트, 18건 | 기록하지 않음 |
| LLMLingua-2 | 90,606 | 45,934 | 90,606 → 45,934 바이트, 24건 | 기록하지 않음 |

provider 비용 차이는 전체 agent 실행의 관측이다. 조건마다 요청 수와 이후 경로가 달라졌고 `squeez`는 실제 변경이 0건인데도 `none`과 비용이 크게 달랐다. 따라서 이 한 묶음의 비용 차이를 압축의 인과적 절감률로 해석하지 않는다.

| 조건 | 조건 run ID | 조건 결과 SHA-256 | run summary SHA-256 | attempt 파일 SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T034100Z-15a3ef03` | `bbe9c874a0f5edfc057c44283ac908eb90768e6230b70fbb1ffbd47b4b9b9045` | `b876ce82599b1454bd5e0f0b0bb9d07297e86acb918053c873844fef39749b07` | `af3fead33eedeb64b603c9b36812ddf6616505db45da62f84c75595c407871eb` |
| squeez | `preliminary-squeez-20260916T034100Z-f076e850` | `924e305e10ed8f3bcb979ad13d04a23ddde3e96c39d0db591685d4e347523de6` | `5af6763185ec87e73dcc4ddabef751dabf435b72d4fb355c8609e378bf007681` | `f050700581062fd63e0571185c2bb4c20c86960b7863129a917d5b7f3111bb0c` |
| Headroom | `preliminary-headroom-20260916T034100Z-b6bed5dd` | `f11849c8484bb2eeffb01b32f46da19aa14c1f9d078fa8ae5ebe390892c98c3b` | `10af850c3f6a423a916cbe45d83249a13ac6bc3b3be7fb94ccd4282a4abb133d` | `dd3d4d2a4490c7b681d3b0007ee416d4b772ee066378bb8b57ab1dab7dd8ae43` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T035537Z-c55293f8` | `8480ee954b6453d17a6b1a6723922b2ae35dac84bd293f8d0464c88f5dc2a765` | `ce6eb4285e8eb63dc71919d65d20da75f9a1d195ba26c162394c026bd2889d93` | `614c41dadb5c3cfdbdb2758ccdd75e64211e03a9e41a1a260c79abcc844be5f7` |

## `dna-assembly`

- 비교 원장: `preliminary-candidate-20260916T040804Z-5ea9af72`
- 비교 manifest 파일 SHA-256: `d214cf5a0fa4c3e748eabf44ac5a93e4df0814e5ab29ee006eca5a177a9c6842`
- 비교 manifest 내용 SHA-256: `4641669e7f13e24ba5dda3cb9a295c9bc809c60d2f3d3d11e7f451926a118161`
- 이미지 digest: `sha256:d1adf6835f1dd91205ba70e452c699d0aea601010038e5617f370716efb50569`
- 과제 파일 tree SHA-256: `33f30f34089bbbe1c266ab88301d12d2cb9eb51c9cf5696041bab13468450511`
- 채점기 source tree SHA-256: `6687e7c7a79d1029bca162a97c67976c890d4c4cdc0a6ee0681024e391b1483f`

| 조건 | 품질 | provider 논리 요청 | HTTP 시도 | Harbor 단계 | 허용 로그 후보 처리 | 실제 변경 | LLMLingua-2 worker 추론 | 입력 / 캐시 / 출력 토큰 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | wrong_answer | 6 | 6 | 6 | 0 | 0 | 0 | 83,272 / 27,392 / 7,703 |
| squeez | wrong_answer | 8 | 8 | 8 | 0 | 0 | 0 | 81,442 / 49,024 / 5,634 |
| Headroom | wrong_answer | 8 | 8 | 8 | 0 | 0 | 0 | 157,470 / 27,008 / 12,172 |
| LLMLingua-2 | wrong_answer | 8 | 8 | 8 | 7 | 7 | 7 | 81,455 / 56,960 / 5,709 |

| 조건 | provider 계산 비용 | 원장 가상 머신 비용 | 겹침 사후 배분 가상 머신 비용 | 확인된 Blob·network 비용 | 사후 배분 직접 비용 합 | 작업 / 조건 전체 시간(초) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.262093 | $0.020303 | $0.007286 | $0.0000432 | $0.269422 | 181.370 / 187.215 |
| squeez | $0.177811 | $0.017197 | $0.005732 | $0.0000432 | $0.183586 | 153.620 / 159.211 |
| Headroom | $0.515487 | $0.024302 | $0.011284 | $0.0000432 | $0.526814 | 217.085 / 222.781 |
| LLMLingua-2 | $0.161113 | $0.016155 | $0.016155 | $0.0000432 | $0.177311 | 144.315 / 234.964 |

가상 머신 사후 배분 합은 실제 작업 구간 합집합 `361.400329초`, `$0.040456759`이며 조건별 배분 합과 일치한다. `LLMLingua-2`만 7개 허용 로그 후보를 실제로 바꿨고, 직접 변환 경계는 `1,071 → 441 UTF-8 바이트`였다. 직접 변환 전후 토큰은 기록하지 않았다.

네 조건 모두 기술 오류가 아니라 유효한 품질 실패 `wrong_answer`다. 작업공간 복원 뒤 재채점도 같은 판정이었으며, 실패 결과를 숨기거나 기술 제외로 바꾸지 않는다.

| 조건 | 조건 run ID | 조건 결과 SHA-256 | run summary SHA-256 | attempt 파일 SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T040818Z-5bd568cd` | `21e9c192bbe07c39c25b3cea57325e8f5b8f4457ece30141156983b073d2459a` | `dcac8cf69d838e845de693389fe48cdaccd53cbb275440fd54ffbe1283477b81` | `2c202e9d94b3af81bc61547d8f71aa97b470a91807debef42fe6af0c7b15dbf8` |
| squeez | `preliminary-squeez-20260916T040818Z-9a110a37` | `423dd2816d6d48e648dce72947ab51a2950e9cfe29db82d2a3dd70ddfbd61c08` | `aa8a8d6dd93f265c40602b1290d3c65779850f9d00461421de7b586a145cde8b` | `2a55c31bd357d49c3fc4877633a1139ac3f2c95ddd2e221d63253d0786459ca0` |
| Headroom | `preliminary-headroom-20260916T040818Z-44b1ca83` | `ed20f6e27120eed45c9974c93d8597e855ba811dd837545d9c398f7098846303` | `d688f1597410736087a21693951e9b99132d7a905605b7a79cb12792fd72c36b` | `f560be491800daeb4360bcc95cb1551b69e004f23e49849c12f20bdc0942aa9a` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T041209Z-bc2ff477` | `33e9e7226443045bc9c901ef404c6278f704e2e7410f0a44e9336c5354a8b979` | `6c2a4049d2cb7695ba3e5d6661df5945e55bd5a2930144d7a427c8084d1299e5` | `133195c9b3337553690604d67899fd0930e1451221f570b675e8513535fbe49b` |

## `modernize-scientific-stack`

- 비교 원장: `preliminary-candidate-20260916T045049Z-dc600270`
- 비교 manifest 파일 SHA-256: `1c4cf2185eb8cce5ada24fad60a586e3bed4dd4d495570105f98610088a6206e`
- 비교 manifest 내용 SHA-256: `2a41ce97687936a9305dc256078b4b82b8225dc46fabe74c7a76da2f7ad91034`
- 이미지 digest: `sha256:64e69cee13bf6b0b9016e735b51891bce996a60f1e2d1a005bf12c949e221d71`
- 과제 파일 tree SHA-256: `62c5482bd23e28d9dcf59bc0dbeff773de079cc99959920c17cae815b0e748f5`
- 채점기 source tree SHA-256: `e218f92db8c5f88481407eeee7d739446aba827b042c720003d11f1fe34d1192`

| 조건 | 품질 | provider 논리 요청 | HTTP 시도 | Harbor 단계 | 허용 로그 후보 처리 | 실제 변경 | LLMLingua-2 worker 추론 | 입력 / 캐시 / 출력 토큰 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | pass | 6 | 6 | 6 | 5 | 0 | 0 | 23,131 / 5,504 / 1,864 |
| squeez | pass | 6 | 6 | 6 | 5 | 0 | 0 | 24,857 / 4,480 / 2,169 |
| Headroom | pass | 6 | 6 | 6 | 5 | 5 | 0 | 22,246 / 8,832 / 1,749 |
| LLMLingua-2 | pass | 4 | 4 | 4 | 3 | 3 | 3 | 11,573 / 4,992 / 1,241 |

| 조건 | provider 계산 비용 | 원장 가상 머신 비용 | 겹침 사후 배분 가상 머신 비용 | 확인된 Blob·network 비용 | 사후 배분 직접 비용 합 | 작업 / 조건 전체 시간(초) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.073404 | $0.013407 | $0.004523 | $0.0000432 | $0.077969 | 119.761 / 125.118 |
| squeez | $0.084598 | $0.013328 | $0.004452 | $0.0000432 | $0.089093 | 119.055 / 123.830 |
| Headroom | $0.061978 | $0.013305 | $0.004438 | $0.0000432 | $0.066459 | 118.854 / 122.517 |
| LLMLingua-2 | $0.036316 | $0.008277 | $0.008277 | $0.0000432 | $0.044635 | 73.935 / 162.673 |

가상 머신 사후 배분 합은 실제 작업 구간 합집합 `193.750264초`, `$0.021689266`이며 조건별 배분 합과 일치한다.

| 조건 | 후보 입력 UTF-8 바이트 | adapter 출력 UTF-8 바이트 | 실제 변경 후보 입력 → 출력 | 직접 변환 전후 토큰 |
|---|---:|---:|---:|---:|
| none | 830 | 830 | 변경 없음 | 기록하지 않음 |
| squeez | 830 | 830 | 변경 없음 | 기록하지 않음 |
| Headroom | 840 | 630 | 840 → 630 바이트, 5건 | 기록하지 않음 |
| LLMLingua-2 | 504 | 291 | 504 → 291 바이트, 3건 | 기록하지 않음 |

네 조건 모두 작업공간 복원 뒤 재채점까지 같은 `pass` 판정이었다. 후보 입력 바이트 합과 provider 사용량은 각 조건에서 모델이 실제로 밟은 경로의 관측이며 조건 간 고정 입력으로 통제된 값이 아니다.

| 조건 | 조건 run ID | 조건 결과 SHA-256 | run summary SHA-256 | attempt 파일 SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T045103Z-5e0ab8ee` | `a0133e8921c6d24a4f9017090deb9a30f0a6ab6e3f7f05771a6b025916792d6f` | `770720611ad74af6b85f04e54c47ac245a6f27acc9c9db3f3d5d7cb7945a6bae` | `1b66b32a71a2999269313914d2f50738d675737b0d3f1f3e92e31bbefe27f7c7` |
| squeez | `preliminary-squeez-20260916T045103Z-fa7f8692` | `2c893224c46e89a995747fb3f9fd029758bbcef6267794782b0db7410a385fd0` | `6b89322313a3730959fd7e5387a36a708842c24d35fed0f4c3c1d39f1104ba38` | `39b13a1d6ee6209e8ad53da9898bea2279306808fc1022cd1c61720ac6d05ca3` |
| Headroom | `preliminary-headroom-20260916T045103Z-0a5e9b31` | `c06e10fb9d8b3552c933789707fc6bb63ca4eb4653a14a48d3d2471c00995aad` | `4d35afe235819ac9055eda358c03371a7c32b56b19789e32cb9e837ecb27d7ea` | `5019ec71b60a651f3f02079838705cf774e37c2a3a291d2c97ce7b2daebe4df4` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T045316Z-ca4151e5` | `df7abf3ae646af8ee02107987ceee8a5fa7e67f89a324567498224e0a2f86a65` | `d1d4ea98a0b47e0184771549474e3f432d45433808be6502af9744e59b130bbc` | `c6ccc991f8064dfe6e5c43ee527c2d5007e44788cdcea424b6efea7ecc766f70` |

## `sam-cell-seg`

- 비교 원장: `preliminary-candidate-20260916T050028Z-af2d2e76`
- 비교 manifest 파일 SHA-256: `b9c36b38d2ca14e5b9163d352863c1165e04634dd9cc80cfdd6611b0c8075296`
- 비교 manifest 내용 SHA-256: `6a23eea084bc8c383221c7a010fa37de628998ed2bae99c6d6c55bd7cfa270aa`
- 이미지 digest: `sha256:d76bdeef19d8113f4094013249c982eca93e62e46130484846269b2d378879d0`
- 과제 파일 tree SHA-256: `0db189b462ac19ca1c7a94bb51037c7d6f4f64cf3c626fbb2acbe643b6f4f6e6`
- 채점기 source tree SHA-256: `ec76e726b89e77baee578707b9818b6376c68202d710a14cfeddf319cff2d676`

| 조건 | 품질 | provider 논리 요청 | HTTP 시도 | Harbor 단계 | 허용 로그 후보 처리 | 실제 변경 | LLMLingua-2 worker 추론 | 입력 / 캐시 / 출력 토큰 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | pass | 5 | 5 | 5 | 0 | 0 | 0 | 43,579 / 19,328 / 8,081 |
| squeez | pass | 6 | 6 | 6 | 5 | 0 | 0 | 37,841 / 10,240 / 4,764 |
| Headroom | pass | 4 | 4 | 4 | 0 | 0 | 0 | 38,796 / 14,720 / 7,469 |
| LLMLingua-2 | pass | 5 | 5 | 5 | 0 | 0 | 0 | 32,391 / 18,048 / 4,451 |

| 조건 | provider 계산 비용 | 원장 가상 머신 비용 | 겹침 사후 배분 가상 머신 비용 | 확인된 Blob·network 비용 | 사후 배분 직접 비용 합 | 작업 / 조건 전체 시간(초) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.186675 | $0.035469 | $0.012982 | $0.0000432 | $0.199699 | 316.841 / 318.514 |
| squeez | $0.143023 | $0.028578 | $0.009535 | $0.0000432 | $0.152601 | 255.284 / 256.486 |
| Headroom | $0.175905 | $0.035491 | $0.013031 | $0.0000432 | $0.188979 | 317.040 / 318.418 |
| LLMLingua-2 | $0.107135 | $0.029068 | $0.029068 | $0.0000432 | $0.136246 | 259.668 / 345.897 |

가상 머신 사후 배분 합은 실제 작업 구간 합집합 `577.210349초`, `$0.064615492`이며 조건별 배분 합과 일치한다.

| 조건 | 후보 입력 UTF-8 바이트 | adapter 출력 UTF-8 바이트 | 실제 변경 후보 입력 → 출력 | 직접 변환 전후 토큰 |
|---|---:|---:|---:|---:|
| none | 0 | 0 | 허용 로그 후보 없음 | 기록하지 않음 |
| squeez | 1,090 | 1,090 | 변경 없음, 5건 | 기록하지 않음 |
| Headroom | 0 | 0 | 허용 로그 후보 없음 | 기록하지 않음 |
| LLMLingua-2 | 0 | 0 | 허용 로그 후보 없음 | 기록하지 않음 |

사전 선정에 사용한 보존 무압축 시도에는 허용 로그 후보 1건이 있었지만, 이번 네 새 실행에서는 모델 경로가 달라 `squeez`만 후보를 만들었다. `squeez`도 후보를 바꾸지 않았으므로 이 묶음에는 실제 압축 적용 관측이 없다. 네 조건의 비용 차이를 압축 절감으로 해석하지 않는다.

| 조건 | 조건 run ID | 조건 결과 SHA-256 | run summary SHA-256 | attempt 파일 SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T050030Z-e465ea92` | `d8b3c6e6161e7e6ba62ced64b144b968ec8c432526a43134a5b64379b0aeaaba` | `4504c0e6876468f925e563524ad62895a2180f644b7860c39e0bbd0e98245319` | `fa9beb39ffcc9be5f73ec0cdf6fa57c729221289a023eff8950f9add6200fbe5` |
| squeez | `preliminary-squeez-20260916T050030Z-c10b9987` | `fa35429d2188cd1130b4f2039b0b3dcac2d04452f123e177b99e7dbc4d09a050` | `3c1889d68786330bca6c623c0a1839925368a92e0e51a2dc438700ecb460f1da` | `e5eacc6402ab0a5ca6655282947b58078af89f82a0f40c516f26dee1f1c25cf7` |
| Headroom | `preliminary-headroom-20260916T050030Z-3adebd5f` | `1c26f198d5a020b14d295d20c526c275bd6228ec27c73251c51335f2e9802d34` | `89fe43ef3c58cb29995c35be1cc1671f8fe89b3fa5b78ae7b88b125c65ea7853` | `b3a6ec4d58fb51fb3d51852af22795f71a45208275d51ea5f96f6dcec236b6f2` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T050558Z-ae86b7b2` | `50309eceeb9c36a1ce0c72d513bbfa79e806e25731b7d272c7be51201595e759` | `e91906bcc9c6c6764615560cc5f8c323ced3e2072e929fd27b269eb5f90ef820` | `b148c9cbf39b8ddfb65ade434f5c7554312a663302effe8926fa830cebc71f7c` |

## `torch-tensor-parallelism`

- 비교 원장: `preliminary-candidate-20260916T051248Z-73a0b4fd`
- 비교 manifest 파일 SHA-256: `ac6075a9e041638fcb03a87d5ee1155ae46541289111e87de6fc9a9b7ca3605e`
- 비교 manifest 내용 SHA-256: `b3412d33c4c74adab1a989b4d770cf99962cb98a1014761ea03ac1e788c24abb`
- 이미지 digest: `sha256:c50ac169e11465f41b49749fe87e4487f24d31a0c39c0906cd3242cc5499c690`
- 과제 파일 tree SHA-256: `9986acd4e26d496dbcb3ce83e6b3e036160ea93b798780dbd9c0a691a3ae09f6`
- 채점기 source tree SHA-256: `a7b6a9426ab8af530c36278ff251b3435c4561897b139856e169fbc93c259a58`

| 조건 | 품질 | provider 논리 요청 | HTTP 시도 | Harbor 단계 | 허용 로그 후보 처리 | 실제 변경 | LLMLingua-2 worker 추론 | 입력 / 캐시 / 출력 토큰 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | wrong_answer | 3 | 3 | 3 | 2 | 0 | 0 | 6,262 / 0 / 1,565 |
| squeez | wrong_answer | 2 | 2 | 2 | 1 | 0 | 0 | 4,660 / 0 / 1,319 |
| Headroom | wrong_answer | 3 | 3 | 3 | 2 | 0 | 0 | 7,568 / 0 / 1,167 |
| LLMLingua-2 | wrong_answer | 2 | 2 | 2 | 1 | 1 | 1 | 3,963 / 0 / 1,272 |

| 조건 | provider 계산 비용 | 원장 가상 머신 비용 | 겹침 사후 배분 가상 머신 비용 | 확인된 Blob·network 비용 | 사후 배분 직접 비용 합 | 작업 / 조건 전체 시간(초) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.039130 | $0.070116 | $0.024445 | $0.0000432 | $0.063618 | 626.344 / 631.604 |
| squeez | $0.031435 | $0.068851 | $0.023177 | $0.0000432 | $0.054655 | 615.049 / 621.032 |
| Headroom | $0.036425 | $0.067521 | $0.022508 | $0.0000432 | $0.058976 | 603.162 / 608.294 |
| LLMLingua-2 | $0.028988 | $0.030490 | $0.030490 | $0.0000432 | $0.059521 | 272.370 / 364.824 |

가상 머신 사후 배분 합은 실제 작업 구간 합집합 `898.839734초`, `$0.100620115`이며 조건별 배분 합과 일치한다.

| 조건 | 후보 입력 UTF-8 바이트 | adapter 출력 UTF-8 바이트 | 실제 변경 후보 입력 → 출력 | 직접 변환 전후 토큰 |
|---|---:|---:|---:|---:|
| none | 190 | 190 | 변경 없음, 2건 | 기록하지 않음 |
| squeez | 95 | 95 | 변경 없음, 1건 | 기록하지 않음 |
| Headroom | 190 | 190 | 변경 없음, 2건 | 기록하지 않음 |
| LLMLingua-2 | 95 | 40 | 95 → 40 바이트, 1건 | 기록하지 않음 |

네 조건 모두 기술 오류가 아니라 유효한 품질 실패 `wrong_answer`였고 복원 뒤 재채점도 같은 판정이었다. `LLMLingua-2`의 직접 변환 1건과 전체 실행 비용은 별도 관측이며, 한 번의 품질·비용 차이로 압축의 인과 효과를 주장하지 않는다.

| 조건 | 조건 run ID | 조건 결과 SHA-256 | run summary SHA-256 | attempt 파일 SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T051250Z-cefdb89b` | `d6abc88b04f31c86700af89caad74ac2ca8428c96de996060a623cd2d9d59a90` | `3c2fe67a6681dc45b979a966208a1e0d658df240572ff09acc92f5af1a10b5e6` | `af0861d64c804788683595d5ba05599d9f7fe963a135737f3466c0799c1962bb` |
| squeez | `preliminary-squeez-20260916T051250Z-7c851981` | `c56da022b6b0d4cd2eccdb9abac2e1ad3214439e9bbb027ccdc17bc81ec34136` | `007eccf70bff95b4027fe3d6b40c23d0bc4e8bf73e17c453d2dc203ad5edf59e` | `9a60306cb52c61a85346d8af492b4f8da706f2af6b4e59875bcaa22131995013` |
| Headroom | `preliminary-headroom-20260916T051250Z-be58bc2f` | `914201637fbb0527fb7ef5774fc833add91cb722c0af71d80f8e009cfc2d5eb7` | `0fe85b04c1cedaf91a2c477bebc05771c28ecb59c438ea3b246dd154add64556` | `190fa69d752ab4687af6f3b8b5410726ca4c44f231ef0c0de9bcbc185eaee84a` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T052331Z-1079341c` | `804e3288bc68fecc335581535791c22be2838059897af91256442353e1322177` | `6553f52d86850b689076f2a37eb007e67d3284edc50a6b365219a9f277c0cd13` | `485b16aebf9a5a17b3bcbe954686613944252ffdbb4c7c8069916fa5c1ed7cc4` |

## `extract-elf`

보존된 무압축 기록에서 바로 확인할 수 있던 후보 과제를 모두 실행한 뒤, 아직 비교하지 않은 과제 중 사전 고정 과제 목록 순서상 첫 과제로 `extract-elf`를 정했다. 품질 결과와 예상 비용 절감은 선정에 사용하지 않았다. 별도 `none` 전체 실행은 `pass`였고 재채점·Blob 검증까지 완료됐으며, 두 번째 provider 요청에서 허용 로그 후보 1건·193 UTF-8 바이트를 모델 호출 없이 확인한 뒤 네 조건을 실행했다.

- 비교 원장: `preliminary-candidate-20260916T053916Z-90f05ebf`
- 비교 manifest 파일 SHA-256: `3888c1c000cec2ed4618514f3cef094d642a52414f73f4cc98752289d6838708`
- 비교 manifest 내용 SHA-256: `7bbbc5838153c95c723f1c6addd7011df737f8a53166aace622d7bc7ca7f8eb5`
- 비교 상태 파일 SHA-256: `9c56da5034389f7f49fbeecb25faea5c9c8a74bbc903a7e1fd48d38f9d1ea54d`
- 이미지 digest: `sha256:6932e4cb318464307eacd497ef8dc617eaf551b6a90231f815ec0b911895cfed`
- 과제 파일 tree SHA-256: `ec291e5bff1262e1dc176f3b06931a53c17d45d461b398763a8cf0c217e1cec6`
- 채점기 source tree SHA-256: `87b7da138926c05a1a8f878f6bc190de575e452e3e339864b01fd2c61543da91`

| 조건 | 품질 | provider 논리 요청 | HTTP 시도 | Harbor 단계 | 허용 로그 후보 처리 | 실제 변경 | LLMLingua-2 worker 추론 | 입력 / 캐시 / 출력 토큰 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| none | wrong_answer | 6 | 6 | 6 | 0 | 0 | 0 | 51,050 / 23,936 / 3,960 |
| squeez | pass | 5 | 5 | 5 | 0 | 0 | 0 | 24,161 / 0 / 1,863 |
| Headroom | pass | 3 | 3 | 3 | 0 | 0 | 0 | 12,773 / 0 / 1,272 |
| LLMLingua-2 | wrong_answer | 5 | 5 | 5 | 0 | 0 | 0 | 40,836 / 23,296 / 2,779 |

| 조건 | provider 계산 비용 | 원장 가상 머신 비용 | 겹침 사후 배분 가상 머신 비용 | 확인된 Blob·network 비용 | 사후 배분 직접 비용 합 | 작업 / 조건 전체 시간(초) |
|---|---:|---:|---:|---:|---:|---:|
| none | $0.133169 | $0.011915 | $0.005876 | $0.0000432 | $0.139088 | 106.438 / 116.141 |
| squeez | $0.088348 | $0.009077 | $0.003034 | $0.0000432 | $0.091424 | 81.088 / 90.906 |
| Headroom | $0.051013 | $0.009056 | $0.003031 | $0.0000432 | $0.054087 | 80.902 / 90.806 |
| LLMLingua-2 | $0.091359 | $0.009639 | $0.009639 | $0.0000432 | $0.101041 | 86.108 / 179.361 |

가상 머신 사후 배분 합은 실제 작업 구간 합집합 `192.777041초`, `$0.021580319`이며 조건별 배분 합과 일치한다. 세 병렬 조건과 단독 `LLMLingua-2`의 시간은 같은 운영 조건이 아니다.

사전 `none` 실행에서는 허용 로그 후보를 확인했지만, 네 새 조건은 서로 다른 agent 경로를 밟으며 실제 실행 중 허용 로그 후보를 만들지 않았다. 따라서 변환기 호출과 실제 변경은 네 조건 모두 0건이다. 품질과 비용 차이는 유효한 실행 관측이지만 압축 적용 효과의 증거가 아니다. 네 조건 모두 작업공간 복원 뒤 재채점 판정이 같았고 원격 자료 해시를 확인했다.

| 조건 | 조건 run ID | 조건 결과 SHA-256 | run summary SHA-256 | attempt 파일 SHA-256 |
|---|---|---|---|---|
| none | `preliminary-none-20260916T053918Z-c0cdf1c7` | `95c065dec75bf7fe3208d933dbd9eb0d138d8d146ab57daffab5e1c7965819ea` | `6e77326ec9b03ccec76b4a081f19b3cfbfbe28c38aeebce885e0b66be7f534ec` | `c1fc7440d32d64ebc202d5ea935b935f7cf5966181ce0a3cf57fa93ee1796130` |
| squeez | `preliminary-squeez-20260916T053918Z-db43a633` | `0337ce1a4a45a16b28a4146989a523b892376a45712670b889df97061fd69062` | `7a7c73e7055fef6127c4f22beee892cba287b99b2ac7fa52b5706d94a1d441ed` | `6d76f4fec0876f9ea7da8f864dd8e6b73ef1b0695f25f3b874d4f5824e5df618` |
| Headroom | `preliminary-headroom-20260916T053918Z-ac89be1d` | `6e6b1d5a3eb4fde3bc3013bd438eff1a393ddbda35fe93f847eb8c580943218d` | `0ccdaee63fee1ade3f069c681f48d7cf592469103f1dfec65b5799e95a61a6e6` | `056a5d5907eea9b45c33423a785311d879fafdd4a06b915a66a348210ed2f5fe` |
| LLMLingua-2 | `preliminary-llmlingua2-20260916T054115Z-a129b591` | `e21cc5df47b8ca169ef3bcd0034b4fcda87713bbcbc12d20b201c580bab0ff78` | `b29bc93ddde4eef24dcb260da51ee8fb6817b90f8ee70e9fa929ea0534abe04d` | `234587f63c42623d0c4b90070163500b8820b6bac74613baf7ee6fb7c17dc4e7` |

## 해석 한계

- 보존 기록에서 후보를 확인한 다섯 과제, 그 전에 실행한 `cancel-async-tasks`, 후보 소진 뒤 새 `none` 실행으로 고른 `extract-elf`는 선정 집단과 시점이 다르며 전체 89개 과제를 대표하지 않는다.
- 7개 과제의 28개 조건 관측은 28개 독립 과제가 아니다. 과제별 네 조건은 같은 과제·모델·이미지·채점기를 공유한다.
- 과제당 조건별 1회라 실행 변동과 조건 효과를 분리할 수 없다.
- provider 캐시를 통제하지 않았고 실제 캐시 토큰도 조건마다 달랐다.
- 세 조건은 병렬, `LLMLingua-2`는 단독 실행이어서 시간과 가상 머신 비용은 운영 관측이다.
- 서로 다른 agent 경로가 서로 다른 요청 수·로그 후보 수·토큰 수를 만들었다. 직접 변환 경계의 바이트 변화와 전체 실행 비용은 별도 관측이다.
- Blob·network 비용은 기록된 쓰기와 확인 읽기 및 같은 지역 network 단가를 반영한다. Blob 보존 비용, 계측되지 않은 network, 공유 idle, 승인 대기, 일회성 준비는 포함하지 않는다.
