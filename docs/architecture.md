# 아키텍처 (AWS 전체 흐름)

엣지 1차 판단(YOLO) + 클라우드 2차 분석(Foundation Model) + 검수자 대시보드 구조의 MVP입니다.
전 리소스 리전은 **서울(`ap-northeast-2`)** 로 통일합니다.

## 전체 흐름

```text
YOLO Simulator
 ├─ 1) 로컬 YOLO 추론(edge-yolo/simulator.py)
 │     └─ DAMAGE_SUSPECTED 인 경우만 클라우드 전송
 │
 ├─ 2) POST /inspection-events ──> API Gateway ──> inspection-event-ingest
 │                                                       ├─ DynamoDB PutItem(PENDING)
 │                                                       └─ S3 presigned upload URL 반환
 │
 └─ 3) PUT image bytes ────────────────────────────────> S3 raw-images/{event_id}.jpg
                                                           │
                                                           ▼
                                                 container-damage-analyzer
                                                           │
                                                           ├─ S3 이미지 다운로드
                                                           ├─ Bedrock Foundation Model 분석
                                                           ├─ Risk Score 계산
                                                           └─ DynamoDB UpdateItem

Next.js Dashboard
 └─ GET/POST /inspections ──> API Gateway ──> dashboard_api ──> DynamoDB/S3

DynamoDB Stream(review_status=DONE)
 └─ report_generator ──> Bedrock 보고서 초안 ──> PDF ──> S3 reports/
```

## 중요한 설계 원칙

사진 파일은 API Gateway를 거치지 않습니다.

| 데이터 | 이동 경로 | 이유 |
|---|---|---|
| 이벤트 메타데이터, YOLO bbox/confidence | API Gateway → ingest Lambda | 작은 JSON, 인증/검증/DB 생성 처리 |
| 원본 이미지 파일 | Simulator → S3 presigned URL | 대용량 파일은 S3 직접 업로드가 비용/속도/제한 면에서 적합 |

## Edge Simulator

로컬 시뮬레이터는 `edge-yolo/`에 구현되어 있습니다.

| 파일 | 역할 |
|---|---|
| `edge-yolo/simulator.py` | 입력 이미지 순회, 이벤트 ID 생성, dry-run/실제 전송 실행 |
| `edge-yolo/infer.py` | Ultralytics YOLO 추론 래퍼, `NORMAL`/`DAMAGE_SUSPECTED` 판정 |
| `edge-yolo/ingest_client.py` | `POST /inspection-events` 호출 |
| `edge-yolo/upload_to_s3.py` | bbox 렌더링 및 presigned URL S3 PUT |
| `edge-yolo/config.py` | `.env`/환경변수 기반 실행 설정 |

기본 이벤트 ID는 같은 날 재실행 충돌을 줄이기 위해 `EVT-YYYYMMDD-HHMMSS-0001` 형식을 사용합니다.
2026-07-16 실제 연동 테스트에서 ingest API `201`, S3 PUT `200`, dashboard API 조회를 확인했습니다.
시연용 손상 감지 모델은 `edge-yolo/weights/stage1_best.pt` 또는 `EDGE_MODEL_PATH`로 지정합니다.

## API Gateway

API Gateway는 하나를 사용합니다. route에 따라 Lambda integration만 다릅니다.

| Method | Path | Lambda | 역할 |
|---|---|---|---|
| POST | `/inspection-events` | `inspection-event-ingest` | 이벤트 접수, PENDING item 생성, upload URL 발급 |
| GET | `/inspections` | `dashboard_api` | 검수 목록 조회 |
| GET | `/inspections/{event_id}` | `dashboard_api` | 단건 상세 조회 |
| POST | `/inspections/{event_id}/review` | `dashboard_api` | 승인/수정/반려 처리 |
| GET | `/inspections/{event_id}/report` | `dashboard_api` | 보고서 상태/URL 조회 |

## Lambda 역할

| Lambda | 트리거 | 책임 | 상태 |
|---|---|---|---|
| `inspection-event-ingest` | API Gateway `POST /inspection-events` | DynamoDB PENDING item 생성, S3 presigned URL 발급 | 구현 완료 |
| `container-damage-analyzer` | S3 `ObjectCreated` (`raw-images/`) | Bedrock 분석, risk 계산, DynamoDB 업데이트 | 구현 완료 |
| `dashboard_api` | API Gateway `/inspections*` | 대시보드 조회/검수/삭제/Presigned read URL | 구현 완료 |
| `report_generator` | DynamoDB Streams 또는 직접 호출 | PDF 리포트 생성 및 S3 저장 | 구현 완료 |

## DynamoDB 상태 흐름

```text
PENDING_CLOUD_ANALYSIS
  → MANUAL_NEEDED      # 위험도와 무관, 전부 수동 검수
  → INFERENCE_FAILED   # 분석 실패 시
  → INFERENCE_FAILED   # Bedrock/S3/분석 실패
  → DONE               # 검수 승인/수정 완료
  → 삭제               # 검수 반려(reject)
```

보고서 상태는 `report.report_status`로 관리합니다.

```text
NOT_CREATED → PENDING → CREATED
                         └→ FAILED
```

## 비동기 이벤트

API Gateway를 거치지 않는 내부 자동화입니다.

```text
S3 ObjectCreated(raw-images/) → container-damage-analyzer
DynamoDB Stream(DONE)        → report_generator
```

## 안전장치

- `container-damage-analyzer`는 `attribute_exists(event_id)` 조건으로 기존 item만 업데이트합니다.
- 분석 전 `review_status=PENDING_CLOUD_ANALYSIS` 및 `cloud_analysis.analysis_status=PENDING`인지 확인합니다.
- S3 이벤트 중복 전달 시 이미 처리된 item은 skip합니다.
- `inspection-event-ingest` 구현 시 `PutItem`에 `ConditionExpression="attribute_not_exists(event_id)"`를 넣어야 합니다.
- 분석 결과 이미지를 `raw-images/`에 다시 저장하지 않습니다.
