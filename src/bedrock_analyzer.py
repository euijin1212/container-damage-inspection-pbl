"""Bedrock Foundation Model 기반 손상 이미지 재분석기.

이미 bbox(손상 여부/구역)가 표시된 이미지를 입력받아, 비전 지원 Foundation
Model(예: Claude 3.5 Sonnet)로 손상 유형(구멍/찌그러짐/녹슴)과 손상 정도
(low/medium/high)를 판정한다. 결과는 Risk Score 계산이 그대로 소비할 수 있는
`DamageItem` 리스트로 변환된다.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

import boto3

from .config import DAMAGE_DENT, DAMAGE_HOLE, DAMAGE_RUST, settings
from .risk_score import (
    DamageItem,
    max_extent,
    _normalize_extent,
    _SMALL_NOTE_KEYS,
    _STRUCTURAL_NOTE_KEYS,
)


@dataclass
class AnalysisResult:
    """비전 분석 결과: 손상 목록 + 전체 판단 근거."""

    damages: List[DamageItem]
    judgment_basis: str = ""

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
표시된 각 손상 구역을 분석하여 아래 JSON 형식으로만 답하세요.

손상 유형은 반드시 다음 중 하나로 분류합니다:
- "hole": 구멍/관통/천공
- "dent": 찌그러짐/변형/찍힘
- "rust": 녹슴/부식

손상 정도(severity)는 박스 안 손상의 위험도입니다:
- "low": 경미 (기능 영향 거의 없음)
- "medium": 중간 (눈에 띄는 손상)
- "high": 심각 (구조적/관통성, 즉시 조치 필요)

손상 크기(extent)는 박스 안에서 실제로 보이는 손상 범위·깊이입니다(박스 크기와 무관):
- "small": 국소·얕음·점상
- "medium": 중간 범위
- "large": 넓거나 깊은 손상, 패널 상당 부분·프레임/면 전체 구김

dent / hole 판정(중요):
- 관통이 없는 찍힘·함몰·딤플은 반드시 "dent" (hole 금지)
- hole 은 실제로 뚫린 구멍/관통만
- 박스 안 손상이 국소·작으면: severity "low" 또는 "medium", extent 반드시 "small"
- 산발적으로 여러 개 작은 dent 가 있어도 각각 extent "small" (large 로 올리지 말 것)
- 프레임·면 전체가 구겨지거나 뒤틀린 대형 찌그러짐만: severity "high" + extent "large"
- bbox 가 커도 안쪽 실제 함몰이 작으면 extent 는 "small"

출력 JSON 스키마:
{
  "overall_judgment": "사용하지 않음(서버가 damages 로 통일 포맷 생성). 빈 문자열 가능.",
  "damages": [
    {
      "type": "hole|dent|rust",
      "severity": "low|medium|high",
      "extent": "small|medium|large",
      "confidence": 0.0~1.0,
      "location": "상/중/하-좌/중/우 형식 (예: 하-우)",
      "note": "감지 결과 한 줄 요약. '위치/부위 + 손상 특징' 형식. 예: '녹색 컨테이너 하단부 광범위한 녹슬음과 부식, 페인트 박리'",
      "bbox_pct": {"x": 0, "y": 0, "width": 10, "height": 10}
    }
  ]
}

이미지에 표시된 기존 bounding box 구역만 분석하세요.
새 구역을 만들지 말고, 박스 안 손상의 유형·심각도·크기(extent)만 판정하세요.
bbox 픽셀 크기와 extent 를 혼동하지 마세요.

병합 규칙(중요):
- 네모(박스) 안·근처에서 유형(type)이 같고 위치가 가까우면 하나의 damages 로만 기록
- 인접한 녹 패치·연속 함몰·근접 구멍은 쪼개지 말고 대표 1건으로 묶기
- 묶을 때 severity/extent 는 가장 높은 값, bbox_pct 는 합친 영역, note 는 대표 한 줄 요약

각 damages[].note 규칙:
- 한국어 한 줄, 마침표 없이 명사구·짧은 구로 끝냄
- 구성: (색/대상 있으면) + 위치·부위 + 손상 양상(범위·형태·부가 징후)
- 길이 25~45자 내외. 예: '도어 하단 우측 관통 구멍과 주변 금속 찢김'
- 판정 문장·권고·유형명만 나열 금지
손상이 없으면 damages 는 [] 로 두고, overall_judgment 에 이상 없음 근거를 적으세요.
JSON 외 설명 문장은 넣지 마세요.
"""

_REINSPECT_PROMPT = """당신은 항만 컨테이너 외관 검수 전문가입니다.
이 이미지는 화질이 개선된 재검수용 사진입니다.
검수자 재검수 의견이 있으면 반드시 반영하여 각 박스 안 판정을 교정하세요.

중요 범위 제한:
- 아래에 주어진 기존 bounding box 구역 안의 손상만 분석하세요.
- 박스 밖의 영역은 무시하세요. 새 구역을 만들지 마세요.
- 박스 안에 유의미한 손상이 없으면 그 박스는 damages 에 넣지 마세요.

병합 규칙(초기 검수와 동일):
- 네모 안·근처에서 유형(type)이 같고 위치가 가까우면 하나의 damages 로만 기록
- 인접한 녹 패치·연속 함몰·근접 구멍은 쪼개지 말고 대표 1건으로 묶기
- 묶을 때 severity/extent 는 가장 높은 값, bbox_pct 는 합친 영역(또는 대표 박스), note 는 대표 한 줄
- box_index 는 묶음에 포함된 대표(가장 심각한) 박스 번호를 쓰세요

손상 유형은 반드시 다음 중 하나로 분류합니다:
- "hole": 구멍/관통/천공
- "dent": 찌그러짐/변형/찍힘
- "rust": 녹슴/부식

손상 정도(severity)는 박스 안 손상의 위험도입니다:
- "low": 경미
- "medium": 중간
- "high": 심각

손상 크기(extent)는 박스 안에서 실제로 보이는 손상 범위·깊이입니다(박스 픽셀 크기와 무관):
- "small": 국소·얕음·점상
- "medium": 중간 범위
- "large": 넓거나 깊은 손상·프레임/면 전체 구김

dent / hole:
- 관통 없는 찍힘·함몰은 "dent". hole 은 실제 관통만
- 국소·작은 dent → severity low/medium, extent "small" (여러 개여도 large 금지)
- 프레임·면 전체 구김·뒤틀림만 → severity "high" + extent "large"

출력 JSON 스키마만 반환하세요:
{
  "overall_judgment": "사용하지 않음(서버가 damages 로 통일 포맷 생성). 빈 문자열 가능.",
  "damages": [
    {
      "type": "hole|dent|rust",
      "severity": "low|medium|high",
      "extent": "small|medium|large",
      "confidence": 0.0~1.0,
      "location": "상/중/하-좌/중/우 형식 (예: 하-우)",
      "note": "감지 결과 한 줄 요약. '위치/부위 + 손상 특징' 형식. 예: '녹색 컨테이너 하단부 광범위한 녹슬음과 부식, 페인트 박리'",
      "bbox_pct": {"x": 0.0, "y": 0.0, "width": 10.0, "height": 10.0},
      "box_index": 1
    }
  ]
}

bbox_pct / box_index 는 이미지 전체 대비 퍼센트(0~100)인 기존 구역 목록을 따릅니다.
box_index 는 1부터 시작하는 기존 구역 번호입니다.

각 damages[].note 규칙:
- 한국어 한 줄, 마침표 없이 명사구·짧은 구로 끝냄
- 구성: (색/대상 있으면) + 위치·부위 + 손상 양상(범위·형태·부가 징후)
- 길이 25~45자 내외. 예: '측면 중앙 수직 골판 함몰과 도장 균열'
- 판정 문장·권고·유형명만 나열 금지
모든 박스에서 손상이 없으면 damages 는 [] 로 두세요.
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

        box = None
        bbox_pct = raw.get("bbox_pct") or raw.get("box")
        if isinstance(bbox_pct, dict):
            try:
                x = float(bbox_pct.get("x", 0))
                y = float(bbox_pct.get("y", 0))
                w = float(bbox_pct.get("width", 0))
                h = float(bbox_pct.get("height", 0))
                if w > 0 and h > 0:
                    box = {"x": x, "y": y, "width": w, "height": h}
            except (TypeError, ValueError):
                box = None

        note = raw.get("note")
        if isinstance(note, str):
            note = " ".join(note.split()).rstrip("。.!")
            # 감지 결과 카드용 한 줄 요약 (예: 하단부 광범위한 녹슬음과 부식, 페인트 박리)
            if len(note) > 60:
                note = note[:58].rstrip() + "…"

        severity = _normalize_severity(raw.get("severity"))
        extent = _normalize_extent(raw.get("extent"), severity)
        items.append(
            _adjust_dent_scale(
                DamageItem(
                    damage_type=dtype,
                    severity=severity,
                    confidence=confidence,
                    location=raw.get("location"),
                    note=note,
                    box=box,
                    extent=extent,
                )
            )
        )
    return items


def _adjust_dent_scale(item: DamageItem) -> DamageItem:
    """약간의 dent(40~60) vs 심한 dent(70~80) 구간이 맞게 severity/extent 보정."""
    if item.damage_type != DAMAGE_DENT:
        return item
    note = (item.note or "").lower()
    ext = _normalize_extent(item.extent, item.severity)

    # 국소·찍힘·산발 → 약간의 dent
    if any(k in note for k in _SMALL_NOTE_KEYS) or ext == "small":
        new_sev = "low" if _SEV_RANK.get(item.severity, 0) <= 1 else "medium"
        new_ext = "small" if ext != "medium" else "medium"
        if ext == "large":
            new_ext = "small"
        return DamageItem(
            damage_type=item.damage_type,
            severity=new_sev,
            confidence=item.confidence,
            location=item.location,
            note=item.note,
            box=item.box,
            extent=new_ext,
        )

    # 프레임·광범위 구김 → 심한 dent
    if any(k in note for k in _STRUCTURAL_NOTE_KEYS):
        return DamageItem(
            damage_type=item.damage_type,
            severity="high",
            confidence=item.confidence,
            location=item.location,
            note=item.note,
            box=item.box,
            extent="large",
        )
    return item


_SEV_KO = {"low": "경미", "medium": "보통", "high": "심각"}
_EXT_KO = {"small": "소형", "medium": "중형", "large": "대형"}
_TYPE_KO = {"hole": "구멍", "dent": "찌그러짐", "rust": "녹/부식"}
_SEV_RANK = {"low": 1, "medium": 2, "high": 3}
_V_MAP = {"상": 0, "중": 1, "하": 2, "top": 0, "mid": 1, "bottom": 2}
_H_MAP = {"좌": 0, "중": 1, "우": 2, "left": 0, "center": 1, "right": 2}


def _normalize_note(note: Optional[str]) -> Optional[str]:
    if not isinstance(note, str):
        return None
    text = " ".join(note.split()).rstrip("。.!")
    if not text:
        return None
    if len(text) > 60:
        text = text[:58].rstrip() + "…"
    return text


def _loc_cells(location: Optional[str]) -> Optional[tuple]:
    """'하-우' 등을 (v,h) 격자 좌표로. 파싱 실패 시 None."""
    if not location:
        return None
    s = str(location).strip().lower().replace(" ", "")
    for sep in ("-", "/", "_", ","):
        if sep in s:
            a, b = s.split(sep, 1)
            if a in _V_MAP and b in _H_MAP:
                return (_V_MAP[a], _H_MAP[b])
            if a in _H_MAP and b in _V_MAP:
                return (_V_MAP[b], _H_MAP[a])
    # 키워드만 있을 때: 중은 상·하 / 좌·우보다 우선순위 낮게
    v = next(( _V_MAP[k] for k in ("상", "하", "중") if k in s), None)
    h = next(( _H_MAP[k] for k in ("좌", "우", "중") if k in s), None)
    if v is not None and h is not None:
        return (v, h)
    return None


def _box_iou(a: Dict[str, float], b: Dict[str, float]) -> float:
    ax2, ay2 = a["x"] + a["width"], a["y"] + a["height"]
    bx2, by2 = b["x"] + b["width"], b["y"] + b["height"]
    ix1, iy1 = max(a["x"], b["x"]), max(a["y"], b["y"])
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = a["width"] * a["height"] + b["width"] * b["height"] - inter
    return inter / union if union > 0 else 0.0


def _box_center_dist(a: Dict[str, float], b: Dict[str, float]) -> float:
    ax = a["x"] + a["width"] / 2.0
    ay = a["y"] + a["height"] / 2.0
    bx = b["x"] + b["width"] / 2.0
    by = b["y"] + b["height"] / 2.0
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def _union_box(
    a: Optional[Dict[str, float]], b: Optional[Dict[str, float]]
) -> Optional[Dict[str, float]]:
    if a is None:
        return dict(b) if b else None
    if b is None:
        return dict(a)
    x1 = min(a["x"], b["x"])
    y1 = min(a["y"], b["y"])
    x2 = max(a["x"] + a["width"], b["x"] + b["width"])
    y2 = max(a["y"] + a["height"], b["y"] + b["height"])
    return {"x": x1, "y": y1, "width": max(0.0, x2 - x1), "height": max(0.0, y2 - y1)}


def _damages_nearby(
    a: DamageItem,
    b: DamageItem,
    *,
    iou_thr: float = 0.10,
    center_dist_thr: float = 28.0,
) -> bool:
    """같은 유형이면서 위치·박스가 가까우면 True."""
    if a.damage_type != b.damage_type:
        return False
    la, lb = _loc_cells(a.location), _loc_cells(b.location)
    if la is not None and lb is not None:
        dv, dh = abs(la[0] - lb[0]), abs(la[1] - lb[1])
        # 인접 칸, 또는 같은 가로/세로 띠(하단 전체 녹 등)
        if dv + dh <= 1 or (dv == 0 and dh <= 2) or (dh == 0 and dv <= 2):
            return True
    if a.box and b.box:
        if _box_iou(a.box, b.box) >= iou_thr:
            return True
        if _box_center_dist(a.box, b.box) <= center_dist_thr:
            return True
    # 박스 없고 location 문자열도 비슷하면 묶기
    if not a.box and not b.box:
        sa = (a.location or "").strip().lower()
        sb = (b.location or "").strip().lower()
        if sa and sa == sb:
            return True
    return False


def _merge_two(a: DamageItem, b: DamageItem) -> DamageItem:
    """두 손상을 1건으로. severity·extent·confidence 최대, bbox 합집합, note 대표 1줄."""
    if _SEV_RANK.get(b.severity, 0) > _SEV_RANK.get(a.severity, 0):
        primary, secondary = b, a
    else:
        primary, secondary = a, b
    note_a = _normalize_note(a.note)
    note_b = _normalize_note(b.note)
    note = None
    if note_a and note_b:
        note = note_a if len(note_a) >= len(note_b) else note_b
    else:
        note = note_a or note_b
    sev = primary.severity
    return DamageItem(
        damage_type=primary.damage_type,
        severity=sev,
        confidence=max(a.confidence, b.confidence),
        location=primary.location or secondary.location,
        note=note,
        box=_union_box(a.box, b.box),
        extent=max_extent(a.extent, b.extent, sev),
    )


def _pct_box_from_raw(raw: dict) -> Optional[Dict[str, float]]:
    bbox_pct = raw.get("bbox_pct") or raw.get("box")
    if not isinstance(bbox_pct, dict):
        return None
    try:
        x = float(bbox_pct.get("x", 0))
        y = float(bbox_pct.get("y", 0))
        w = float(bbox_pct.get("width", 0))
        h = float(bbox_pct.get("height", 0))
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return {"x": x, "y": y, "width": w, "height": h}


def constrain_damages_to_prior_boxes(
    payload: dict,
    damages: List[DamageItem],
    prior_boxes: List[Dict[str, float]],
) -> List[DamageItem]:
    """재검수 결과를 기존 bbox 에만 매핑. 박스 밖·신규 구역은 버린다."""
    if not prior_boxes:
        return merge_similar_damages(damages)

    assigned: Dict[int, DamageItem] = {}
    raw_list = list(payload.get("damages") or [])

    for i, raw in enumerate(raw_list):
        if not isinstance(raw, dict):
            continue
        dtype = _normalize_type(raw.get("type"))
        if dtype is None:
            continue

        idx: Optional[int] = None
        try:
            bi = int(raw.get("box_index"))
            if 1 <= bi <= len(prior_boxes):
                idx = bi - 1
        except (TypeError, ValueError):
            pass

        raw_box = _pct_box_from_raw(raw)
        if idx is None and raw_box is not None:
            best_j, best_iou = -1, 0.08
            for j, pb in enumerate(prior_boxes):
                iou = _box_iou(raw_box, pb)
                if iou > best_iou:
                    best_iou, best_j = iou, j
            if best_j >= 0:
                idx = best_j

        if idx is None and i < len(prior_boxes):
            idx = i

        if idx is None or idx < 0 or idx >= len(prior_boxes):
            continue

        try:
            confidence = float(raw.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        note = _normalize_note(raw.get("note") if isinstance(raw.get("note"), str) else None)
        severity = _normalize_severity(raw.get("severity"))
        cand = _adjust_dent_scale(
            DamageItem(
                damage_type=dtype,
                severity=severity,
                confidence=confidence,
                location=raw.get("location"),
                note=note,
                box=dict(prior_boxes[idx]),
                extent=_normalize_extent(raw.get("extent"), severity),
            )
        )
        prev = assigned.get(idx)
        if prev is None:
            assigned[idx] = cand
        elif cand.damage_type == prev.damage_type:
            assigned[idx] = _merge_two(prev, cand)
        elif _SEV_RANK.get(cand.severity, 0) > _SEV_RANK.get(prev.severity, 0):
            assigned[idx] = cand

    if assigned:
        return [assigned[k] for k in sorted(assigned)]

    # 모델이 좌표를 안 맞춘 경우: 파싱된 damages 를 순서대로 prior 에 스냅
    out: List[DamageItem] = []
    for i, d in enumerate(damages):
        if i >= len(prior_boxes):
            break
        out.append(
            _adjust_dent_scale(
                DamageItem(
                    damage_type=d.damage_type,
                    severity=d.severity,
                    confidence=d.confidence,
                    location=d.location,
                    note=_normalize_note(d.note),
                    box=dict(prior_boxes[i]),
                    extent=_normalize_extent(d.extent, d.severity),
                )
            )
        )
    return out


def merge_similar_damages(
    damages: List[DamageItem],
    *,
    max_items: int = 5,
) -> List[DamageItem]:
    """같은 유형·가까운 위치 손상을 묶는다(초기 검수·재검수 공통)."""
    if len(damages) <= 1:
        return list(damages)

    # 위험도 높은 것부터 시드
    ordered = sorted(
        damages,
        key=lambda d: (_SEV_RANK.get(d.severity, 0), d.confidence),
        reverse=True,
    )
    clusters: List[DamageItem] = []
    for item in ordered:
        merged = False
        for i, c in enumerate(clusters):
            if _damages_nearby(c, item):
                clusters[i] = _merge_two(c, item)
                merged = True
                break
        if not merged:
            clusters.append(item)

    # 여전히 많으면 같은 유형끼리 추가 병합
    while len(clusters) > max_items:
        best_i = best_j = -1
        best_dist = 1e9
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                a, b = clusters[i], clusters[j]
                if a.damage_type != b.damage_type:
                    continue
                if a.box and b.box:
                    dist = _box_center_dist(a.box, b.box)
                else:
                    dist = 0.0 if _damages_nearby(a, b) else 50.0
                if dist < best_dist:
                    best_dist, best_i, best_j = dist, i, j
        if best_i < 0:
            # 유형이 모두 다르면 위험도 낮은 것부터 제거
            clusters.sort(
                key=lambda d: (_SEV_RANK.get(d.severity, 0), d.confidence),
                reverse=True,
            )
            clusters = clusters[:max_items]
            break
        merged = _merge_two(clusters[best_i], clusters[best_j])
        clusters = [
            c for k, c in enumerate(clusters) if k not in (best_i, best_j)
        ] + [merged]

    return clusters


def format_judgment_basis(damages: List[DamageItem]) -> str:
    """초기 분석·재검수 공통 AI 판단 근거 포맷."""
    if not damages:
        return (
            "이미지에서 구멍·찌그러짐·녹 등 유의미한 외관 손상이 확인되지 않았습니다.\n"
            "현재 탐지 결과만으로는 구조적 위험이 낮아 보이며, 이상 징후가 없습니다."
        )
    parts = []
    for i, d in enumerate(damages, 1):
        t = _TYPE_KO.get(d.damage_type, d.damage_type)
        s = _SEV_KO.get(d.severity, d.severity)
        e = _EXT_KO.get(_normalize_extent(d.extent, d.severity), d.extent)
        loc = (d.location or "위치 미상").strip()
        note = " ".join((d.note or "").split()).strip()
        if note:
            parts.append(f"{i}) {loc} — {t}({s}/{e}): {note}")
        else:
            parts.append(f"{i}) {loc} — {t}({s}/{e}) 확인")
    return (
        f"총 {len(damages)}건의 손상이 탐지되었습니다.\n"
        + "\n".join(parts)
        + "\n유형·크기·정도를 종합하면 수동 검수로 최종 확인하는 것이 적절합니다."
    )


def _extract_judgment(payload: dict, damages: List[DamageItem]) -> str:
    """모델 자유 서술 대신 손상 목록으로 통일 포맷을 만든다."""
    # overall_judgment 는 참고만 하고, 화면 포맷은 항상 damages 기준으로 맞춤
    _ = payload
    return format_judgment_basis(damages)[:1200]


# 하위 호환
_fallback_judgment = format_judgment_basis


class BedrockDamageAnalyzer:
    """Bedrock 비전 모델로 손상 유형/정도를 판정한다."""

    def __init__(self, model_id: Optional[str] = None, client=None) -> None:
        self.model_id = model_id or settings.bedrock_model_id
        if client is not None:
            self._client = client
        else:
            # Lambda 타임아웃(예: 90s) 전에 ReadTimeout 으로 실패시켜
            # DynamoDB 실패 저장이 실행되도록 한다 (RUNNING 고착 방지)
            from botocore.config import Config

            cfg = Config(
                connect_timeout=10,
                read_timeout=int(os.getenv("BEDROCK_READ_TIMEOUT", "55")),
                retries={"max_attempts": 2, "mode": "standard"},
            )
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=settings.bedrock_region,
                config=cfg,
            )

    def analyze(
        self,
        image_bytes: bytes,
        image_format: str = "jpeg",
        reviewer_note: Optional[str] = None,
        *,
        reinspect: bool = False,
        prior_boxes: Optional[List[Dict[str, float]]] = None,
    ) -> AnalysisResult:
        """이미지 1장을 분석해 손상 목록 + 전체 판단 근거를 반환한다.

        reviewer_note 가 있으면 검수자 재검수 의견으로 프롬프트에 포함한다.
        reinspect=True 이면 기존 bbox(prior_boxes) 안만 재판정한다.
        """
        boxes = [b for b in (prior_boxes or []) if isinstance(b, dict)]
        base = _REINSPECT_PROMPT if reinspect else _PROMPT
        prompt = base
        if reinspect and boxes:
            lines = []
            for i, b in enumerate(boxes, 1):
                lines.append(
                    f'{i}) {{"x": {b.get("x", 0)}, "y": {b.get("y", 0)}, '
                    f'"width": {b.get("width", 0)}, "height": {b.get("height", 0)}}}'
                )
            prompt = (
                f"{base}\n\n"
                "=== 분석 대상 기존 bounding box (이미지 대비 %, 이 구역만) ===\n"
                + "\n".join(lines)
                + "\n위 구역 밖은 분석하지 마세요.\n"
            )
        note = (reviewer_note or "").strip()
        if note:
            prompt = (
                f"{prompt}\n\n"
                "=== 검수자 재검수 의견 (반드시 참고) ===\n"
                f"{note}\n"
                "위 의견을 반영해 각 박스 안 손상의 유형·정도·요약만 다시 판정하세요. "
                "박스 밖 손상은 기록하지 마세요.\n"
            )

        fmt = (image_format or "jpeg").lower()
        if fmt == "jpg":
            fmt = "jpeg"

        response = self._client.converse(
            modelId=self.model_id,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"text": prompt},
                        {
                            "image": {
                                "format": fmt,
                                "source": {"bytes": image_bytes},
                            }
                        },
                    ],
                }
            ],
            inferenceConfig={"maxTokens": 2048, "temperature": 0.0},
        )
        text = self._extract_text(response)
        payload = _extract_json(text)
        damages = _parse_damages(payload)
        # 재검수: 기존 bbox 안으로 스냅한 뒤, 초기와 동일하게 유사·근접 병합
        if reinspect and boxes:
            damages = constrain_damages_to_prior_boxes(payload, damages, boxes)
        damages = merge_similar_damages(damages)
        for d in damages:
            d.note = _normalize_note(d.note)
        # 감지 결과·AI 판단 근거: 초기/재검수 동일 포맷
        return AnalysisResult(
            damages=damages,
            judgment_basis=format_judgment_basis(damages)[:1200],
        )

    @staticmethod
    def _extract_text(response: dict) -> str:
        blocks = (
            response.get("output", {}).get("message", {}).get("content", [])
        )
        parts = [b.get("text", "") for b in blocks if "text" in b]
        return "\n".join(parts)
