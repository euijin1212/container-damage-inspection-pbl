"""knowledge_base.py — Amazon Bedrock Knowledge Base 검색(RAG) 래퍼.

역할
----
보고서 작성 시, 미리 색인해 둔 EIR 양식/작성 지침 문서를 Bedrock Knowledge Base
에서 검색(retrieve)해 관련 청크를 가져온다. 가져온 텍스트는 `report_writer` 가
프롬프트의 "참고 자료" 로 주입해 Foundation Model 이 양식을 따르도록 유도한다.

특징
----
- `KNOWLEDGE_BASE_ID` 가 비어 있으면 비활성(빈 리스트 반환) → RAG 없이 동작.
- 검색 실패(권한/네트워크 등)해도 예외를 던지지 않고 빈 리스트 반환 → 보고서
  생성이 멈추지 않는다.

API: bedrock-agent-runtime.retrieve
"""

from __future__ import annotations

from typing import List, Optional

import boto3

from .config import settings


class KnowledgeBaseRetriever:
    """Bedrock Knowledge Base 에서 관련 문서 청크를 검색한다."""

    def __init__(
        self,
        kb_id: Optional[str] = None,
        max_results: Optional[int] = None,
        client=None,
    ) -> None:
        self.kb_id = kb_id if kb_id is not None else settings.knowledge_base_id
        self.max_results = max_results or settings.kb_max_results
        self._client = client or boto3.client(
            "bedrock-agent-runtime", region_name=settings.bedrock_region
        )

    @property
    def enabled(self) -> bool:
        return bool(self.kb_id)

    def retrieve(self, query: str) -> List[str]:
        """질의와 관련된 문서 청크 텍스트 목록을 반환한다(실패 시 빈 리스트)."""
        if not self.enabled:
            return []
        try:
            resp = self._client.retrieve(
                knowledgeBaseId=self.kb_id,
                retrievalQuery={"text": query},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {"numberOfResults": self.max_results}
                },
            )
        except Exception as exc:  # noqa: BLE001 - RAG 실패가 보고서 생성을 막지 않도록
            print(f"[knowledge_base] 검색 실패, RAG 생략: {exc}")
            return []

        chunks: List[str] = []
        for item in resp.get("retrievalResults", []):
            text = (item.get("content") or {}).get("text")
            if text:
                chunks.append(text.strip())
        return chunks
