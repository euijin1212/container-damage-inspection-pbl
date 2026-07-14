# 아키텍처 (AWS 전체 흐름)

3계층 구조 · 엣지 1차 판단(YOLO) + 클라우드 재분석(Foundation Model).
전 리소스 리전은 **서울(`ap-northeast-2`)** 로 통일한다.

## 전체 흐름

```text
[Layer 1] 로컬 엣지 (edge-yolo/)
    - YOLO로 컨테이너 이미지 1차 추론 (bbox, confidence)
    - 파손 의심(DAMAGE_SUSPECTED) 이미지를 S3(container-damage)로 업로드
    - (선택) 엣지 결과 JSON을 edge-results/ 로 함께 업로드
        │
        ▼  S3 ObjectCreated 이벤트
[Layer 2] 클라우드 분석 (lambda/container-damage-analyzer + src/)
    - S3 이벤트로 Lambda 자동 트리거
    - src/s3_client   : 방금 올라온 이미지 다운로드
    - src/bedrock_analyzer : Sonnet 4.5로 손상 유형(hole/dent/rust)·정도(low/med/high) 판정
    - src/risk_score  : Risk Score 계산 (구멍 ≥ 찌그러짐 > 녹슴)
    - DynamoDB(container-inspection)에 검수 결과 저장
    - 고위험(HIGH) → SNS 알림
    - CloudWatch에 처리 로그
        │
        ▼
[Layer 3] 관리자 서비스 (dashboard/, lambda/dashboard_api, lambda/report_generator)
    - 대시보드: 검수 큐 조회 · 승인/수정/반려 (dashboard_api)  ※ 예정
    - Bedrock 일일 리포트 자동 생성 (report_generator)         ※ 예정
```

## 구성요소별 책임

| 계층 | 위치 | 책임 | 상태 |
|---|---|---|---|
| 엣지 YOLO | `edge-yolo/` | 1차 파손 판단, S3 업로드 | 예정(플레이스홀더) |
| 분석 Lambda | `lambda/container-damage-analyzer/` | FM 재분석 + Risk Score + 저장 | **구현 완료** |
| 공유 로직 | `src/` | 분석기·스코어·S3·설정 | **구현 완료** |
| 대시보드 API | `lambda/dashboard_api/` | 검수 큐/승인 처리 | 예정 |
| 리포트 | `lambda/report_generator/` | Bedrock 일일 리포트 | 예정 |

## 사용 AWS 서비스

| 서비스 | 용도 |
|---|---|
| S3 | 이미지 업로드 버킷 `container-damage` (Lambda 트리거 소스) |
| Lambda | 분석/대시보드 API/리포트 |
| Bedrock | Claude Sonnet 4.5 손상 재분석 |
| DynamoDB | 검수 결과 저장 `container-inspection` |
| SNS | 고위험 알림 |
| CloudWatch | Lambda 로그·모니터링 |
| API Gateway | 대시보드 API 프론트 (예정) |

## 주의사항

- **무한 루프 방지:** 분석 결과 이미지를 트리거 버킷(`container-damage`)에 되쓰지 말 것.
  결과물은 별도 버킷 또는 트리거 제외 접두사에 저장.
- **분석 Lambda 설정:** 타임아웃 **90초 이상**, 메모리 **512MB 이상** (Bedrock 응답 대기).
- **Bedrock 모델 ID:** 서울 리전은 추론 프로파일 필요 —
  `apac.anthropic.claude-sonnet-4-5-20250929-v1:0` (또는 `global.` 접두사).
