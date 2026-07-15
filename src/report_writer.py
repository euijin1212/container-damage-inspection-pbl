"""report_writer.py — Bedrock 기반 EIR(컨테이너 검수 보고서) 초안 생성기.

역할
----
검수가 완료된(`review_status = DONE`) DynamoDB 검수 이벤트 1건을 입력받아,
Foundation Model(Sonnet 4.5)로 사람이 읽을 수 있는 EIR 보고서 초안을 작성한다.
결과는 PDF 렌더러(`pdf_report.py`)가 그대로 소비할 수 있는 구조화된 dict 다.

설계
----
- 모델에는 검수 레코드의 핵심 필드만 JSON 으로 전달한다(토큰 절약·환각 방지).
- (RAG) Bedrock Knowledge Base 가 설정돼 있으면, EIR 양식/작성 지침을 검색해
  프롬프트의 "참고 자료" 로 주입한다(`knowledge_base.py`). 미설정 시 생략.
- 모델은 정해진 JSON 스키마(summary/damage_assessment/recommended_action/
  reuse_decision/reuse_reason)로만 답하도록 강제한다.
- 모델 호출이 실패하거나 파싱이 깨져도 보고서 생성이 멈추지 않도록,
  레코드 값만으로 만드는 결정론적 폴백(`_fallback_report`)을 항상 제공한다.

입력: 검수 이벤트 dict (data-schema.md 의 최종 저장 item)
출력: 보고서 섹션 dict
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

import boto3

from .config import settings
from .knowledge_base import KnowledgeBaseRetriever
from .record_adapter import normalize_inspection_record

# 모델이 반드시 선택해야 하는 재사용 판정값 (표준값)
REUSE_USABLE = "USABLE"          # 재사용 가능 (경미/무손상)
REUSE_REPAIR = "REPAIR_NEEDED"   # 수리 후 재사용
REUSE_REJECT = "REJECT"          # 사용 불가 (반출/폐기)

_REUSE_ALIASES = {
    "usable": REUSE_USABLE,
    "ok": REUSE_USABLE,
    "reuse": REUSE_USABLE,
    "재사용": REUSE_USABLE,
    "repair_needed": REUSE_REPAIR,
    "repair": REUSE_REPAIR,
    "수리": REUSE_REPAIR,
    "reject": REUSE_REJECT,
    "폐기": REUSE_REJECT,
    "unusable": REUSE_REJECT,
}

# 보고서에 실제로 넘길 레코드 필드 (그 외는 프롬프트에서 제외)
_RECORD_FIELDS = (
    "event_id",
    "container_id",
    "captured_at",
    "processed_at",
    "inspection_result",
    "detection_count",
    "detections",
    "risk_score",
    "risk_level",
    "location",
    "model_version",
)

_PROMPT_TEMPLATE = """당신은 항만 EIR(Equipment Interchange Receipt) 전표 작성 담당자입니다.
아래 검수 결과 JSON 과 참고 양식 지침을 근거로, EIR 전표의 Remarks/판정란에 들어갈 문구만 작성하세요.
{reference_block}
규칙:
- 참고 자료가 있으면 그 양식 항목·문체·판정 기준을 따릅니다.
- 반드시 아래 JSON 스키마로만 답합니다. 코드펜스/설명 문장은 넣지 마세요.
- 서술 필드는 한국어, EIR 전표 톤(짧고 사실만). 각 1~3문장.
- 근거 없는 손상을 지어내지 마세요. 제공된 detections 만 사용합니다.
- confidence, 모델명, 내부 점수를 본문에 쓰지 마세요.
- reuse_decision:
  · USABLE: 무손상 또는 경미(low) 위주
  · REPAIR_NEEDED: 수리 후 재사용
  · REJECT: 관통/구조적(high) 등으로 사용 불가

출력 JSON 스키마:
{{
  "summary": "EIR Remarks용 상태 요약 (전표 메모 스타일)",
  "damage_assessment": "손상 위치·유형·정도에 대한 짧은 평가",
  "recommended_action": "인수/수리/반출 등 권고 조치 한두 문장",
  "reuse_decision": "USABLE|REPAIR_NEEDED|REJECT",
  "reuse_reason": "Disposition 판정 근거 한두 문장"
}}

검수 결과 JSON:
{record_json}
"""

# 참고 자료(RAG)가 있을 때 프롬프트에 끼워 넣는 블록
_REFERENCE_BLOCK = """
다음은 보고서 양식/작성 지침 참고 자료입니다. 이 양식을 따라 작성하세요:
---
{reference}
---
"""


def _pick_record(record: Dict) -> Dict:
    """프롬프트에 넣을 핵심 필드만 추린다 (MVP 중첩 스키마 지원)."""
    flat = normalize_inspection_record(record)
    return {k: flat.get(k) for k in _RECORD_FIELDS if flat.get(k) is not None}


def _extract_json(text: str) -> Optional[dict]:
    """모델 응답 텍스트에서 JSON 오브젝트를 추출한다."""
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            text = brace.group(0)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _normalize_reuse(value: Optional[str], record: Dict) -> str:
    """재사용 판정값을 표준값으로 정규화하고, 없으면 risk_level 로 추정한다."""
    if value:
        mapped = _REUSE_ALIASES.get(str(value).strip().lower())
        if mapped:
            return mapped
    level = str(record.get("risk_level", "LOW")).upper()
    if level == "HIGH":
        return REUSE_REJECT
    if level == "MEDIUM":
        return REUSE_REPAIR
    return REUSE_USABLE


def _damage_phrase(record: Dict) -> str:
    detections: List[Dict] = record.get("detections") or []
    if not detections:
        return "탐지된 손상 없음"
    return ", ".join(
        f"{d.get('class', '?')}/{d.get('severity', '?')}"
        + (f"({d.get('location')})" if d.get("location") else "")
        for d in detections
    )


def _fallback_report(record: Dict) -> Dict:
    """모델 호출/파싱 실패 시 레코드 값만으로 만드는 결정론적 보고서."""
    reuse = _normalize_reuse(None, record)
    count = record.get("detection_count", 0)
    score = record.get("risk_score", 0)
    level = record.get("risk_level", "LOW")
    phrase = _damage_phrase(record)
    action = {
        REUSE_USABLE: "추가 조치 없이 재사용 가능합니다.",
        REUSE_REPAIR: "재사용 전 해당 손상 부위 수리를 권고합니다.",
        REUSE_REJECT: "구조적 손상으로 재사용을 보류하고 별도 반출/정비 절차가 필요합니다.",
    }[reuse]
    return {
        "summary": f"손상 {count}건 탐지, 위험도 {level}(점수 {score}). 손상 내역: {phrase}.",
        "damage_assessment": f"자동 분석 기준 대표 위치 {record.get('location') or 'N/A'}, "
        f"탐지 손상: {phrase}.",
        "recommended_action": action,
        "reuse_decision": reuse,
        "reuse_reason": f"위험 등급 {level} 기준 자동 판정(모델 서술 생성 실패로 규칙 기반 대체).",
        "generated_by": "fallback",
    }


def _build_query(record: Dict) -> str:
    """검수 레코드로부터 Knowledge Base 검색 질의를 만든다."""
    types = {
        d.get("class")
        for d in (record.get("detections") or [])
        if d.get("class")
    }
    type_str = ", ".join(sorted(types)) if types else "무손상"
    level = record.get("risk_level", "LOW")
    return (
        "컨테이너 검수 보고서(EIR) 작성 양식과 지침. "
        f"손상 유형: {type_str}. 위험 등급: {level}. 재사용 판정 기준."
    )


class BedrockReportWriter:
    """Bedrock 텍스트 모델로 EIR 보고서 초안을 작성한다(선택적 RAG)."""

    def __init__(
        self,
        model_id: Optional[str] = None,
        client=None,
        retriever: Optional[KnowledgeBaseRetriever] = None,
    ) -> None:
        self.model_id = model_id or settings.bedrock_model_id
        self._client = client or boto3.client(
            "bedrock-runtime", region_name=settings.bedrock_region
        )
        # Knowledge Base 미설정이면 retriever.enabled=False → RAG 자동 생략
        self._retriever = retriever if retriever is not None else KnowledgeBaseRetriever()

    def _reference_block(self, record: Dict) -> str:
        """RAG 로 참고 자료를 검색해 프롬프트 블록을 만든다(없으면 빈 문자열)."""
        if not self._retriever.enabled:
            return ""
        chunks = self._retriever.retrieve(_build_query(record))
        if not chunks:
            return ""
        joined = "\n\n".join(chunks)
        return _REFERENCE_BLOCK.format(reference=joined)

    def write(self, record: Dict) -> Dict:
        """검수 레코드 1건으로 보고서 섹션 dict 를 생성한다.

        모델 호출/파싱 실패 시에도 예외를 던지지 않고 폴백 보고서를 반환한다.
        """
        flat = normalize_inspection_record(record)
        prompt = _PROMPT_TEMPLATE.format(
            reference_block=self._reference_block(flat),
            record_json=json.dumps(_pick_record(record), ensure_ascii=False, indent=2),
        )
        try:
            response = self._client.converse(
                modelId=self.model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 1500, "temperature": 0.2},
            )
            payload = _extract_json(self._extract_text(response))
        except Exception as exc:  # noqa: BLE001 - 보고서 생성이 멈추지 않도록 폴백
            print(f"[report_writer] Bedrock 호출 실패, 폴백 사용: {exc}")
            payload = None

        if not payload:
            return _fallback_report(flat)

        return {
            "summary": payload.get("summary") or _fallback_report(flat)["summary"],
            "damage_assessment": payload.get("damage_assessment", ""),
            "recommended_action": payload.get("recommended_action", ""),
            "reuse_decision": _normalize_reuse(payload.get("reuse_decision"), flat),
            "reuse_reason": payload.get("reuse_reason", ""),
            "generated_by": self.model_id,
        }

    @staticmethod
    def _extract_text(response: dict) -> str:
        blocks = response.get("output", {}).get("message", {}).get("content", [])
        return "\n".join(b.get("text", "") for b in blocks if "text" in b)
