# knowledge-base/ — 보고서 RAG 참고 문서

`lambda/report_generator` 가 EIR 보고서를 작성할 때 **Amazon Bedrock Knowledge Base**
에서 검색(retrieve)해 참고하는 원본 문서 모음이다.

| 파일 | 용도 |
|---|---|
| `eir_report_template.md` | EIR 보고서 표준 양식(구성 항목·문체·재사용 판정 기준) |
| `report_writing_guide.md` | 손상 유형별 표현·심각도 해석·권고 문구 작성 지침 |

## Bedrock Knowledge Base 구성 방법 (AWS 콘솔)

1. **S3 데이터 소스 준비**
   - S3 버킷/프리픽스에 이 폴더의 `.md` 파일들을 업로드
     (예: `s3://container-damage/knowledge-base/`)

2. **Knowledge Base 생성** (Bedrock 콘솔 → Knowledge bases → Create)
   - 데이터 소스: 위 S3 경로 지정
   - 임베딩 모델: `Titan Text Embeddings v2` 등 선택
   - 벡터 스토어: **OpenSearch Serverless**(콘솔이 자동 생성 옵션 제공) 또는 Aurora/Pinecone
   - 생성 후 **데이터 동기화(Sync)** 실행 → 문서가 색인됨

3. **Knowledge Base ID 확인**
   - 생성된 KB 상세 화면의 **Knowledge base ID** (예: `ABCDEFGHIJ`) 복사

4. **Lambda 환경변수 설정** (`report_generator`)
   - `KNOWLEDGE_BASE_ID=<위에서 복사한 ID>`
   - (선택) `KB_MAX_RESULTS=4` — 검색해 올 청크 수

5. **IAM 권한 추가** (Lambda 실행 역할)
   - `bedrock:Retrieve` (해당 Knowledge Base ARN 대상)

## 동작

- `KNOWLEDGE_BASE_ID` 가 설정되면, 보고서 생성 시 손상 정보로 질의를 만들어
  KB 에서 관련 양식/지침 청크를 검색하고, 그 내용을 프롬프트의 "참고 자료" 로
  넣어 Foundation Model 이 양식을 따르도록 유도한다.
- `KNOWLEDGE_BASE_ID` 가 없으면 RAG 없이 기존 방식으로 동작한다(선택 기능).

## 문서 갱신 시

양식/지침을 수정하면 S3 의 파일을 교체한 뒤 Knowledge Base 를 **다시 Sync** 하면
Lambda 코드 재배포 없이 반영된다.
