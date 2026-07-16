# AWS 인프라 리소스 명세서

기본 리전은 **서울(`ap-northeast-2`)** 입니다.

## 1. API Gateway

현재 API ID:

```text
7tevpqwqmj
```

기본 URL:

```text
https://7tevpqwqmj.execute-api.ap-northeast-2.amazonaws.com
```

권장 route 구성:

| Method | Path | Integration |
|---|---|---|
| POST | `/inspection-events` | Lambda `inspection-event-ingest` |
| GET | `/inspections` | Lambda `dashboard_api` |
| GET | `/inspections/{event_id}` | Lambda `dashboard_api` |
| POST | `/inspections/{event_id}/review` | Lambda `dashboard_api` |
| GET | `/inspections/{event_id}/report` | Lambda `dashboard_api` |

사진 파일은 API Gateway 요청 body로 보내지 않습니다. `POST /inspection-events`는 메타데이터만 받고, 이미지 업로드는 S3 presigned URL로 직접 수행합니다.

## 2. S3

| 항목 | 값 |
|---|---|
| 버킷 | `container-damage` |
| 원본 이미지 prefix | `raw-images/` |
| 리포트 prefix | `reports/` |

이미지 key 규칙:

```text
raw-images/{event_id}.jpg
raw-images/{event_id}.png
raw-images/{event_id}.webp
```

S3 trigger:

```text
Event type: ObjectCreated
Prefix: raw-images/
Target Lambda: container-damage-analyzer
```

## 3. DynamoDB

| 항목 | 값 |
|---|---|
| 테이블 | `InspectionEventTable` |
| PK | `event_id` (String) |
| Billing | On-demand 권장 |

권장 GSI:

```text
Index name: ReviewStatusIndex
Partition key: review_status
Sort key: event_date
```

GSI가 없으면 `dashboard_api`는 Scan fallback을 사용할 수 있지만, 포트폴리오/운영 구조로는 GSI를 두는 편이 좋습니다.

## 4. Lambda

### `inspection-event-ingest`

트리거:

```text
API Gateway POST /inspection-events
```

역할:

```text
1. 요청 JSON 검증
2. DynamoDB PutItem(PENDING)
3. S3 presigned PUT URL 발급
4. upload_url 반환
```

코드 위치:

```text
lambda/inspection-event-ingest/handler.py
```

배포 패키지:

```powershell
.\build_ingest_lambda.ps1
```

필수 안전장치:

```python
ConditionExpression="attribute_not_exists(event_id)"
```

환경변수:

```text
DDB_TABLE=InspectionEventTable
S3_BUCKET=container-damage
UPLOAD_EXPIRES=900
CORS_ORIGIN=*
```

필수 IAM:

```text
dynamodb:PutItem
s3:PutObject
```

### `container-damage-analyzer`

트리거:

```text
S3 ObjectCreated, prefix raw-images/
```

핸들러:

```text
lambda_handler.lambda_handler
```

권장 구성:

```text
Timeout: 120초 (Bedrock converse 55초 read_timeout + 여유)
Memory: 1024 MB 이상
```

환경변수:

```text
AWS_REGION=ap-northeast-2
BEDROCK_REGION=ap-northeast-2
BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-4-5-20250929-v1:0
BEDROCK_READ_TIMEOUT=55
DDB_TABLE=InspectionEventTable
S3_BUCKET=container-damage
SNS_TOPIC_ARN=선택
RISK_ALERT_LEVEL=HIGH
```

필수 IAM:

```text
s3:GetObject
dynamodb:GetItem
dynamodb:UpdateItem
bedrock:InvokeModel
bedrock:InvokeModelWithResponseStream
sns:Publish          # SNS 사용 시
```

역할 `container-damage-analyzer-role-*` 에 인라인/관리형 정책으로 추가 (콘솔 → Lambda → 구성 → 권한 → 역할 이름 클릭):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDBInspection",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:UpdateItem",
        "dynamodb:PutItem"
      ],
      "Resource": "arn:aws:dynamodb:ap-northeast-2:963701985499:table/InspectionEventTable"
    },
    {
      "Sid": "S3RawImages",
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::container-damage/raw-images/*"
    },
    {
      "Sid": "BedrockInvoke",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "*"
    }
  ]
}
```

S3 트리거가 안 붙으면 업로드해도 analyzer 가 안 돕니다. 콘솔에서 확인:

```text
S3 → container-damage → 속성 → 이벤트 알림
  → Event types: All object create
  → Prefix: raw-images/
  → Destination: Lambda container-damage-analyzer
```

멈춘 건(RUNNING, risk 없음) 은 대시보드 PENDING 목록 폴링이 analyzer 를 비동기 재호출합니다.

### `dashboard_api`

트리거:

```text
API Gateway /inspections*
```

핸들러:

```text
handler.lambda_handler
```

환경변수:

```text
DDB_TABLE=InspectionEventTable
REVIEW_STATUS_INDEX=ReviewStatusIndex
S3_BUCKET=container-damage
PRESIGN_EXPIRES=3600
CORS_ORIGIN=*
  ANALYZER_FUNCTION_NAME=container-damage-analyzer
BEDROCK_MODEL_ID=apac.anthropic.claude-sonnet-4-5-20250929-v1:0
BEDROCK_IMAGE_MODEL_ID=amazon.nova-canvas-v1:0
BEDROCK_IMAGE_REGION=us-east-1
```

필수 IAM:

```text
dynamodb:GetItem
dynamodb:Query
dynamodb:Scan
dynamodb:UpdateItem
dynamodb:DeleteItem
s3:GetObject
s3:HeadObject
s3:PutObject           # 재검수 화질개선 이미지 저장
s3:DeleteObject
bedrock:InvokeModel          # PENDING 복구 분석 + 재검수
bedrock:InvokeModelWithResponseStream
lambda:InvokeFunction        # PENDING 목록 폴링 시 analyzer 재호출
```

권장 설정:

```text
Timeout: 90초 이상 (재검수 Bedrock)
Memory: 512MB 이상
```

재검수 흐름:

```text
원본 S3 이미지
  → Nova Canvas IMAGE_VARIATION (화질 개선, us-east-1)
  → enhanced-images/{event_id}.png 저장
  → Claude 비전 + 검수 의견으로 재감지
  → review_status=MANUAL_NEEDED
```

최초 유입 분석(원래 방식):

```text
ingest PutItem(PENDING)
  → S3 raw-images/ 업로드
  → container-damage-analyzer (S3 트리거)
  → MANUAL_NEEDED | INFERENCE_FAILED
```

### `report_generator`

트리거:

```text
DynamoDB Stream 또는 직접 호출
```

핸들러:

```text
handler.lambda_handler
```

환경변수:

```text
DDB_TABLE=InspectionEventTable
REPORT_BUCKET=container-damage
REPORT_PREFIX=reports/
BEDROCK_MODEL_ID=apac.anthropic.claude-sonnet-4-5-20250929-v1:0
```

필수 IAM:

```text
dynamodb:GetItem
dynamodb:UpdateItem
s3:PutObject
bedrock:InvokeModel
```

## 5. Edge Simulator

위치:

```text
edge-yolo/
```

주요 파일:

```text
simulator.py       # 전체 실행 진입점
infer.py           # Ultralytics YOLO 추론
ingest_client.py   # API Gateway POST /inspection-events
upload_to_s3.py    # bbox 렌더링 + presigned URL PUT
config.py          # 환경변수/.env 설정
requirements.txt   # 로컬 실행 의존성
```

로컬 실행 준비:

```powershell
python -m venv .venv-edge
.\.venv-edge\Scripts\python.exe -m pip install -r edge-yolo\requirements.txt
```

환경변수:

```text
INGEST_API_URL=https://7tevpqwqmj.execute-api.ap-northeast-2.amazonaws.com
INGEST_PATH=/inspection-events
EDGE_MODEL_PATH=edge-yolo/weights/stage1_best.pt
EDGE_INPUT_DIR=edge-yolo/input_images
EDGE_OUTPUT_DIR=edge-yolo/output_results
EDGE_CONF=0.15
EDGE_IMGSZ=896
EDGE_DRY_RUN=false
EDGE_INTERACTIVE=true
```

실행:

```powershell
$env:EDGE_INTERACTIVE="false"
.\.venv-edge\Scripts\python.exe edge-yolo\simulator.py
```

dry-run은 API Gateway/S3 호출 없이 payload JSON과 bbox JPEG만 생성합니다.

```powershell
$env:EDGE_DRY_RUN="true"
.\.venv-edge\Scripts\python.exe edge-yolo\simulator.py
```

실제 연동 확인 결과(2026-07-16):

```text
container-dent.png → [EVT-20260716-054239-0001] POST 201 · S3 PUT 200 → raw-images/EVT-20260716-054239-0001.jpg
dashboard_api GET /inspections/{event_id} → MANUAL_NEEDED, risk_level=MEDIUM, report_status=NOT_CREATED
```

주의:

```text
edge-yolo/weights/         # 모델 파일은 Git 제외
edge-yolo/input_images/    # 테스트 입력 이미지 Git 제외
edge-yolo/output_results/  # 생성 payload/bbox 이미지 Git 제외
```

## 6. Dashboard Frontend

위치:

```text
dashboard/
```

환경변수:

```text
NEXT_PUBLIC_API_BASE=https://7tevpqwqmj.execute-api.ap-northeast-2.amazonaws.com
```

실행:

```powershell
cd dashboard
npm ci
npm run dev
```
