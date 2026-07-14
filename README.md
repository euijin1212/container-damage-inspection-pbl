# Container Damage Inspection PBL

컨테이너 게이트 반출입 시 촬영된 이미지에서 파손을 탐지하고,
Foundation Model로 2차 분석하여 검수자가 확인할 대상을 선별하는 MVP 프로젝트입니다.

> 포트폴리오용 MVP 단계입니다. 데이터 구조는 당장 구현에 필요한 최소 필드만 유지합니다.

---

## 1. 최종 흐름

```text
Simulator
  → DynamoDB PutItem(PENDING)
  → S3 PutObject(raw image)
  → Lambda (S3 raw-images/ 트리거)
  → Foundation Model
  → DynamoDB UpdateItem
  → Dashboard
```

1. Simulator가 기본 이벤트 정보를 생성하고, 내부에서 YOLO 모델을 실행한다.
2. YOLO가 파손 여부, bbox, confidence를 생성한다.
3. YOLO가 `DAMAGE_SUSPECTED`로 판단한 경우에만 DynamoDB에 PENDING item을 먼저 저장한다.
4. S3 `raw-images/{event_id}.jpg`에 원본 이미지만 업로드한다.
5. S3 업로드 이벤트로 Lambda가 실행되고, S3 key에서 `event_id`를 추출한다.
6. Lambda가 Foundation Model 분석 후 기존 item을 `UpdateItem`으로 핀셋 업데이트한다.
7. Dashboard는 `review_status = MANUAL_NEEDED`인 item만 검수 큐에 표시한다.

---

## 2. 구성요소 역할

| 구성요소 | 역할 |
|---|---|
| Simulator | 기본 이벤트 정보 생성, 내부 YOLO 실행, DynamoDB PutItem(PENDING), S3 원본 이미지 업로드 |
| YOLO 모델 | 파손 여부 1차 판단, bbox / confidence 생성 (Simulator 내부에서 실행) |
| S3 | 원본 이미지 저장 (`raw-images/`) 및 Lambda 트리거 소스 |
| Lambda | S3 key에서 `event_id` 추출, Foundation Model 호출, DynamoDB UpdateItem |
| Foundation Model | 파손 유형 / 위치 / 심각도 분석 |
| DynamoDB | 이벤트 상태와 분석 결과 저장 (`InspectionEventTable`) |
| Dashboard | `MANUAL_NEEDED` item 검수 큐 표시 |

---

## 3. 저장 원칙

- **S3는 이미지만 저장한다.** 필수 경로는 `container-damage/raw-images/{event_id}.jpg` 하나다.
  - S3 metadata는 사용하지 않는다.
  - YOLO 결과 JSON(edge-results)은 S3에 저장하지 않는다.
  - `annotated-images/`는 선택 기능, `reports/`는 추후 기능으로만 고려한다.
- **DynamoDB는 상태와 분석 결과를 저장한다.**
  - Simulator가 PENDING item을 PutItem 하고, Lambda가 분석 결과를 UpdateItem 한다.

---

## 4. 문서 / 데이터

- 상세 스키마: [docs/data-schema.md](docs/data-schema.md)
- 인프라 리소스: [infra/aws-resources.md](infra/aws-resources.md)
- 예시 JSON: [mock-data/](mock-data/)

| mock-data 파일 | 설명 |
|---|---|
| `sample_pending_item.json` | Simulator가 PutItem 하는 최소 PENDING item |
| `sample_completed_update.json` | Lambda 성공 시 UpdateItem 필드 |
| `sample_failed_update.json` | Lambda 실패 시 UpdateItem 필드 |

---

## 5. 폴더 구조

```text
container-damage-inspection-pbl/
├─ README.md
├─ requirements.txt
├─ build_lambda.ps1                  # analyzer Lambda 배포 zip 생성 스크립트
├─ docs/
│  ├─ architecture.md
│  └─ data-schema.md                 # DynamoDB item 구조 (MVP)
├─ edge-yolo/                        # 로컬/시뮬레이터 YOLO 추론
├─ lambda/
│  └─ container-damage-analyzer/     # S3 트리거 분석 Lambda
├─ src/                              # 클라우드 분석 공유 라이브러리
├─ dashboard/                        # 검수자 대시보드
├─ mock-data/                        # JSON 필드 통일용 샘플
└─ infra/
   └─ aws-resources.md               # AWS 리소스 명세
```

---

## 6. 분석 Lambda 배포

```powershell
# 1) 배포 패키지 생성 → lambda_deploy.zip (생성물, git 추적 안 함)
.\build_lambda.ps1

# 2) AWS 콘솔에서 container-damage-analyzer 에 lambda_deploy.zip 업로드
#    - 핸들러: lambda_handler.lambda_handler
#    - 타임아웃 90초 / 메모리 512MB
```
