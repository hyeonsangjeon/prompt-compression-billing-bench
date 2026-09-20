# 실행 원장

- [`static.toml`](static.toml)은 고정 입력 정적 측정의 원장이다.
- [`demo.toml`](demo.toml)은 합성 자료로 계약을 확인하는 예제 원장이다.
- [`native.template.toml`](native.template.toml)은 실제 모델 실행 전 채워야 하는
  native 원장 템플릿이다.
- [`screening.template.toml`](screening.template.toml)은 Terminal-Bench 2.1
  선별 규칙과 중단·비용 기록 필드를 고정한다.
- [`recovery.template.toml`](recovery.template.toml)은 외부 노출을 끈 상태로
  로컬 squeez 원문 회수·수명·인증 경계를 고정한 비운영 템플릿이다.
- [`accountless-native.json`](accountless-native.json)은 공개 GSM8K 한 항목,
  로컬 전용 Qwen2.5 0.5B 자산·런타임 지문, 생성 설정, 300초 attempt,
  120초 no-progress, retry 0을 고정한 cached quickstart 원장이다. 기존
  Ollama 원장과 별개이며 모델 다운로드나 패키지 설치를 승인하지 않는다.

템플릿에는 자격 증명 값 대신 환경 변수 이름만 기록한다.
