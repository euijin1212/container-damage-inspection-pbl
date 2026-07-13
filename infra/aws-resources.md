# AWS 인프라 리소스 명세서 (Container Damage Inspection MVP)

> **공통 설정**
> * **기본 리전:** 서울 (`ap-northeast-2`)

최종 데이터 흐름:

```text
Simulator → DynamoDB PutItem(PENDING) → S3 PutObject(raw image)
  → Lambda → Foundation Model → DynamoDB UpdateItem → Dashboard
```

---

## 1. Amazon S3 (오브젝트 스토리지)

| 버킷명 | 용도 | 비고 |
| :--- | :--- | :--- |
| **`container-damage`** | 원본 컨테이너 이미지 저장 | Analyzer Lambda의 트리거 소스 |

### S3 저장 기준

* **필수 prefix:** `raw-images/`
  * 경로 규칙: `container-damage/raw-images/{event_id}.jpg`
  * 예: `container-damage/raw-images/EVT-20260713-0001.jpg`
  * 이미지 파일명은 `event_id`와 동일하게 맞춘다.
* **S3에는 원본 이미지만 저장한다.**
* **사용하지 않는 것 (MVP):**
  * S3 metadata 사용 **X**
  * YOLO 결과 JSON(`edge-results/`) 저장 **X**
* **선택/추후 기능:**
  * `annotated-images/` : 선택 기능
  * `reports/` : 추후 기능

⚠️ **무한 루프 주의:** Lambda 분석 결과 이미지(어노테이션 등)를 원본 트리거 버킷의 `raw-images/` 접두사에 다시 저장하면 트리거가 재실행되어 무한 루프가 발생할 수 있습니다. 결과물은 별도 버킷이나 트리거가 제외된 접두사(`annotated-images/` 등)에만 저장합니다.

---

## 2. Amazon DynamoDB (NoSQL 데이터베이스)

컨테이너 파손 이벤트를 저장하는 메인 테이블입니다.

* **테이블명:** `InspectionEventTable`
* **Partition Key (PK):** `event_id` (String) — 이벤트 고유 식별자 (예: `EVT-20260713-0001`)
* **Sort Key (SK):** 없음
* **과금:** 온디맨드(PAY_PER_REQUEST) 권장

### 쓰기 주체

| 주체 | 동작 | 설명 |
| :--- | :--- | :--- |
| **Simulator** | `PutItem` | YOLO가 `DAMAGE_SUSPECTED`로 판단하면, S3 이미지 업로드 **전에** PENDING item을 먼저 저장 |
| **Lambda** | `UpdateItem` | 기존 item을 덮어쓰지 않고 아래 필드만 핀셋 업데이트 |

### Lambda 핀셋 업데이트 대상 필드

* `processed_at`
* `cloud_analysis`
* `risk`
* `review_status`

> 상세 필드 정의는 [../docs/data-schema.md](../docs/data-schema.md), 샘플은 [../mock-data/](../mock-data/) 참조.

---

## 3. AWS Lambda (서버리스 컴퓨팅)

S3 `raw-images/`에 이미지가 업로드되면 실행되어, 이미지를 Bedrock으로 분석하고 결과를 DynamoDB에 UpdateItem 합니다.

* **함수명:** `container-damage-analyzer`
* **핸들러:** `lambda_handler.lambda_handler`
* **트리거:** S3 `ObjectCreated` 이벤트 (`container-damage` 버킷, prefix `raw-images/`)

### 처리 규칙

* Lambda는 `event_id`를 새로 생성하지 **않는다**.
* Lambda는 **S3 key에서 `event_id`를 추출**한다. (예: `raw-images/EVT-20260713-0001.jpg` → `EVT-20260713-0001`)
* Lambda는 DynamoDB에 새 item을 `PutItem` 하지 않고, 기존 item을 `UpdateItem` 한다.

### 환경 변수 (Environment Variables)
* `S3_BUCKET`: 처리 대상 S3 버킷명 (`container-damage`)
* `BEDROCK_MODEL_ID`: 호출할 Bedrock 모델 ID
* `DDB_TABLE`: DynamoDB 테이블명 (`InspectionEventTable`)
* `SNS_TOPIC_ARN`: 위험도 초과 시 알림을 보낼 SNS 토픽 ARN
* `RISK_ALERT_LEVEL`: 알림 발송 기준 위험 등급 (예: `HIGH`)

### 리소스 설정 및 IAM 권한
* **타임아웃:** `90초` 권장 (Bedrock API 응답 시간 고려)
* **메모리:** `512MB` 권장
* **필수 IAM 정책:**
  * `s3:GetObject` (트리거 버킷 읽기)
  * `bedrock:InvokeModel` (AI 모델 호출)
  * `dynamodb:UpdateItem` (기존 item 핀셋 업데이트)
  * `sns:Publish` (고위험 알림 발송)

> Simulator 측(로컬/시뮬레이터)에는 별도로 `dynamodb:PutItem`, `s3:PutObject` 권한이 필요합니다.

---

## 4. Amazon Bedrock (생성형 AI 서비스)

이미지 비전 분석을 담당하는 Foundation Model입니다.

* **사용 모델:** Claude Sonnet 4.5
* **모델 ID:** `apac.anthropic.claude-sonnet-4-5-20250929-v1:0`
* 💡 **사전 준비:** AWS 콘솔의 **[Bedrock → Model access]** 메뉴에서 해당 모델 사용 권한을 미리 활성화해야 API 호출이 가능합니다.

---

## 5. Amazon SNS (알림)

Risk Score가 임계 등급(`RISK_ALERT_LEVEL`, 기본 `HIGH`) 이상일 때 관리자에게 이메일 알림을 발송합니다.

* **토픽명:** `container-damage-alert` (가칭)
* **구독:** 이메일 프로토콜 → 구독 후 메일함에서 **Confirm** 필수
* **발송 주체:** Analyzer Lambda (`SNS_TOPIC_ARN` 환경변수로 지정)

---

## 6. Amazon CloudWatch (모니터링)

* Lambda 실행 로그 그룹: `/aws/lambda/container-damage-analyzer`
* 확인 포인트: 분석 완료 로그, 에러/타임아웃, 처리 지연
* 로그 그룹은 함수가 **최초 실행될 때 자동 생성**된다.
