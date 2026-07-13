# Container Damage Inspection PBL

## 1. 프로젝트 흐름

```text
로컬 컨테이너 이미지
-> YOLO 모델이 로컬에서 1차 파손 여부 판단
-> 파손 의심 이미지일 경우에만 S3 raw-images/ 업로드
-> YOLO 결과 JSON도 함께 저장 또는 전달
-> S3 업로드 이벤트로 Lambda 실행
-> Foundation Model이 파손 유형, 위치, 심각도 분석
-> Lambda가 YOLO 결과 + Foundation Model 결과를 통합
-> DynamoDB에 최종 InspectionEvent JSON 저장
-> Dashboard에서 검수자가 확인
-> 검수 완료 후 보고서 생성
```

---

## 2. 폴더 구조

```text
container-damage-inspection-pbl/
├─ README.md                         # 프로젝트 폴더 구조와 JSON 필드 통일 문서
├─ .gitignore                        # AWS 키, 모델 가중치, 환경변수 제외 설정
│
├─ docs/                             # 설계 문서
│  ├─ architecture.md                # AWS 전체 아키텍처 정리
│  └─ data-schema.md                 # DynamoDB JSON 구조 정리
│
├─ edge-yolo/                        # 로컬 YOLO 1차 파손 판단
│  ├─ infer.py                       # YOLO로 이미지 추론, bbox/confidence 출력
│  ├─ upload_to_s3.py                # 파손 의심 이미지와 결과 JSON을 S3로 업로드
│  ├─ config.py                      # threshold, bucket name, prefix 등 설정
│  ├─ weights/                       # YOLO 모델 가중치, GitHub 업로드 X
│  ├─ input_images/                  # 테스트용 원본 컨테이너 이미지, GitHub 업로드 X 가능
│  ├─ output_results/                # YOLO 추론 결과 JSON, bbox 시각화 결과
│  └─ sample_events/                 # 테스트용 edge 결과 JSON
│
├─ lambda/                           # AWS Lambda 코드
│  ├─ image_processor/               # S3 이미지 업로드 후 실행되는 Lambda
│  │  └─ handler.py                  # S3 metadata, YOLO 결과, Foundation Model 결과 통합 후 DynamoDB 저장
│  │
│  ├─ dashboard_api/                 # 대시보드 API Lambda
│  │  └─ handler.py                  # 검수 큐 조회, 승인/수정/반려 처리
│  │
│  └─ report_generator/              # 보고서 생성 Lambda
│     └─ handler.py                  # 검수 완료된 파손 건에 대해 Bedrock 보고서 생성
│
├─ dashboard/                        # 검수자 대시보드
│  └─ README.md                      # 대시보드 실행 방법, 화면 구성 정리
│
├─ mock-data/                        # 팀원 간 JSON 필드명 통일용 샘플
│  ├─ sample_edge_result.json        # YOLO 로컬 추론 결과 예시
│  ├─ sample_cloud_result.json       # Foundation Model 분석 결과 예시
│  └─ sample_dynamodb_item.json      # DynamoDB 최종 저장 item 예시
│
└─ infra/                            # AWS 리소스 설정 메모
   └─ aws-resources.md               # S3, DynamoDB, Lambda, Bedrock 리소스 이름 정리
```

---

## 3. JSON 데이터 흐름

전체 JSON을 처음부터 S3에 올리는 구조가 아니다.

```text
1. YOLO가 로컬에서 이미지 분석
2. 파손 의심이면 이미지 S3 업로드
3. YOLO 결과 JSON도 함께 저장 또는 전달
4. Lambda가 S3 metadata와 YOLO 결과를 읽음
5. Lambda가 Foundation Model을 호출
6. Foundation Model이 파손 유형, 위치, 심각도, 설명 생성
7. Lambda가 최종 JSON을 만들어 DynamoDB에 저장
```

---

## 4. S3 저장 기준

```text
raw-images/
└─ 파손 의심 원본 이미지 저장

edge-results/
└─ YOLO 로컬 추론 결과 JSON 저장

reports/
└─ 검수 완료 후 생성된 보고서 저장
```

예시:

```text
raw-images/EVT-20260709-0001.jpg
edge-results/EVT-20260709-0001.json
reports/EVT-20260709-0001.json
```

---

## 5. S3 metadata 기준

이미지 업로드 시 S3 metadata에는 작은 기본 정보만 넣는다.

```text
event-id
container-id
gate-id
vehicle-no
captured-at
direction
edge-status
upload-reason
edge-confidence
edge-result-key
```

예시:

```text
event-id: EVT-20260709-0001
container-id: MSCU1234567
gate-id: GATE-01
vehicle-no: BUSAN-1234
captured-at: 2026-07-09T14:32:00Z
direction: IN
edge-status: DAMAGE_SUSPECTED
upload-reason: EDGE_DAMAGE_DETECTED
edge-confidence: 0.82
edge-result-key: edge-results/EVT-20260709-0001.json
```

---

## 6. 상태값 통일

### edge_status

| 값 | 의미 |
|---|---|
| DAMAGE_SUSPECTED | YOLO가 파손 의심으로 판단 |
| NORMAL | YOLO가 정상으로 판단 |

### upload_reason

| 값 | 의미 |
|---|---|
| EDGE_DAMAGE_DETECTED | YOLO가 파손 의심으로 판단해 클라우드 업로드 |
| EDGE_AUTO_OK | YOLO가 정상으로 판단해 업로드하지 않음 |

### review_status

| 값 | 의미 |
|---|---|
| MANUAL_NEEDED | 검수자 확인 필요 |
| DONE | 검수 완료 |
| INFERENCE_FAILED | 클라우드 분석 실패 |

### report_status

| 값 | 의미 |
|---|---|
| NOT_CREATED | 보고서 생성 전 |
| PENDING | 보고서 생성 중 |
| CREATED | 보고서 생성 완료 |
| FAILED | 보고서 생성 실패 |