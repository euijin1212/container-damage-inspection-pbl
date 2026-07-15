# Knowledge Base (RAG) 업로드 안내

## 왜 원본 PDF를 그대로 올리면 안 되나

해당 EIR PDF는 **페이지 전체가 이미지 1장**입니다.
Bedrock Knowledge Base는 텍스트가 없으면 Sync 시 아래처럼 무시합니다.

```text
Ignored 1 files as no text content found
```

그래서 **텍스트 가이드(`eir_writing_guide.md`)를 올리는 방식**을 씁니다.
원본 PDF URL은 가이드 문서 안에 참고 링크로만 남겨 두었습니다.

## S3 업로드

1. S3 → `container-damage` 버킷
2. prefix: `knowledge-base/eir/`
3. 업로드 파일:
   - `eir_writing_guide.md`  ← 필수 (RAG 본문)
   - (선택) 원본 PDF는 올려도 되지만 인덱싱되지 않을 수 있음

로컬 파일 위치:

```text
knowledge-base/eir/eir_writing_guide.md
```

## Knowledge Base Sync

1. Bedrock → Knowledge bases → 해당 KB
2. Data source → Sync
3. 결과 확인: **추가됨 ≥ 1**, Documents에 md 문서 표시
4. Test → Retrieve only → 질의 `EIR` 또는 `재사용 판정`

## report_generator 연결

환경변수:

```text
KNOWLEDGE_BASE_ID=<KB_ID>
KB_MAX_RESULTS=4
```

IAM:

```text
bedrock:Retrieve
bedrock:RetrieveAndGenerate
```
