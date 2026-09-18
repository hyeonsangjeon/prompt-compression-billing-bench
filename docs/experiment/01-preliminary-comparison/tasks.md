# 1차 실험의 26과제

이 문서는 [1차 실험 한 장 요약](README.md)에 나온 26과제가 어떤 문제였는지
설명한다. 과제 이름과 공개 지시문은 Terminal-Bench 2.1 고정 revision
`7131e4375048a0e408a8fb404b5f499d726b695b`을 따른다.

## 네 비교 조건

26과제를 아래 네 방식으로 각각 한 번 실행했다. 과제당 4조건, 모두 104조건이다.

| 조건 | 이번 실험에서 뜻하는 것 |
|---|---|
| `none` | 모델은 과제를 풀되 입력에 추가 압축을 하지 않은 기준 조건 |
| squeez `1.48.4` | 긴 출력의 앞 30개 내용 줄을 남기고 뒤를 버리는 압축 조건 |
| Headroom `0.36.5` paths-only | 반복되는 경로 접두어를 묶는 제한된 무손실 압축 조건 |
| LLMLingua-2 `0.2.2` | 줄 안의 token 가운데 남길 것을 고르는 손실 압축 조건 |

## 표를 읽는 방법

- **공개 통과 대상**은 공식 지시문이 요구한 파일과 동작을 짧게 옮긴 것이다.
  실제 `pass`와 `wrong_answer`는 과제 내장 채점기의 판정이다.
- **`pass` 수**는 `none`, squeez, Headroom, LLMLingua-2를 각각 한 번 실행한
  네 조건 가운데 내장 채점을 통과한 수다. 반복 통과율이 아니다.
- **시간 범위**는 네 조건의 조건 전체 시간 가운데 최소~최대다. 조건 간 동시성이
  달라 압축기 속도 비교로 읽지 않는다.
- **논리 요청**은 네 조건에서 모델 프록시가 받은 요청 수의 합이다. HTTP 시도,
  성공 응답, 작업에 전달한 응답과 같은 사건으로 취급하지 않는다.
- **API 계산 비용**은 네 조건의 제공자 사용량에 고정 가격표를 적용한 합계다.
  과제별 값은 소수 셋째 자리까지 반올림했다. 26개 표시값의 합은 `$22.333`이며,
  정밀 원본 합은 `$22.3333885`다. 실제 청구서와 대사한 금액은 아니다.

## 과제와 관측값

| 과제 | 무슨 문제이며 무엇을 만들면 되는가 | `pass` / 4조건 | 조건 전체 시간 범위 | 논리 요청 합 | API 계산 비용 합 |
|---|---|---:|---:|---:|---:|
| [1. `cancel-async-tasks`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/cancel-async-tasks/instruction.md) | 동시에 실행할 비동기 작업 수를 제한하면서, 사용자가 중간에 취소해도 각 작업의 정리 코드가 실행되는 Python 함수를 만든다. `/app/run.py`에서 정해진 이름과 인자로 불러 쓸 수 있어야 한다. | 0/4 | 1분 23초~3분 28초 | 10회 | `$0.064` |
| [2. `crack-7z-hash`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/crack-7z-hash/instruction.md) | 암호화된 7z 파일 안의 `secret_file.txt`를 열어 그 안의 단어를 찾는다. 찾은 단어를 `/app/solution.txt`에 정확히 쓰면 된다. | 4/4 | 4분 44초~14분 30초 | 112회 | `$1.787` |
| [3. `dna-assembly`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/dna-assembly/instruction.md) | 네 DNA 조각을 Golden Gate 방식으로 조립할 수 있도록 필요한 프라이머를 설계한다. 길이·녹는점·효소 절단 위치 조건을 만족하는 최소 프라이머 쌍을 `primers.fasta`에 써야 한다. | 0/4 | 2분 39초~3분 55초 | 30회 | `$1.117` |
| [4. `modernize-scientific-stack`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/modernize-scientific-stack/instruction.md) | Python 2용 기후 분석 코드를 Python 3에서 실행되도록 새로 작성한다. 두 관측소의 평균 온도를 지정 형식으로 출력하고, 필요한 라이브러리 버전도 파일로 남겨야 한다. | 4/4 | 2분 3초~2분 43초 | 22회 | `$0.256` |
| [5. `sam-cell-seg`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/sam-cell-seg/instruction.md) | 조직 사진의 사각형 세포 표시를 MobileSAM으로 세밀한 외곽선으로 바꾸는 CPU용 스크립트를 만든다. 모든 세포가 겹치지 않는 하나의 연속 외곽선이 되도록 CSV를 갱신해야 한다. | 4/4 | 4분 16초~5분 46초 | 20회 | `$0.613` |
| [6. `torch-tensor-parallelism`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/torch-tensor-parallelism/instruction.md) | PyTorch 선형 계층의 가중치를 여러 프로세스에 열 또는 행 방향으로 나눠 계산하는 두 클래스를 구현한다. 여러 프로세스 수에서 가중치 분할, 출력과 기울기가 기준값과 맞아야 한다. | 0/4 | 6분 5초~10분 32초 | 10회 | `$0.136` |
| [7. `extract-elf`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/extract-elf/instruction.md) | 컴파일된 C 실행 파일에서 메모리 주소와 정수 값을 읽어 JSON으로 내보내는 JavaScript 프로그램을 만든다. 출력한 값은 모두 정확해야 하고 기준 메모리 값의 75% 이상을 찾아야 한다. | 2/4 | 1분 31초~2분 59초 | 19회 | `$0.364` |
| [8. `financial-document-processor`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/financial-document-processor/instruction.md) | JPG와 PDF 문서를 송장과 기타 문서로 나눠 폴더를 옮기고, 송장의 총액과 세금을 추출한다. 파일별 값과 전체 합계를 정해진 CSV 형식으로 만들어야 한다. | 0/4 | 2분 38초~8분 27초 | 43회 | `$1.032` |
| [9. `gcode-to-text`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/gcode-to-text/instruction.md) | 3D 프린터의 G-code를 분석해 출력물 표면에 나타날 글자를 알아낸다. 해독한 문자열을 `/app/out.txt`에 쓰면 된다. | 0/4 | 1분 27초~11분 31초 | 76회 | `$1.587` |
| [10. `install-windows-3.11`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/install-windows-3.11/instruction.md) | QEMU에서 Windows 3.11을 실행하고 VNC와 웹 화면, 키보드 입력용 감시 소켓을 설정한다. 원본 디스크를 바꾸지 않은 채 바탕 화면까지 부팅하고 외부 입력을 받을 수 있어야 한다. | 0/4 | 3분 35초~4분 55초 | 32회 | `$0.476` |
| [11. `kv-store-grpc`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/kv-store-grpc/instruction.md) | 문자열 키에 정수 값을 저장하고 읽는 gRPC 서버를 만든다. 지정된 proto 메시지와 두 RPC를 구현하고 5328번 포트에서 서버를 계속 실행해야 한다. | 4/4 | 1분 32초~2분 57초 | 18회 | `$0.198` |
| [12. `log-summary-date-ranges`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/log-summary-date-ranges/instruction.md) | 날짜별 로그에서 `ERROR`, `WARNING`, `INFO`가 오늘·최근 7일·최근 30일·이번 달·전체에 각각 몇 번 나오는지 센다. 기준일과 행 순서를 지켜 `summary.csv`를 만들어야 한다. | 0/4 | 1분 31초~3분 46초 | 11회 | `$0.160` |
| [13. `llm-inference-batching-scheduler`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/llm-inference-batching-scheduler/instruction.md) | 길이가 다른 모델 요청을 고정 크기 실행 묶음으로 배치하는 계획을 만든다. 모든 요청을 한 번씩 포함하고 형태 수·비용·빈 공간·지연시간 기준을 만족하는 두 JSONL 파일을 출력해야 한다. | 2/4 | 3분 38초~6분 58초 | 38회 | `$1.568` |
| [14. `model-extraction-relu-logits`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/model-extraction-relu-logits/instruction.md) | 입력값을 넣어 결과만 볼 수 있는 한 층 신경망을 여러 번 질의해 첫 번째 가중치 행렬을 복원한다. 뉴런 순서와 비례 배율을 제외하고 같은 행렬을 `.npy` 파일로 저장해야 한다. | 0/4 | 3분 3초~6분 48초 | 18회 | `$0.331` |
| [15. `openssl-selfsigned-cert`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/openssl-selfsigned-cert/instruction.md) | OpenSSL로 정해진 이름·유효기간·권한의 개발용 인증서와 개인키를 만든다. 결합 PEM, 검증 기록과 인증서를 읽어 확인하는 Python 스크립트까지 지정 위치에 있어야 한다. | 4/4 | 4분 10초~4분 13초 | 9회 | `$0.100` |
| [16. `overfull-hbox`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/overfull-hbox/instruction.md) | LaTeX 문서가 줄 너비 초과 경고 없이 빌드되도록 허용된 동의어만 골라 바꾼다. 다른 파일을 수정하지 않고 `pdflatex` 컴파일을 성공시켜야 한다. | 1/4 | 4분 14초~7분 22초 | 33회 | `$0.699` |
| [17. `prove-plus-comm`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/prove-plus-comm/instruction.md) | Coq 파일의 덧셈 교환법칙 증명에서 빠진 단계를 채운다. 완성한 증명이 `coqc`로 컴파일돼 `.vo` 파일이 만들어져야 한다. | 4/4 | 1분 42초~5분 33초 | 18회 | `$0.120` |
| [18. `raman-fitting`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/raman-fitting/instruction.md) | 그래핀 Raman 스펙트럼의 G와 2D 봉우리를 맞추고 위치·폭·크기·기준값을 구한다. 네 값을 지정된 구조의 `/app/results.json`에 저장해야 한다. | 0/4 | 2분 17초~6분 48초 | 37회 | `$0.619` |
| [19. `sqlite-with-gcov`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/sqlite-with-gcov/instruction.md) | 저장소에 포함된 SQLite 소스를 코드 실행 범위 측정 기능과 함께 컴파일한다. 완성한 `sqlite` 실행 파일을 어디서나 호출할 수 있도록 PATH에 둬야 한다. | 3/4 | 3분 47초~7분 55초 | 33회 | `$0.642` |
| [20. `vulnerable-secret`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/vulnerable-secret/instruction.md) | 실행 파일을 분석하거나 상호작용해 `FLAG{...}` 형식의 비밀 값을 찾는다. 찾은 값을 `/app/results.txt`에 정확히 저장하면 된다. | 4/4 | 1분 33초~4분 46초 | 22회 | `$0.350` |
| [21. `video-processing`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/video-processing/instruction.md) | 허들 경기 영상을 분석해 선수가 점프를 시작한 프레임과 착지한 프레임을 찾는 스크립트를 만든다. 두 프레임 번호를 정해진 TOML 필드로 출력해야 한다. | 0/4 | 3분 8초~5분 40초 | 29회 | `$0.956` |
| [22. `chess-best-move`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/chess-best-move/instruction.md) | 체스판 그림을 읽고 백이 둘 수 있는 최선의 수를 찾는다. 시작 칸과 도착 칸 형식으로 기록하고, 이기는 수가 여러 개면 모두 한 줄씩 써야 한다. | 0/4 | 2분 51초~9분 37초 | 38회 | `$0.610` |
| [23. `schemelike-metacircular-eval`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/schemelike-metacircular-eval/instruction.md) | Scheme과 비슷한 언어를 실행하는 해석기를 그 언어 자체로 작성한다. 제공된 프로그램뿐 아니라 해석기 자신도 다시 해석할 수 있어야 한다. | 0/4 | 11분 32초~27분 20초 | 113회 | `$3.023` |
| [24. `build-pov-ray`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/build-pov-ray/instruction.md) | 오래된 POV-Ray 2.2 소스를 받아 빌드하고 지정 경로에 설치한다. 제공된 장면을 실행해 기준 이미지와 맞는 결과를 렌더링할 수 있어야 한다. | 1/4 | 9분 40초~23분 2초 | 77회 | `$2.290` |
| [25. `dna-insert`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/dna-insert/instruction.md) | 원형 DNA를 원하는 결과로 바꾸는 Q5 돌연변이 유도 프라이머를 설계한다. 길이와 녹는점 조건을 만족하는 최소 프라이머 쌍을 `primers.fasta`에 써야 한다. | 0/4 | 2분 15초~28분 46초 | 118회 | `$1.993` |
| [26. `feal-differential-cryptanalysis`](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/tasks/feal-differential-cryptanalysis/instruction.md) | FEAL 계열 암호 함수에 선택한 입력을 넣어 보며 여섯 번째 라운드 키를 복구하는 공격을 구현한다. `attack.py`가 30초 안에 정확한 `key[5]` 정수를 반환해야 한다. | 3/4 | 4분 34초~8분 11초 | 41회 | `$1.242` |

## 출처와 한계

- 과제 설명과 공개 통과 대상:
  [Terminal-Bench 2.1 공식 과제](https://github.com/harbor-framework/terminal-bench-2-1/tree/7131e4375048a0e408a8fb404b5f499d726b695b/tasks)
- 조건별 품질·요청·시간·비용:
  [예비 비교 기술 증거](../preliminary-comparison-20260916.md)
- 이 26과제는 목적·후보 중심으로 선택한 예비 표본이며 전체 89과제를 대표하는
  무작위 표본이 아니다.
- 공개 지시문을 쉽게 풀어 썼지만, 과제 내장 채점기의 모든 세부 검사를 새 문서에
  다시 구현하거나 독립 검증한 것은 아니다.
