"""Risk Score 계산 로직.

가이드라인(대략):
  - 약간의 rust : 10~20
  - 심한 rust   : 30~40
  - 약간의 dent : 40~60
  - 심한 dent   : 70~80
  - hole        : 90 이상

Foundation Model 이 bbox 안에서 판정한
type / severity / extent 를 표로 매핑한 뒤 confidence 를 곱한다.
bbox 픽셀 면적은 쓰지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .config import DAMAGE_DENT, DAMAGE_HOLE, DAMAGE_RUST, settings

_SECONDARY_DECAY = 0.22

_EXTENT_RANK = {"small": 1, "medium": 2, "large": 3}
_SEV_RANK = {"low": 1, "medium": 2, "high": 3}

# (type, severity, extent) → 기준 점수 (confidence=1.0 일 때)
# 가이드라인 중간값에 맞춤
_BASE_SCORE: Dict[Tuple[str, str, str], float] = {
    # rust 10~20 / 30~40
    (DAMAGE_RUST, "low", "small"): 12.0,
    (DAMAGE_RUST, "low", "medium"): 16.0,
    (DAMAGE_RUST, "low", "large"): 20.0,
    (DAMAGE_RUST, "medium", "small"): 18.0,
    (DAMAGE_RUST, "medium", "medium"): 24.0,
    (DAMAGE_RUST, "medium", "large"): 30.0,
    (DAMAGE_RUST, "high", "small"): 26.0,
    (DAMAGE_RUST, "high", "medium"): 34.0,
    (DAMAGE_RUST, "high", "large"): 38.0,
    # dent 40~60 / 70~80
    (DAMAGE_DENT, "low", "small"): 42.0,
    (DAMAGE_DENT, "low", "medium"): 48.0,
    (DAMAGE_DENT, "low", "large"): 55.0,
    (DAMAGE_DENT, "medium", "small"): 48.0,
    (DAMAGE_DENT, "medium", "medium"): 55.0,
    (DAMAGE_DENT, "medium", "large"): 62.0,
    (DAMAGE_DENT, "high", "small"): 58.0,   # 심각해도 크기가 작으면 약간~중간
    (DAMAGE_DENT, "high", "medium"): 68.0,
    (DAMAGE_DENT, "high", "large"): 78.0,   # 심한 dent
    # hole ≥ 90
    (DAMAGE_HOLE, "low", "small"): 90.0,
    (DAMAGE_HOLE, "low", "medium"): 92.0,
    (DAMAGE_HOLE, "low", "large"): 94.0,
    (DAMAGE_HOLE, "medium", "small"): 92.0,
    (DAMAGE_HOLE, "medium", "medium"): 94.0,
    (DAMAGE_HOLE, "medium", "large"): 96.0,
    (DAMAGE_HOLE, "high", "small"): 94.0,
    (DAMAGE_HOLE, "high", "medium"): 97.0,
    (DAMAGE_HOLE, "high", "large"): 99.0,
}

_STRUCTURAL_NOTE_KEYS = (
    "프레임",
    "광범위",
    "구겨",
    "뒤틀",
    "접힘",
    "구조적",
    "패널 전체",
    "면 전체",
    "대면적",
    "심하게 찌그러",
    "crumpl",
    "buckl",
    "frame warp",
    "collapse",
    "warped",
)

_SMALL_NOTE_KEYS = (
    "국소",
    "찍힘",
    "점상",
    "작은",
    "소형",
    "미세",
    "얕은",
    "산발",
    "여러",
    "다수",
    "군데",
    "부분적",
    "경미",
)


@dataclass
class DamageItem:
    """모델이 판정한 손상 1건."""

    damage_type: str            # "hole" | "dent" | "rust"
    severity: str               # "low" | "medium" | "high"
    confidence: float = 1.0     # 0.0 ~ 1.0
    location: Optional[str] = None
    note: Optional[str] = None
    box: Optional[Dict[str, float]] = None
    extent: str = "medium"


@dataclass
class RiskResult:
    """Risk Score 산출 결과."""

    risk_score: float
    risk_level: str
    components: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "risk_score": round(self.risk_score, 1),
            "risk_level": self.risk_level,
            "components": self.components,
        }


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalize_type(damage_type: str) -> str:
    key = (damage_type or "").strip().lower()
    if key in (DAMAGE_HOLE, DAMAGE_DENT, DAMAGE_RUST):
        return key
    if key in ("damage", "unknown", "denting", ""):
        return DAMAGE_DENT
    if key in ("corrosion", "녹", "녹슴"):
        return DAMAGE_RUST
    if key in ("구멍", "puncture", "perforation"):
        return DAMAGE_HOLE
    return key


def _normalize_severity(severity: Optional[str]) -> str:
    if not severity:
        return "medium"
    v = severity.strip().lower()
    aliases = {
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
    return aliases.get(v, "medium")


def _normalize_extent(value: Optional[str], severity: str) -> str:
    if value:
        v = value.strip().lower()
        aliases = {
            "small": "small",
            "s": "small",
            "작음": "small",
            "소형": "small",
            "경미": "small",
            "medium": "medium",
            "m": "medium",
            "중간": "medium",
            "보통": "medium",
            "large": "large",
            "l": "large",
            "큼": "large",
            "대형": "large",
            "광범위": "large",
            "넓음": "large",
        }
        if v in aliases:
            return aliases[v]
    sev = _normalize_severity(severity)
    if sev == "high":
        return "large"
    if sev == "low":
        return "small"
    return "medium"


def _note_has(item: DamageItem, keys: tuple) -> bool:
    note = (item.note or "").lower()
    return any(k in note for k in keys)


def _resolve_band(item: DamageItem) -> Tuple[str, str, str]:
    """가이드라인 구간용 type/severity/extent 확정."""
    dtype = _normalize_type(item.damage_type)
    sev = _normalize_severity(item.severity)
    ext = _normalize_extent(item.extent, item.severity)

    if dtype == DAMAGE_DENT:
        if _note_has(item, _SMALL_NOTE_KEYS):
            # 약간의 dent
            if _SEV_RANK.get(sev, 0) >= 3:
                sev = "medium"
            ext = "small" if ext == "large" else ext
            if ext == "large":
                ext = "medium"
        elif _note_has(item, _STRUCTURAL_NOTE_KEYS):
            # 심한 dent (프레임 구김)
            sev, ext = "high", "large"

    if dtype == DAMAGE_RUST and _note_has(item, _STRUCTURAL_NOTE_KEYS + ("광범위", "심함", "심한")):
        if _SEV_RANK.get(sev, 0) < 3:
            sev = "high"
        if _EXTENT_RANK.get(ext, 0) < 3:
            ext = "large"

    return dtype, sev, ext


def _base_score_for(dtype: str, sev: str, ext: str) -> float:
    key = (dtype, sev, ext)
    if key in _BASE_SCORE:
        return _BASE_SCORE[key]
    # 폴백: 유형별 대략 중앙값
    fallback = {
        DAMAGE_HOLE: 94.0,
        DAMAGE_DENT: 55.0,
        DAMAGE_RUST: 20.0,
    }
    return float(fallback.get(dtype, 40.0))


def _type_weight(damage_type: str) -> float:
    """하위 호환(로그/컴포넌트용). 실제 점수는 가이드라인 표 사용."""
    key = _normalize_type(damage_type)
    configured = settings.type_weights.get(key)
    if configured is not None:
        return float(configured)
    return {"hole": 1.0, "dent": 0.7, "rust": 0.3}.get(key, 0.5)


def max_extent(a: Optional[str], b: Optional[str], severity: str = "medium") -> str:
    ea = _normalize_extent(a, severity)
    eb = _normalize_extent(b, severity)
    return ea if _EXTENT_RANK.get(ea, 0) >= _EXTENT_RANK.get(eb, 0) else eb


def _component_score(item: DamageItem) -> float:
    dtype, sev, ext = _resolve_band(item)
    base = _base_score_for(dtype, sev, ext)
    # confidence 영향은 약하게 (0.85~1.0 배)
    conf = _clamp01(item.confidence)
    conf_factor = 0.85 + 0.15 * conf
    return min(100.0, base * conf_factor)


def _level_from_score(score: float) -> str:
    if score >= settings.threshold_high:
        return "HIGH"
    if score >= settings.threshold_medium:
        return "MEDIUM"
    return "LOW"


def _severity_factor(severity: Optional[str]) -> float:
    return {"low": 0.35, "medium": 0.65, "high": 1.0}.get(
        _normalize_severity(severity), 0.65
    )


def _extent_factor(extent: Optional[str], severity: str = "medium") -> float:
    return {"small": 0.4, "medium": 0.7, "large": 1.0}.get(
        _normalize_extent(extent, severity), 0.7
    )


def calculate_risk(damages: List[DamageItem]) -> RiskResult:
    """손상 목록으로부터 Risk Score 와 등급을 계산한다."""
    if not damages:
        return RiskResult(risk_score=0.0, risk_level="LOW", components=[])

    scored = [(item, _component_score(item)) for item in damages]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    total = 0.0
    decay = 1.0
    components: List[Dict] = []
    for item, comp_score in scored:
        contribution = comp_score * decay
        total += contribution
        dtype, sev, ext = _resolve_band(item)
        components.append(
            {
                "damage_type": dtype,
                "severity": sev,
                "extent": ext,
                "confidence": round(_clamp01(item.confidence), 3),
                "type_weight": round(_type_weight(dtype), 3),
                "severity_factor": round(_severity_factor(sev), 3),
                "extent_factor": round(_extent_factor(ext, sev), 3),
                "base_score": round(_base_score_for(dtype, sev, ext), 1),
                "component_score": round(comp_score, 1),
                "weighted_contribution": round(contribution, 1),
                "location": item.location,
            }
        )
        # 부가 손상은 약하게만 가산 (주 손상이 가이드라인 유지)
        if dtype == DAMAGE_RUST or (dtype == DAMAGE_DENT and ext == "small"):
            decay *= 0.12
        else:
            decay *= _SECONDARY_DECAY

    return RiskResult(
        risk_score=min(total, 100.0),
        risk_level=_level_from_score(min(total, 100.0)),
        components=components,
    )
