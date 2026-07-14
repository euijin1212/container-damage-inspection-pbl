# AWS 인프라 리소스 명세서 (Container Damage Analysis)

> **공통 설정**
> * **기본 리전:** 서울 (`ap-northeast-2`)

---

## 1. Amazon S3 (오브젝트 스토리지)

| 버킷명 (가칭) | 용도 | 비고 |
| :--- | :--- | :--- |
| **`container-damage`** | 엣지 디바이스 업로드 이미지 저장 | • Analyzer Lambda의 트리거 소스로 사용됨 |

⚠️ **주의사항:** Lambda 분석 결과(어노테이션 이미지 등)를 원본 트리거 버킷(`container-damage`)에 다시 저장하면 **무한 루프(Infinite Loop)**가 발생하여 요금 폭탄을 맞을 수 있습니다. 결과물은 반드시 별도의 버킷이나 트리거가 제외된 특정 접두사(Prefix) 경로에 저장해야 합니다.

---

## 2. Amazon DynamoDB (NoSQL 데이터베이스)

컨테이너 파손 및 부식 분석 결과를 이벤트 단위로 저장하는 메인 테이블입니다.

* **테이블명:** `container-inspection` (가칭)
* **Partition Key (PK):** `event_id` (String) - 각 분석 이벤트의 고유 식별자
* **Sort Key (SK):** `processed_at` (String) - 데이터 처리 완료 일시 (ISO 8601)

### 주요 속성 (Attributes) 명세

| 속성명 | 타입 | 설명 | 예시 |
| :--- | :--- | :--- | :--- |
| **event_id** | String | **[PK]** 이벤트 고유 ID | `evt_658674034a1e` |
| **processed_at** | String | **[SK]** 데이터 처리 완료 일시 | `2026-07-13T02:35:26Z` |
| **event_date** | String | 이벤트 발생 일자 (YYYY-MM-DD) | `2026-07-13` |
| **image_path** | String | 원본/분석 이미지의 S3 경로 | `s3://container-damage/9a01...jpg` |
| **model_version**| String | 분석에 사용된 AI 모델 버전 | `global.anthropic...` |
| **inspection_result**| String | 최종 검사 결과 | `damage` |
| **review_status**| String | 관리자 검토 상태 | `MANUAL_NEEDED` |
| **risk_level** | String | 전체 위험 등급 | `MEDIUM` |
| **risk_score** | Number | 전체 위험도 점수 | `41.3` |
| **detections** | List | 파손 감지 상세 내역 (Map 배열) | `[{"class": "rust", "severity": "high"...}]` |
| **risk_breakdown** | List | 위험도 산출 세부 내역 (Map 배열) | `[{"component_score": 31.5...}]` |

---

## 3. AWS Lambda (서버리스 컴퓨팅)

S3에 이미지가 업로드되면 실행되어, 이미지를 Bedrock으로 보내 분석하고 결과를 DynamoDB에 저장합니다.

* **함수명:** `container-damage-analyzer`
* **핸들러:** `lambda_handler.lambda_handler`
* **트리거:** S3 `ObjectCreated` 이벤트 (`container-damage` 버킷)

### 환경 변수 (Environment Variables)
* `S3_BUCKET`: 처리 대상 S3 버킷명
* `BEDROCK_MODEL_ID`: 호출할 Bedrock 모델 ID
* `DDB_TABLE`: 분석 결과를 저장할 DynamoDB 테이블명
* `SNS_TOPIC_ARN`: 위험도 초과 시 알림을 보낼 SNS 토픽 ARN
* `RISK_ALERT_LEVEL`: 알림 발송 기준 위험 등급 (예: `HIGH`)

### 리소스 설정 및 IAM 권한
* **타임아웃:** `90초` 권장 (Bedrock API 응답 시간 고려)
* **메모리:** `512MB` 권장 (이미지 리사이징 등 전처리 필요 시 증설)
* **필수 IAM 정책:**
  * `s3:GetObject` (트리거 버킷 읽기)
  * `bedrock:InvokeModel` (AI 모델 호출)
  * `dynamodb:PutItem` (테이블 쓰기)
  * `sns:Publish` (고위험 알림 발송)

---

## 4. Amazon Bedrock (생성형 AI 서비스)

이미지 비전 분석을 담당하는 파운데이션 모델입니다. 

* **사용 모델:** Claude Sonnet 4.5
* **모델 ID:** `apac.anthropic.claude-sonnet-4-5-20250929-v1:0`
* 💡 **사전 준비:** AWS 콘솔의 **[Bedrock -> Model access]** 메뉴에서 해당 모델에 대한 사용 권한을 미리 요청하고 활성화해야 API 호출이 가능합니다.

---

## 5. Amazon SNS (알림)

Risk Score 가 임계 등급(`RISK_ALERT_LEVEL`, 기본 `HIGH`) 이상일 때 관리자에게 이메일 알림을 발송합니다.

* **토픽명:** `container-damage-alert` (가칭)
* **구독:** 이메일 프로토콜 → 구독 후 메일함에서 **Confirm** 필수
* **발송 주체:** Analyzer Lambda (`SNS_TOPIC_ARN` 환경변수로 지정)

---

## 6. Amazon CloudWatch (모니터링)

* Lambda 실행 로그 그룹: `/aws/lambda/container-damage-analyzer`
* 확인 포인트: `[분석완료] ... → HIGH (score=...)` 로그, 에러/타임아웃, 처리 지연
* 로그 그룹은 함수가 **최초 실행될 때 자동 생성**된다(미실행 시 "로그 그룹 없음"은 정상).
