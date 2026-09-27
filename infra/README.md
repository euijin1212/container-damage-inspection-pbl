# AWS 재배포 및 운영 가이드

이 디렉터리는 부트캠프 계정이 정리된 뒤에도 동일한 서버리스 백엔드를 다시 만들기 위한 실행 문서입니다. 리소스 정의의 기준은 저장소 루트의 [`template.yaml`](../template.yaml)입니다.

## 1. 생성되는 리소스

`sam deploy` 한 번으로 다음 항목을 생성합니다.

| 구분 | 리소스 |
|---|---|
| API | API Gateway HTTP API와 5개 route |
| Compute | ingest, analyzer, dashboard API, report generator Lambda |
| Data | S3 버킷, DynamoDB 테이블, `ReviewStatusIndex`, DynamoDB Stream |
| Event | `raw-images/` S3 ObjectCreated 트리거, DynamoDB Stream 트리거 |
| Ops | CloudWatch Log Group 14일 보존, 고위험 알림용 SNS Topic |
| Security | 함수별 최소 범위 IAM 정책, S3 공개 차단, 암호화 |

인증과 사용자 권한 관리는 현재 MVP 범위에 포함하지 않습니다. 공개 배포 시 `AllowedOrigin`을 실제 대시보드 도메인으로 제한하고 API 인증을 추가해야 합니다.

## 2. 준비 사항

- AWS CLI 로그인 완료
- AWS SAM CLI
- Python 3.12
- GNU Make
- `ap-northeast-2`에서 지정 Bedrock 모델 사용 권한

Windows에서는 WSL에서 실행하거나 Docker Desktop을 켠 뒤 `sam build --use-container`를 사용합니다. 현재 저장소의 Lambda 패키징은 루트 `Makefile`이 담당합니다.

AWS SAM은 CloudFormation 위에서 동작하며, `sam build`가 Lambda 배포 산출물을 구성하고 `sam deploy`가 스택을 배포합니다. 공식 문서는 [AWS SAM build](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/using-sam-cli-build.html)와 [AWS SAM deploy](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-deploying.html)를 참고합니다.

## 3. 배포

스택 이름은 S3 버킷 이름의 일부가 되므로 30자 이하의 영문 소문자와 하이픈 조합을 권장합니다.

```powershell
Copy-Item samconfig.toml.example samconfig.toml
sam validate --lint --template-file template.yaml
sam build --use-container
sam deploy --guided
```

권장 입력값:

```text
Stack Name: seintu-container-inspection
AWS Region: ap-northeast-2
AllowedOrigin: http://localhost:3000
KnowledgeBaseId: 비워도 됨
Confirm changes before deploy: Y
Allow SAM CLI IAM role creation: Y
Save arguments to configuration file: Y
```

배포 결과 확인:

```powershell
aws cloudformation describe-stacks `
  --stack-name seintu-container-inspection `
  --query "Stacks[0].Outputs" `
  --output table
```

`ApiBaseUrl` 출력값을 두 곳에 설정합니다.

```powershell
# Edge simulator
$env:INGEST_API_URL="https://<api-id>.execute-api.ap-northeast-2.amazonaws.com"

# Dashboard: dashboard/.env.local
NEXT_PUBLIC_API_BASE=https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
NEXT_PUBLIC_DEMO_MODE=false
```

## 4. 배포 후 스모크 테스트

```powershell
# API가 빈 목록을 정상 반환하는지 확인
Invoke-RestMethod "$env:INGEST_API_URL/inspections?status=MANUAL_NEEDED"

# 모델 없이 엣지 payload 생성만 확인
$env:EDGE_DRY_RUN="true"
python edge-yolo/simulator.py
```

실제 연동은 `EDGE_MODEL_PATH`, `EDGE_INPUT_DIR`, `INGEST_API_URL`을 지정한 뒤 `EDGE_DRY_RUN=false`로 실행합니다.

## 5. 실패 건 재실행

대시보드의 분석 실패 행에서 재시도를 누르면 `dashboard_api`가 상태를 `PENDING_CLOUD_ANALYSIS`로 되돌리고 analyzer Lambda를 비동기 호출합니다. 보고서 실패/정체 건의 생성 버튼은 report generator를 `force=true`로 다시 호출합니다.

CLI에서 직접 재실행할 때는 다음 스크립트를 사용합니다.

```powershell
.\infra\retry-event.ps1 -EventId EVT-20260713-084200-0001 -Mode analyze
.\infra\retry-event.ps1 -EventId EVT-20260713-084200-0001 -Mode reinspect -ReviewerNote "우측 패널 재확인"
.\infra\retry-event.ps1 -EventId EVT-20260713-084200-0001 -Mode report
```

상세 실패 조건과 복구 가능 범위는 [`docs/failure-recovery.md`](../docs/failure-recovery.md)에 정리되어 있습니다.

## 6. 기존 부트캠프 계정 증거 백업

계정 삭제 전에 아래 스크립트를 실행하면 현재 Lambda 설정, API route, DynamoDB 테이블, S3 이벤트 구성을 `portfolio-evidence/`에 JSON으로 보관합니다. 이 폴더는 계정 ID와 ARN이 포함될 수 있어 Git에서 제외됩니다.

```powershell
.\infra\export-existing-aws-state.ps1
```

추가로 직접 보관할 화면:

- 동작 중인 대시보드 목록과 상세 검수 화면
- API Gateway route 목록
- S3 `raw-images/`, `reports/` 객체 목록
- DynamoDB 완료 item 한 건
- Lambda CloudWatch 성공 로그 한 건
- 생성된 PDF 보고서

## 7. 스택 삭제

```powershell
sam delete --stack-name seintu-container-inspection --region ap-northeast-2
```

S3와 DynamoDB에는 `DeletionPolicy: Retain`이 적용되어 스택 삭제 후에도 데이터가 남습니다. 비용을 완전히 없애려면 필요한 자료를 백업한 뒤 retained 버킷과 테이블을 별도로 삭제해야 합니다. 삭제 전 대상 이름은 CloudFormation Output과 AWS 콘솔에서 다시 확인합니다.
