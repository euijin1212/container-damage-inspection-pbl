"""Bedrock Foundation Model 기반 손상 이미지 재분석기.

이미 bbox(손상 여부/구역)가 표시된 이미지를 입력받아, 비전 지원 Foundation
Model(예: Claude 3.5 Sonnet)로 손상 유형(구멍/찌그러짐/녹슴)과 손상 정도
(low/medium/high)를 판정한다. 결과는 Risk Score 계산이 그대로 소비할 수 있는
`DamageItem` 리스트로 변환된다.
"""

from __future__ import annotations

import json
import re
from typing import List, Optional

import boto3

from .config import DAMAGE_DENT, DAMAGE_HOLE, DAMAGE_RUST, settings
from .risk_score import DamageItem

# 유형 표기 정규화 (모델이 한글/유사어로 답해도 표준값으로 매핑)
_TYPE_ALIASES = {
    DAMAGE_HOLE: DAMAGE_HOLE,
    "구멍": DAMAGE_HOLE,
    "hole": DAMAGE_HOLE,
    "puncture": DAMAGE_HOLE,
    "perforation": DAMAGE_HOLE,
    DAMAGE_DENT: DAMAGE_DENT,
    "찌그러짐": DAMAGE_DENT,
    "dent": DAMAGE_DENT,
    "deformation": DAMAGE_DENT,
    "bent": DAMAGE_DENT,
    DAMAGE_RUST: DAMAGE_RUST,
    "녹슴": DAMAGE_RUST,
    "녹": DAMAGE_RUST,
    "rust": DAMAGE_RUST,
    "corrosion": DAMAGE_RUST,
}

_SEVERITY_ALIASES = {
    "low": "low",
    "경미": "low",
    "minor": "low",
    "medium": "medium",
    "중간": "medium",
    "moderate": "medium",
    "high": "high",
    "심각": "high",
    "severe": "high",
    "critical": "high",
}

_PROMPT = """당신은 항만 컨테이너 외관 검수 전문가입니다.
입력 이미지에는 이미 손상 의심 구역이 bounding box 로 표시되어 있습니다.
표시된 각 손상 구역을 분석하여 아래 JSON 형식으로만 답하세요. 설명 문장은 넣지 마세요.

손상 유형은 반드시 다음 중 하나로 분류합니다:
- "hole": 구멍/관통/천공
- "dent": 찌그러짐/변형/찍힘
- "rust": 녹슴/부식

손상 정도(severity)는 다음 중 하나입니다:
- "low": 경미 (표면적, 기능 영향 거의 없음)
- "medium": 중간 (눈에 띄는 손상)
- "high": 심각 (구조적/관통성 손상, 즉시 조치 필요)

출력 JSON 스키마:
{
  "damages": [
    {
      "type": "hole|dent|rust",
      "severity": "low|medium|high",
      "confidence": 0.0~1.0,
      "location": "상/중/하-좌/중/우 형식 (예: 하-우)",
      "note": "간단한 근거"
    }
  ]
}

손상이 없다고 판단되면 "damages": [] 로 반환하세요.
"""


def _normalize_type(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return _TYPE_ALIASES.get(value.strip().lower())


def _normalize_severity(value: Optional[str]) -> str:
    if not value:
        return "medium"
    return _SEVERITY_ALIASES.get(value.strip().lower(), "medium")


def _extract_json(text: str) -> dict:
    """모델 응답 텍스트에서 JSON 오브젝트를 추출한다."""
    text = text.strip()
    # ```json ... ``` 코드펜스 제거
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            text = brace.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"damages": []}


def _parse_damages(payload: dict) -> List[DamageItem]:
    items: List[DamageItem] = []
    for raw in payload.get("damages", []) or []:
        dtype = _normalize_type(raw.get("type"))
        if dtype is None:
            continue  # 표준 3유형에 해당하지 않으면 스킵
        try:
            confidence = float(raw.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        items.append(
            DamageItem(
                damage_type=dtype,
                severity=_normalize_severity(raw.get("severity")),
                confidence=confidence,
                location=raw.get("location"),
                note=raw.get("note"),
            )
        )
    return items


class BedrockDamageAnalyzer:
    """Bedrock 비전 모델로 손상 유형/정도를 판정한다."""

    def __init__(self, model_id: Optional[str] = None, client=None) -> None:
        self.model_id = model_id or settings.bedrock_model_id
        self._client = client or boto3.client(
            "bedrock-runtime", region_name=settings.bedrock_region
        )

    def analyze(self, image_bytes: bytes, image_format: str = "jpeg") -> List[DamageItem]:
        """이미지 1장을 분석해 손상 목록을 반환한다."""
        response = self._client.converse(
            modelId=self.model_id,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"text": _PROMPT},
                        {
                            "image": {
                                "format": image_format,
                                "source": {"bytes": image_bytes},
                            }
                        },
                    ],
                }
            ],
            inferenceConfig={"maxTokens": 1024, "temperature": 0.0},
        )
        text = self._extract_text(response)
        payload = _extract_json(text)
        return _parse_damages(payload)

    @staticmethod
    def _extract_text(response: dict) -> str:
        blocks = (
            response.get("output", {}).get("message", {}).get("content", [])
        )
        parts = [b.get("text", "") for b in blocks if "text" in b]
        return "\n".join(parts)
