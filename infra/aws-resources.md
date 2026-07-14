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

환경변수:

```text
AWS_REGION=ap-northeast-2
BEDROCK_REGION=ap-northeast-2
BEDROCK_MODEL_ID=apac.anthropic.claude-sonnet-4-5-20250929-v1:0
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
sns:Publish          # SNS 사용 시
```

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
s3:DeleteObject
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

## 5. Dashboard Frontend

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
