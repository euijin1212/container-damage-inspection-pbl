# AWS 콘솔 설정 순서

이 문서는 GUI로 API Gateway와 Lambda를 연결할 때 따라가는 순서입니다.

## 1. 전체 구조

```text
API Gateway 하나
├─ POST /inspection-events              → inspection-event-ingest
├─ GET /inspections                     → dashboard_api
├─ GET /inspections/{event_id}          → dashboard_api
├─ POST /inspections/{event_id}/review  → dashboard_api
└─ GET /inspections/{event_id}/report   → dashboard_api

S3 raw-images/* ObjectCreated           → container-damage-analyzer
DynamoDB Stream review_status=DONE      → report_generator
```

사진 파일은 API Gateway를 통과하지 않습니다.

```text
메타데이터 JSON → API Gateway
이미지 파일     → S3 presigned URL
```

## 2. `inspection-event-ingest` Lambda 생성

AWS Console → Lambda → Create function

```text
Function name: inspection-event-ingest
Runtime: Python 3.12
Architecture: x86_64
Execution role: Create a new role with basic Lambda permissions
```

코드는 `lambda/inspection-event-ingest/handler.py` 내용을 사용합니다.

환경변수:

```text
DDB_TABLE=InspectionEventTable
S3_BUCKET=container-damage
UPLOAD_EXPIRES=900
CORS_ORIGIN=*
```

IAM inline policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:PutItem"],
      "Resource": "arn:aws:dynamodb:ap-northeast-2:*:table/InspectionEventTable"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": "arn:aws:s3:::container-damage/raw-images/*"
    }
  ]
}
```

구현 시 DynamoDB PutItem에는 반드시 중복 방지 조건을 둡니다.

```python
ConditionExpression="attribute_not_exists(event_id)"
```

## 3. API Gateway route 추가

AWS Console → API Gateway → `dashboard-api` → Routes → Create

```text
Method: POST
Path: /inspection-events
```

Integration:

```text
Lambda function: inspection-event-ingest
```

Lambda permission 추가 확인 창이 나오면 허용합니다.

## 4. CORS 설정

API Gateway → CORS

```text
Allow origins: *
Allow methods: GET,POST,OPTIONS
Allow headers: Content-Type,Authorization
```

## 5. S3 trigger 연결

S3 → `container-damage` → Properties → Event notifications → Create event notification

```text
Event name: raw-images-created
Prefix: raw-images/
Event types: All object create events
Destination: Lambda function
Lambda: container-damage-analyzer
```

## 6. Dashboard API routes

아래 route가 모두 `dashboard_api` Lambda에 연결되어 있어야 합니다.

```text
GET  /inspections
GET  /inspections/{event_id}
POST /inspections/{event_id}/review
GET  /inspections/{event_id}/report
```

## 7. 프론트 연결

`dashboard/.env.local`:

```text
NEXT_PUBLIC_API_BASE=https://7tevpqwqmj.execute-api.ap-northeast-2.amazonaws.com
```

실행:

```powershell
cd dashboard
npm run dev
```

## 8. YOLO 팀원 호출 순서

1. `POST /inspection-events`로 메타데이터와 YOLO 결과 JSON 전송
2. 응답의 `upload_url` 수신
3. `upload_url`에 이미지 파일을 `PUT`
4. S3 trigger가 analyzer Lambda 실행
5. 대시보드가 polling으로 결과 표시
