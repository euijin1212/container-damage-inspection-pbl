# 데이터 스키마 (MVP)

Container Damage Inspection MVP의 DynamoDB item 구조 정의 문서입니다.
포트폴리오용 MVP 단계이므로 **당장 구현에 필요한 최소 필드만** 유지합니다.

실제 샘플 JSON은 [../mock-data/](../mock-data/), 리소스 명세는 [aws-resources.md](../infra/aws-resources.md) 참조.

---

## 1. 색상 범례 (필드 생성 주체)

| 색 | 생성 주체 | 설명 |
|---|---|---|
| 🟦 | Simulator | 기본 이벤트 정보 생성 |
| 🟩 | YOLO 모델 | Simulator 내부에서 실행되는 추론 결과 |
| 🟧 | Lambda + Foundation Model | 클라우드 분석 결과 |
| 🟥 | Lambda | 위험도 계산 / 상태값 |

---

## 2. 최종 데이터 흐름

```text
Simulator
  → DynamoDB PutItem(PENDING)
  → S3 PutObject(raw image)
  → Lambda (S3 raw-images/ 트리거)
  → Foundation Model 분석
  → DynamoDB UpdateItem (핀셋 업데이트)
  → Dashboard
```

- Simulator가 기본 이벤트 정보를 생성하고, 내부에서 YOLO 모델을 실행한다.
- YOLO가 파손 여부, bbox, confidence를 생성한다.
- YOLO가 `DAMAGE_SUSPECTED`로 판단한 경우에만 DynamoDB에 PENDING item을 먼저 저장한다.
- 이후 S3 `raw-images/{event_id}.jpg`에 원본 이미지만 업로드한다.
- S3 업로드 이벤트로 Lambda가 실행되고, S3 key에서 `event_id`를 추출한다.
- Lambda는 Foundation Model 분석 후 기존 item을 `UpdateItem`으로 핀셋 업데이트한다.

---

## 3. DynamoDB 테이블

| 항목 | 값 |
|---|---|
| 테이블명 | `InspectionEventTable` |
| Partition Key | `event_id` (String) |
| Sort Key | 없음 |
| 과금 | 온디맨드(PAY_PER_REQUEST) 권장 |

---

## 4. 🟦 Simulator가 생성하는 기본 데이터

| 필드 | 타입 | 설명 |
|---|---|---|
| `event_id` | S | 이벤트 고유 ID (예: `EVT-20260713-0001`) |
| `event_date` | S | 이벤트 발생 일자 (`YYYY-MM-DD`) |
| `captured_at` | S | 촬영 시각 (ISO 8601) |
| `container.container_id` | S | 컨테이너 번호 |
| `source.gate_id` | S | 게이트 ID |
| `source.camera_id` | S | 카메라 ID |
| `image.bucket` | S | S3 버킷명 (`container-damage`) |
| `image.raw_image_key` | S | 원본 이미지 key (`raw-images/{event_id}.jpg`) |

> 이미지 파일명은 `event_id`와 동일하게 맞춘다. 예: `raw-images/EVT-20260713-0001.jpg`

---

## 5. 🟩 YOLO가 추가하는 데이터

`bbox`와 `confidence`는 Simulator가 직접 만드는 값이 아니라,
**Simulator 내부에서 실행되는 YOLO 모델의 추론 결과**다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `edge.edge_status` | S | `NORMAL` \| `DAMAGE_SUSPECTED` |
| `edge.edge_model` | S | 추론 모델명 (예: `YOLOv8`) |
| `edge.edge_confidence` | N | 대표 탐지 신뢰도 |
| `edge.edge_detections[].damage_class` | S | 탐지된 손상 클래스 |
| `edge.edge_detections[].confidence` | N | 개별 탐지 신뢰도 |
| `edge.edge_detections[].bbox` | M | `{x_min, y_min, x_max, y_max}` |

---

## 6. 🟧🟥 Lambda가 업데이트하는 데이터

Lambda는 기존 item 전체를 덮어쓰지 않고, 아래 필드만 `UpdateItem`으로 핀셋 업데이트한다.

| 필드 | 색 | 타입 | 설명 |
|---|---|---|---|
| `processed_at` | 🟧 | S | 클라우드 처리 완료 시각 |
| `cloud_analysis.analysis_status` | 🟧 | S | `PENDING` \| `COMPLETED` \| `FAILED` |
| `cloud_analysis.model_name` | 🟧 | S | 사용한 Foundation Model 이름 |
| `cloud_analysis.inspection_result` | 🟧 | S | 최종 검사 결과 (예: `damage`) |
| `cloud_analysis.confidence` | 🟧 | N | 대표 신뢰도 |
| `cloud_analysis.detection_count` | 🟧 | N | 손상 개수 |
| `cloud_analysis.detections[].damage_class` | 🟧 | S | 손상 유형 |
| `cloud_analysis.detections[].severity` | 🟧 | S | 손상 정도 |
| `cloud_analysis.detections[].location` | 🟧 | S | 손상 위치 |
| `cloud_analysis.detections[].description` | 🟧 | S | 손상 설명 |
| `risk.risk_score` | 🟥 | N | 0~100 위험 점수 |
| `risk.risk_level` | 🟥 | S | `HIGH` \| `MEDIUM` \| `LOW` |
| `review_status` | 🟥 | S | 검수 상태값 (아래 참조) |

> 실패 시에는 `cloud_analysis`에 `analysis_status: FAILED`와 `error_message`만 담고,
> `risk`는 `null`, `review_status`는 `INFERENCE_FAILED`로 업데이트한다.

---

## 7. 최소 PENDING item 구조 요약

Simulator가 YOLO 결과가 `DAMAGE_SUSPECTED`인 경우, S3 이미지 업로드 전에 아래 구조로 PutItem 한다.

```json
{
  "event_id": "EVT-20260713-0001",
  "event_date": "2026-07-13",
  "captured_at": "2026-07-13T11:30:00Z",
  "container": { "container_id": "MSCU1234567" },
  "source": { "gate_id": "GATE-01", "camera_id": "CAM-01" },
  "image": {
    "bucket": "container-damage",
    "raw_image_key": "raw-images/EVT-20260713-0001.jpg"
  },
  "edge": {
    "edge_status": "DAMAGE_SUSPECTED",
    "edge_model": "YOLOv8",
    "edge_confidence": 0.82,
    "edge_detections": [
      {
        "damage_class": "damage",
        "confidence": 0.82,
        "bbox": { "x_min": 412, "y_min": 288, "x_max": 580, "y_max": 411 }
      }
    ]
  },
  "cloud_analysis": { "analysis_status": "PENDING" },
  "risk": { "risk_score": null, "risk_level": null },
  "review_status": "PENDING_CLOUD_ANALYSIS"
}
```

전체 예시는 [../mock-data/sample_pending_item.json](../mock-data/sample_pending_item.json) 참조.

---

## 8. Lambda 핀셋 업데이트 필드

`UpdateItem` 대상 최상위 필드는 다음 4개뿐이다.

- `processed_at`
- `cloud_analysis`
- `risk`
- `review_status`

성공/실패 예시는 아래 mock-data 참조.

---

## 9. 상태값 정리

### `edge.edge_status`

| 값 | 의미 |
|---|---|
| `NORMAL` | YOLO가 정상으로 판단 |
| `DAMAGE_SUSPECTED` | YOLO가 파손 의심으로 판단 |

### `cloud_analysis.analysis_status`

| 값 | 의미 |
|---|---|
| `PENDING` | 클라우드 분석 대기 |
| `COMPLETED` | 클라우드 분석 완료 |
| `FAILED` | 클라우드 분석 실패 |

### `review_status`

| 값 | 의미 |
|---|---|
| `PENDING_CLOUD_ANALYSIS` | 클라우드 분석 대기 (PutItem 직후) |
| `MANUAL_NEEDED` | 검수자 확인 필요 → 검수 큐 표시 |
| `AUTO_OK` | 자동 통과 → 기본 검수 큐 미표시 |
| `INFERENCE_FAILED` | 분석 실패 → 실패/관리자 확인 큐 표시 |
| `DONE` | 검수 완료 |

### 위험도 → review_status 매핑

| risk_level | review_status |
|---|---|
| `HIGH` 또는 `MEDIUM` | `MANUAL_NEEDED` |
| `LOW` | `AUTO_OK` |

### Dashboard 표시 기준

- `MANUAL_NEEDED` → 검수 큐 표시
- `AUTO_OK` → 기본 검수 큐 미표시
- `INFERENCE_FAILED` → 실패 큐 또는 관리자 확인 큐 표시

---

## 10. 표준값

- `damage_class`(손상 유형): `hole`(구멍), `dent`(찌그러짐), `rust`(녹슴)
- `severity`(손상 정도): `low`(경미), `medium`(중간), `high`(심각)
- `inspection_result`: `normal`(정상), `damage`(손상)

---

## 11. mock-data 파일

| 파일 | 설명 |
|---|---|
| [sample_pending_item.json](../mock-data/sample_pending_item.json) | Simulator가 PutItem 하는 최소 PENDING item |
| [sample_completed_update.json](../mock-data/sample_completed_update.json) | Lambda 성공 시 UpdateItem 필드 |
| [sample_failed_update.json](../mock-data/sample_failed_update.json) | Lambda 실패 시 UpdateItem 필드 |
