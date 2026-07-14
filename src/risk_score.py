"""Risk Score 계산 로직.

손상 유형별 가중치(구멍 >= 찌그러짐 > 녹슴), 손상 정도(severity), 탐지 신뢰도
(confidence)를 조합해 0~100 점수를 산출하고 HIGH/MEDIUM/LOW 로 등급화한다.

설계 원칙
---------
- 유형 가중치: 구멍(hole) >= 찌그러짐(dent) > 녹슴(rust)
  → 관통/구조적 손상일수록 위험, 표면 부식은 상대적으로 낮음.
- 단일 손상 점수 = 유형가중치 × 정도계수 × 신뢰도 × 100 (최대 100)
- 다중 손상 집계 = 가장 위험한 손상을 100% 반영하고, 나머지는 감쇠 계수를
  적용해 누적(하나의 심각한 손상이 여러 경미한 손상보다 위험하도록).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import SEVERITY_FACTORS, settings

# 추가 손상이 총점에 기여할 때 적용하는 감쇠 계수
_SECONDARY_DECAY = 0.4


@dataclass
class DamageItem:
    """모델이 판정한 손상 1건."""

    damage_type: str            # "hole" | "dent" | "rust"
    severity: str               # "low" | "medium" | "high"
    confidence: float = 1.0     # 0.0 ~ 1.0
    location: Optional[str] = None
    note: Optional[str] = None
    # 이미지 대비 퍼센트 bbox (대시보드 확대/오버레이용)
    box: Optional[Dict[str, float]] = None


@dataclass
class RiskResult:
    """Risk Score 산출 결과."""

    risk_score: float                 # 0 ~ 100
    risk_level: str                   # "HIGH" | "MEDIUM" | "LOW"
    components: List[Dict] = field(default_factory=list)  # 손상별 기여도 breakdown

    def to_dict(self) -> Dict:
        return {
            "risk_score": round(self.risk_score, 1),
            "risk_level": self.risk_level,
            "components": self.components,
        }


def _severity_factor(severity: Optional[str]) -> float:
    if not severity:
        return SEVERITY_FACTORS["medium"]
    return SEVERITY_FACTORS.get(severity.lower(), SEVERITY_FACTORS["medium"])


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _component_score(item: DamageItem) -> float:
    """단일 손상의 위험 점수(0~100)."""
    weight = settings.type_weights.get(item.damage_type.lower(), 0.0)
    sev = _severity_factor(item.severity)
    conf = _clamp01(item.confidence)
    return weight * sev * conf * 100.0


def _level_from_score(score: float) -> str:
    if score >= settings.threshold_high:
        return "HIGH"
    if score >= settings.threshold_medium:
        return "MEDIUM"
    return "LOW"


def calculate_risk(damages: List[DamageItem]) -> RiskResult:
    """손상 목록으로부터 Risk Score 와 등급을 계산한다."""
    if not damages:
        return RiskResult(risk_score=0.0, risk_level="LOW", components=[])

    scored = []
    for item in damages:
        scored.append((item, _component_score(item)))

    # 가장 위험한 손상부터 정렬 (지배 손상 우선 반영)
    scored.sort(key=lambda pair: pair[1], reverse=True)

    total = 0.0
    decay = 1.0
    components: List[Dict] = []
    for item, comp_score in scored:
        contribution = comp_score * decay
        total += contribution
        components.append(
            {
                "damage_type": item.damage_type,
                "severity": item.severity,
                "confidence": round(_clamp01(item.confidence), 3),
                "type_weight": settings.type_weights.get(item.damage_type.lower(), 0.0),
                "severity_factor": _severity_factor(item.severity),
                "component_score": round(comp_score, 1),
                "weighted_contribution": round(contribution, 1),
                "location": item.location,
            }
        )
        decay *= _SECONDARY_DECAY

    risk_score = min(total, 100.0)
    return RiskResult(
        risk_score=risk_score,
        risk_level=_level_from_score(risk_score),
        components=components,
    )
