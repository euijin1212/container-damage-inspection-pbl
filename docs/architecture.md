# 아키텍처 (AWS 전체 흐름)

엣지 1차 판단(YOLO) + 클라우드 재분석(Foundation Model) 구조의 MVP.
전 리소스 리전은 **서울(`ap-northeast-2`)** 로 통일한다.

## 최종 흐름 한 줄

```text
Simulator → DynamoDB PutItem(PENDING) → S3 PutObject(raw image)
  → Lambda → Foundation Model → DynamoDB UpdateItem → Dashboard
```

## 전체 흐름

```text
[Layer 1] Simulator + 엣지 YOLO (edge-yolo/)
    - Simulator가 기본 이벤트 정보 생성 (event_id, container, source, image 등)
    - Simulator 내부에서 YOLO 모델 실행 → 파손 여부, bbox, confidence 생성
    - DAMAGE_SUSPECTED인 경우에만:
        1) DynamoDB(InspectionEventTable)에 PENDING item을 먼저 PutItem
        2) S3(container-damage)의 raw-images/{event_id}.jpg 에 원본 이미지만 업로드
        │
        ▼  S3 ObjectCreated 이벤트 (prefix raw-images/)
[Layer 2] 클라우드 분석 (lambda/container-damage-analyzer + src/)
    - S3 이벤트로 Lambda 자동 트리거
    - S3 key에서 event_id 추출 (새로 생성하지 않음)
    - src/s3_client        : 방금 올라온 이미지 다운로드
    - src/bedrock_analyzer : Sonnet 4.5로 손상 유형(hole/dent/rust)·정도(low/med/high) 판정
    - src/risk_score       : Risk Score 계산 (구멍 ≥ 찌그러짐 > 녹슴)
    - DynamoDB(InspectionEventTable) 기존 item을 UpdateItem으로 핀셋 업데이트
      (processed_at, cloud_analysis, risk, review_status)
    - 고위험(HIGH) → SNS 알림
    - CloudWatch에 처리 로그
        │
        ▼
[Layer 3] 관리자 서비스 (dashboard/, lambda/dashboard_api, lambda/report_generator)
    - 대시보드: review_status = MANUAL_NEEDED 인 item만 검수 큐 표시 (dashboard_api)  ※ 예정
    - Bedrock 일일 리포트 자동 생성 (report_generator)                              ※ 예정
```

## 구성요소별 책임

| 계층 | 위치 | 책임 | 상태 |
|---|---|---|---|
| Simulator + YOLO | `edge-yolo/` | 이벤트 생성, YOLO 추론, PutItem(PENDING), 이미지 업로드 | 예정(플레이스홀더) |
| 분석 Lambda | `lambda/container-damage-analyzer/` | FM 재분석 + Risk Score + UpdateItem | **구현 완료** |
| 공유 로직 | `src/` | 분석기·스코어·S3·설정 | **구현 완료** |
| 대시보드 API | `lambda/dashboard_api/` | 검수 큐/승인 처리 | 예정 |
| 리포트 | `lambda/report_generator/` | Bedrock 일일 리포트 | 예정 |

## 사용 AWS 서비스

| 서비스 | 용도 |
|---|---|
| S3 | 원본 이미지 버킷 `container-damage` (`raw-images/`, Lambda 트리거 소스) |
| Lambda | 분석/대시보드 API/리포트 |
| Bedrock | Claude Sonnet 4.5 손상 재분석 |
| DynamoDB | 이벤트 상태·분석 결과 저장 `InspectionEventTable` |
| SNS | 고위험 알림 |
| CloudWatch | Lambda 로그·모니터링 |
| API Gateway | 대시보드 API 프론트 (예정) |

## 주의사항

- **S3에는 원본 이미지만 저장한다.** S3 metadata와 edge-results JSON은 MVP에서 사용하지 않는다.
- **무한 루프 방지:** 분석 결과 이미지를 트리거 접두사(`raw-images/`)에 되쓰지 말 것.
  결과물은 별도 버킷 또는 트리거 제외 접두사(`annotated-images/` 등)에 저장.
- **분석 Lambda 설정:** 타임아웃 **90초 이상**, 메모리 **512MB 이상** (Bedrock 응답 대기).
- **Bedrock 모델 ID:** 서울 리전은 추론 프로파일 필요 —
  `apac.anthropic.claude-sonnet-4-5-20250929-v1:0` (또는 `global.` 접두사).
