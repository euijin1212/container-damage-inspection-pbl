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
  → (검수 완료) DynamoDB Streams → report_generator → PDF 보고서
```

1. Simulator가 기본 이벤트 정보를 생성하고, 내부에서 YOLO 모델을 실행한다.
2. YOLO가 파손 여부, bbox, confidence를 생성한다.
3. YOLO가 `DAMAGE_SUSPECTED`로 판단한 경우에만 DynamoDB에 PENDING item을 먼저 저장한다.
4. S3 `raw-images/{event_id}.jpg`에 원본 이미지만 업로드한다.
5. S3 업로드 이벤트로 Lambda가 실행되고, S3 key에서 `event_id`를 추출한다.
6. Lambda가 Foundation Model 분석 후 기존 item을 `UpdateItem`으로 핀셋 업데이트한다.
7. Dashboard는 `review_status = MANUAL_NEEDED`인 item만 검수 큐에 표시한다.
8. 검수 완료(`review_status = DONE`) 시 `report_generator`가 EIR PDF 보고서를 자동 생성한다.

---

## 2. 구성요소 역할

| 구성요소 | 역할 |
|---|---|
| Simulator | 기본 이벤트 정보 생성, 내부 YOLO 실행, DynamoDB PutItem(PENDING), S3 원본 이미지 업로드 |
| YOLO 모델 | 파손 여부 1차 판단, bbox / confidence 생성 (Simulator 내부에서 실행) |
| S3 | 원본 이미지 저장 (`raw-images/`), 보고서 PDF 저장 (`reports/`) |
| container-damage-analyzer | S3 key에서 `event_id` 추출, Foundation Model 호출, DynamoDB UpdateItem |
| report_generator | 검수 완료 시 Bedrock 보고서 초안 → PDF → S3 → DynamoDB `report` 메타 갱신 |
| Foundation Model | 파손 유형 / 위치 / 심각도 분석, EIR 보고서 서술 생성 |
| DynamoDB | 이벤트 상태와 분석 결과 저장 (`InspectionEventTable`) |
| Dashboard | `MANUAL_NEEDED` item 검수 큐 표시 |

---

## 3. 저장 원칙

- **S3는 이미지(필수)와 보고서 PDF(선택)를 저장한다.**
  - 필수: `container-damage/raw-images/{event_id}.jpg`
  - 보고서: `container-damage/reports/{event_id}.pdf`
  - S3 metadata는 사용하지 않는다.
  - YOLO 결과 JSON(edge-results)은 S3에 저장하지 않는다.
- **DynamoDB는 상태와 분석 결과를 저장한다.**
  - Simulator가 PENDING item을 PutItem 하고, Lambda가 분석 결과를 UpdateItem 한다.
  - report_generator가 검수 완료 후 `report` 중첩 객체를 UpdateItem 한다.

---

## 4. 문서 / 데이터

- 상세 스키마: [docs/data-schema.md](docs/data-schema.md)
- 인프라 리소스: [infra/aws-resources.md](infra/aws-resources.md)
- 예시 JSON: [mock-data/](mock-data/)

| mock-data 파일 | 설명 |
|---|---|
| `sample_pending_item.json` | Simulator가 PutItem 하는 최소 PENDING item |
| `sample_completed_update.json` | Analyzer Lambda 성공 시 UpdateItem 필드 |
| `sample_failed_update.json` | Analyzer Lambda 실패 시 UpdateItem 필드 |
| `sample_report_update.json` | report_generator 성공 시 `report` 필드 |

---

## 5. 폴더 구조

```text
container-damage-inspection-pbl/
├─ README.md
├─ requirements.txt
├─ build_lambda.ps1                  # analyzer Lambda 배포 zip
├─ build_report_lambda.ps1           # report_generator Lambda 배포 zip
│
├─ docs/
│  ├─ architecture.md
│  └─ data-schema.md                 # DynamoDB item 구조 (MVP)
│
├─ edge-yolo/                        # 로컬/시뮬레이터 YOLO 추론
│
├─ lambda/
│  ├─ container-damage-analyzer/     # ★ S3 트리거 분석 Lambda (구현 완료)
│  │  └─ lambda_handler.py
│  ├─ dashboard_api/                 # (플레이스홀더) 대시보드 API
│  │  └─ handler.py
│  └─ report_generator/              # ★ 검수 완료 시 EIR 보고서 자동 생성 (구현 완료)
│     ├─ handler.py
│     └─ sample_stream_event.json    # Lambda 테스트용 Streams 이벤트
│
├─ src/                              # 클라우드 공유 라이브러리
│  ├─ bedrock_analyzer.py            # Bedrock 비전 모델 손상 분석
│  ├─ risk_score.py                  # Risk Score 계산
│  ├─ s3_client.py                   # S3 이미지 조회/다운로드
│  ├─ report_writer.py               # Bedrock EIR 보고서 초안 (+선택적 RAG)
│  ├─ pdf_report.py                  # 보고서 dict → PDF (fpdf2)
│  ├─ knowledge_base.py              # Bedrock Knowledge Base RAG 래퍼
│  ├─ record_adapter.py              # MVP 중첩 스키마 → 보고서용 flat 변환
│  ├─ fonts/                         # PDF 한글 렌더용 TTF (NanumGothic)
│  └─ config.py
│
├─ knowledge-base/                   # 보고서 RAG 참고 문서 (Bedrock KB 색인 대상)
│  ├─ eir_report_template.md
│  ├─ report_writing_guide.md
│  └─ README.md
│
├─ dashboard/
│  └─ README.md
│
├─ mock-data/
└─ infra/
   └─ aws-resources.md
```

> **구현 상태:** `container-damage-analyzer`, `report_generator`, `src/` 가 실제 동작 코드입니다.

---

## 6. 분석 Lambda 배포

```powershell
.\build_lambda.ps1
```

- 핸들러: `lambda_handler.lambda_handler`
- 타임아웃 90초 / 메모리 512MB
- 환경변수: `S3_BUCKET`, `BEDROCK_MODEL_ID`, `DDB_TABLE=InspectionEventTable`, `SNS_TOPIC_ARN`

---

## 7. 보고서 자동화 Lambda 배포

검수 완료(`review_status = DONE`) 시 DynamoDB Streams가 `report_generator`를 트리거합니다.

```text
DynamoDB(상태 변경) → Streams → Lambda(report_generator)
  → Bedrock(보고서 초안) → PDF(fpdf2) → S3(reports/<event_id>.pdf)
  → DynamoDB(report 중첩 객체 갱신)
```

```powershell
.\build_report_lambda.ps1
```

- 핸들러: `handler.lambda_handler`
- 타임아웃 120초 / 메모리 256~512MB
- 환경변수: `DDB_TABLE=InspectionEventTable`, `REPORT_BUCKET`, `REPORT_PREFIX`, `BEDROCK_MODEL_ID`
- (선택) `KNOWLEDGE_BASE_ID`, `KB_MAX_RESULTS` — 보고서 RAG
- DynamoDB Streams 활성화(New and old images) 후 트리거 연결

### 보고서 RAG (선택)

[knowledge-base/README.md](knowledge-base/README.md) 참고. `KNOWLEDGE_BASE_ID` 설정 시 EIR 양식/지침을 KB에서 검색해 프롬프트에 주입합니다.

---

## 8. 구현 상태

| 구성요소 | 상태 |
|---|---|
| `container-damage-analyzer` | 구현 완료 (MVP PENDING → UpdateItem 워크플로) |
| `report_generator` | 구현 완료 (DONE → PDF 보고서 자동화) |
| `src/` | 구현 완료 |
| `dashboard_api`, `edge-yolo` | 플레이스홀더 |
