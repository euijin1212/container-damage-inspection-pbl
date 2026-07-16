# Container Damage Inspection PBL

컨테이너 게이트 반출입 시 촬영된 이미지에서 YOLO가 1차로 파손 의심 건을 선별하고,
AWS 서버리스 파이프라인이 Foundation Model로 2차 분석한 뒤 검수자가 확인할 대상을
대시보드에 표시하는 MVP 프로젝트입니다.

> 포트폴리오용 MVP입니다. 사진 파일은 API Gateway를 거치지 않고 S3 presigned URL로 직접 업로드하며, API Gateway는 메타데이터와 대시보드 요청만 처리합니다.

---

## 1. 최종 흐름

```text
YOLO Simulator
  → POST /inspection-events (metadata only)
  → API Gateway
  → inspection-event-ingest Lambda
  → DynamoDB PutItem(PENDING)
  → S3 presigned upload URL 반환
  → Simulator가 S3 raw-images/{event_id}.jpg 직접 업로드
  → S3 ObjectCreated trigger
  → container-damage-analyzer Lambda
  → Bedrock Foundation Model
  → DynamoDB UpdateItem
  → Next.js Dashboard
```

사진 업로드와 API 호출은 분리합니다.

```text
메타데이터 / YOLO 결과 JSON → API Gateway
원본 이미지 파일             → S3 presigned URL
```

---

## 2. 구성요소 역할

| 구성요소 | 역할 |
|---|---|
| YOLO Simulator | 파손 의심 판단, bbox/confidence 생성, ingest API 호출, presigned URL로 이미지 업로드 |
| API Gateway | 외부 요청 단일 진입점 |
| `inspection-event-ingest` Lambda | PENDING item 생성, S3 upload URL 발급 |
| S3 | 원본 이미지 저장 (`raw-images/`) 및 analyzer Lambda 트리거 |
| `container-damage-analyzer` Lambda | S3 key에서 `event_id` 추출, Bedrock 분석, risk 계산, DynamoDB 업데이트 |
| `dashboard_api` Lambda | 대시보드 목록/상세/검수 처리/보고서 URL API |
| `report_generator` Lambda | 검수 완료 후 PDF 리포트 생성 |
| DynamoDB | 이벤트 상태와 분석 결과 저장 (`InspectionEventTable`) |
| Dashboard | 검수 큐, 상세 이미지, 승인/반려, 보고서 상태 표시 |

---

## 3. API Gateway Routes

API Gateway는 하나를 사용하고, route별로 Lambda를 나눕니다.

```text
POST /inspection-events
  → inspection-event-ingest

GET /inspections
GET /inspections/{event_id}
POST /inspections/{event_id}/review
GET /inspections/{event_id}/report
  → dashboard_api
```

S3 trigger와 DynamoDB Stream은 API Gateway를 거치지 않는 내부 이벤트입니다.

```text
S3 raw-images/* ObjectCreated → container-damage-analyzer
DynamoDB Stream(DONE)         → report_generator
```

---

## 4. 폴더 구조

```text
container-damage-inspection-pbl/
├─ edge-yolo/                          # 로컬 YOLO 엣지 시뮬레이터
├─ dashboard/                         # Next.js 검수자 대시보드
├─ lambda/
│  ├─ inspection-event-ingest/         # API Gateway 이벤트 접수 Lambda
│  ├─ container-damage-analyzer/       # S3 트리거 분석 Lambda
│  ├─ dashboard_api/                   # API Gateway 뒤 대시보드 API Lambda
│  ├─ report_generator/                # PDF 리포트 생성 Lambda
│  └─ image_processor/                 # 보조/예정
├─ src/                                # Lambda 공통 Python 모듈
├─ docs/                               # 아키텍처/스키마/콘솔 설정 가이드
├─ infra/                              # AWS 리소스 명세
├─ mock-data/                          # DynamoDB item 샘플
├─ build_lambda.ps1                    # analyzer Lambda zip
├─ build_dashboard_lambda.ps1          # dashboard_api Lambda zip
└─ build_report_lambda.ps1             # report_generator Lambda zip
```

---

## 5. 로컬 프론트 실행

```powershell
cd dashboard
npm ci
npm run dev
```

실제 AWS API Gateway에 붙이려면 `dashboard/.env.local`에 설정합니다.

```text
NEXT_PUBLIC_API_BASE=https://7tevpqwqmj.execute-api.ap-northeast-2.amazonaws.com
```

---

## 6. 로컬 엣지 시뮬레이터 실행

시뮬레이터는 `edge-yolo/`에 구현되어 있습니다. 로컬 이미지에 YOLO 1차 탐지를 수행하고,
손상 의심 건만 `POST /inspection-events`로 전송한 뒤 ingest Lambda가 반환한 presigned URL로
이미지를 S3 `raw-images/`에 직접 업로드합니다.

```powershell
python -m venv .venv-edge
.\.venv-edge\Scripts\python.exe -m pip install -r edge-yolo\requirements.txt

# 실제 손상 감지 모델을 사용하는 경우
$env:EDGE_MODEL_PATH="C:\path\to\stage1_best.pt"

# 입력 이미지는 edge-yolo/input_images/에 둡니다.
$env:EDGE_INTERACTIVE="false"
.\.venv-edge\Scripts\python.exe edge-yolo\simulator.py
```

엔드포인트 호출 없이 payload/bbox 이미지 생성만 확인하려면 dry-run으로 실행합니다.

```powershell
$env:EDGE_DRY_RUN="true"
.\.venv-edge\Scripts\python.exe edge-yolo\simulator.py
```

2026-07-16 기준 실제 API 연동 테스트에서 `POST /inspection-events` 201, S3 presigned PUT 200,
대시보드 API 단건 조회까지 확인했습니다. 자세한 실행 옵션은 [docs/edge-simulator.md](docs/edge-simulator.md)를 봅니다.

---

## 7. Lambda 배포 패키지

```powershell
# 이벤트 접수 Lambda
.\build_ingest_lambda.ps1

# S3 트리거 분석 Lambda
.\build_lambda.ps1

# 대시보드 API Lambda
.\build_dashboard_lambda.ps1

# 리포트 생성 Lambda
.\build_report_lambda.ps1
```

생성되는 zip은 Git에 포함하지 않습니다.

---

## 8. 현재 미완성/결정 지점

- `inspection-event-ingest` Lambda는 `lambda/inspection-event-ingest/handler.py`에 구현되어 있습니다.
- 권장 구조는 `POST /inspection-events`가 DynamoDB PENDING item을 만들고 S3 presigned upload URL을 반환하는 방식입니다.
- YOLO 팀원이 AWS 자격증명을 직접 들고 DynamoDB/S3에 쓰는 방식도 동작은 가능하지만, 포트폴리오/보안 구조로는 ingest API 방식이 더 적합합니다.
- 실제 시연 품질은 `edge-yolo/weights/stage1_best.pt` 손상 감지 모델 품질에 좌우됩니다. 공개 `yolov8n.pt`는 파이프라인 검증용으로만 사용합니다.
