# 데이터 스키마 (JSON 필드 통일)

세 계층(엣지 YOLO / 클라우드 FM / DynamoDB)이 공유하는 필드 계약.
실제 샘플은 [../mock-data/](../mock-data/), 리소스 명세는 [../infra/aws-resources.md](../infra/aws-resources.md) 참조.

## DynamoDB 테이블: `container-inspection`

- **Partition Key:** `event_id` (String)
- **Sort Key:** `processed_at` (String, ISO 8601)
- 날짜별 조회가 필요하면 GSI `event_date` 추가 권장
- 과금: 온디맨드(PAY_PER_REQUEST) 권장

## 최종 저장 item 필드

`lambda/container-damage-analyzer` 가 저장하는 필드 (숫자는 DynamoDB용 Decimal 로 변환).

| 필드 | 생성 | 타입 | 설명 |
|---|---|---|---|
| `event_id` | Lambda | S | **[PK]** 이벤트 고유 ID (`evt_...`) |
| `processed_at` | Lambda | S | **[SK]** 클라우드 처리 완료 시각 |
| `event_date` | Lambda | S | `YYYY-MM-DD` |
| `captured_at` | 엣지 | S | 촬영 시각 |
| `container_id` | 엣지 | S | 컨테이너 번호 |
| `inspection_result` | 클라우드 | S | `normal` \| `damage` |
| `confidence` | 클라우드 | N | 대표 탐지 신뢰도 |
| `detection_count` | 클라우드 | N | 손상 개수 |
| `detections` | 클라우드 | L | 손상별 `{class, severity, confidence, location, note}` |
| `location` | 클라우드 | S | 대표 손상 위치 |
| `risk_score` | 클라우드 | N | 0~100 위험 점수 |
| `risk_level` | Lambda | S | `HIGH` \| `MEDIUM` \| `LOW` |
| `risk_breakdown` | 클라우드 | L | 손상별 점수 기여도 상세 |
| `image_path` | Lambda | S | S3 이미지 경로 |
| `image_type` | Lambda | S | `raw`(정상) \| `annotated`(손상) |
| `model_version` | 클라우드 | S | 추론 모델 ID |
| `review_status` | Lambda | S | `PENDING` \| `AUTO_OK` \| `MANUAL_NEEDED` \| `DONE` |
| `notified` | Lambda | BOOL | SNS 중복 발송 방지 |

## 표준값

- `class`(손상 유형): `hole`(구멍), `dent`(찌그러짐), `rust`(녹슴)
- `severity`(손상 정도): `low`(경미), `medium`(중간), `high`(심각)
- `inspection_result`: `normal`(정상), `damage`(손상)

## Risk Score 규칙

- 유형 가중치: `hole` 1.0 ≥ `dent` 0.7 > `rust` 0.35
- 정도 계수: `low` 0.3 / `medium` 0.6 / `high` 1.0
- 단일 손상 점수 = 유형가중치 × 정도계수 × 신뢰도 × 100
- 다중 손상 = 가장 위험한 손상 100% + 나머지 감쇠(×0.4) 누적, 최대 100
- 등급: `HIGH ≥ 66`, `MEDIUM ≥ 33`, 그 외 `LOW`

## 저장 item 예시

```json
{
  "event_id": "evt_3f9a12c4b8e1",
  "processed_at": "2026-07-13T02:35:26Z",
  "event_date": "2026-07-13",
  "inspection_result": "damage",
  "detection_count": 2,
  "detections": [
    { "class": "hole", "severity": "high", "confidence": 0.88, "location": "하-우" },
    { "class": "dent", "severity": "medium", "confidence": 0.64, "location": "중-좌" }
  ],
  "risk_score": 90.5,
  "risk_level": "HIGH",
  "image_path": "s3://container-damage/MSKU7654321.jpg",
  "image_type": "annotated",
  "model_version": "apac.anthropic.claude-sonnet-4-5-20250929-v1:0",
  "review_status": "MANUAL_NEEDED",
  "notified": true
}
```

> **참고:** 엣지(YOLO) 단계의 `edge_status`, `upload_reason`, `edge_confidence` 등
> 메타데이터 필드 정의는 루트 [README.md](../README.md) 5·6장을 따른다.
