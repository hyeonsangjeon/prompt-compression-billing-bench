# 실험 기록

이 디렉터리는 실험 설계, 측정 요약, 열린 판단의 공개 원본이다. Project 15는 상태와 다음 행동만 표시하고, 근거는 이 문서들에서 관리한다.

## 현재 상태

| 증거 | 현재 상태 | 표본·분모 | 성격 |
| --- | --- | --- | --- |
| 추가 압축 없는 기준선 | 2026-09-14 UTC에 20회 완료. 사전 규칙에 따라 판정 불가로 중단 | 목적 선정 5과제 × 20회 = 100 native trial | 비공개 원본에서 집계한 측정·계산 |
| 세 압축기의 정적 적용 | squeez·Headroom·LLMLingua-2의 입력 크기와 변환 표본 확인 | 과거 15실행의 저장 요청 56개, 후보 107출현·27고유 입력 | 정적 측정·계산·분류 판단 |
| native 압축 비교 | 미실행 | 0회·0 trial | 미측정 |
| 전체 모집단 선별·평가 재설계 | 20개 유효 결과 중 18회 통과, D1 진단과 F1-R1 채택. 전체 적격 `K`개를 일정 gate 안에서 평가. 성공 기준·비용 분석 경로·`rho_quality`·`rho_cost` 범위·`R(K, rho)` 공식·행렬 승인 전 | Terminal-Bench 2.1 89과제, 실행 0회 | 설계안 |
| nginx verifier revision | 기존 diff와 source·effective SHA, fixture 3/3을 2026-09-14 UTC에 재검증. 해당 바이트 범위만 조건부 승인 | 원본·수정본 1개씩, test module 6/6 | 구현·정적 확인·조건부 승인 |

기준선이 판정 불가이므로 압축 조건의 품질·청구 토큰·비용 효과는 아직 측정하지 않았다.

## 문서

- [실험 규약](protocol.md): 고정 조건, 지표, 중단 규칙, 실행 순서
- [평가 과제 선별 규약](screening-protocol.md): 전체 89과제 모집단, 18/20 적격 기준, D1·F1-R1과 nginx verifier 수정
- [압축 평가 규약](evaluation-protocol.md): 네 조건 행렬, 성공 기준·비용 기대값 선택지, 품질·비용 차이값 상관과 `R(K, rho)` 공식 후보, 일정 gate
- [재현 계약](reproducibility-contract.md): F1-R1 attempt, trial 증거, workspace replay와 중복 집계 방지
- [기준선](baseline.md): 추가 압축 없는 20회 결과와 해석 한계
- [압축기 정적 측정](compressors.md): 세 개입의 정적 크기, 변환 표본, 분모
- [판단 기록](decisions.md): 열린 판단 세 건과 결정 이력
- [벤치마크 EDA](../eda/README.md): 두 벤치마크와 입력 구성
- [native 실행 계약](../native-contract.md): 실행기, 보호, 회수, 판정기의 상세 계약

## 갱신 원칙

작업이 끝날 때마다 현재 상태, 새 측정, 열린 판단을 이 디렉터리에 먼저 반영한다. Project 카드에는 상태, 다음 행동, 해당 문서 링크만 둔다.
