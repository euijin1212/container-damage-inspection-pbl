"""infer.py — 1단계(손상 여부) YOLO 추론.

Simulator 내부에서 실행되어 이미지 1장의 손상 여부/bbox/신뢰도를 만든다.
- 탐지 0건  → NORMAL
- 탐지 1건+ → DAMAGE_SUSPECTED (+ edge_detections)

데이터 스키마의 `edge.*` 필드를 채우는 근거 값을 생성한다 (docs/data-schema.md §5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# edge.edge_status 표준값
EDGE_NORMAL = "NORMAL"
EDGE_DAMAGE_SUSPECTED = "DAMAGE_SUSPECTED"


@dataclass
class Detection:
    damage_class: str            # 1클래스 모델이면 "damage"
    confidence: float
    bbox: dict                   # {x_min, y_min, x_max, y_max}


@dataclass
class EdgeResult:
    status: str                  # NORMAL | DAMAGE_SUSPECTED
    confidence: Optional[float]  # 대표(최대) 신뢰도, NORMAL 이면 None
    detections: List[Detection] = field(default_factory=list)


# ---- bbox 정리(중복/중첩 제거) 헬퍼 ----
def _area(b: dict) -> float:
    return max(0, b["x_max"] - b["x_min"]) * max(0, b["y_max"] - b["y_min"])


def _inter(a: dict, b: dict) -> float:
    x1, y1 = max(a["x_min"], b["x_min"]), max(a["y_min"], b["y_min"])
    x2, y2 = min(a["x_max"], b["x_max"]), min(a["y_max"], b["y_max"])
    return max(0, x2 - x1) * max(0, y2 - y1)


def _iou(a: dict, b: dict) -> float:
    inter = _inter(a, b)
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0 else 0.0


def _contain(a: dict, b: dict) -> float:
    """교집합 / 작은 박스 면적 → 한 박스가 다른 박스에 얼마나 포함되는지."""
    inter = _inter(a, b)
    small = min(_area(a), _area(b))
    return inter / small if small > 0 else 0.0


def _dedup(dets: List[Detection], iou_thr: float = 0.5, contain_thr: float = 0.85) -> List[Detection]:
    """신뢰도 높은 순으로 유지하되, 겹치거나(IoU) 포함되는(containment) 박스는 버린다."""
    kept: List[Detection] = []
    for d in sorted(dets, key=lambda x: x.confidence, reverse=True):
        if all(
            _iou(d.bbox, k.bbox) < iou_thr and _contain(d.bbox, k.bbox) < contain_thr
            for k in kept
        ):
            kept.append(d)
    return kept


class Stage1Detector:
    """1단계 손상 여부 탐지기 (ultralytics YOLO 래퍼)."""

    def __init__(self, model_path: str, conf: float = 0.15, imgsz: int = 896, iou: float = 0.45) -> None:
        from ultralytics import YOLO  # 무거운 import 는 여기서

        self.model = YOLO(model_path)
        self.conf = conf
        self.imgsz = imgsz
        self.iou = iou  # NMS IoU 임계값(낮을수록 겹치는 박스 더 억제)

    def infer(self, image_path: str) -> EdgeResult:
        r = self.model.predict(
            image_path, conf=self.conf, imgsz=self.imgsz, iou=self.iou, verbose=False
        )[0]

        detections: List[Detection] = []
        for b in r.boxes:
            x1, y1, x2, y2 = (int(v) for v in b.xyxy[0].tolist())
            cls_id = int(b.cls)
            detections.append(
                Detection(
                    damage_class=self.model.names[cls_id],
                    confidence=round(float(b.conf), 4),
                    bbox={"x_min": x1, "y_min": y1, "x_max": x2, "y_max": y2},
                )
            )

        detections = _dedup(detections)  # 중복/중첩 박스 정리

        if detections:
            top = max(d.confidence for d in detections)
            return EdgeResult(EDGE_DAMAGE_SUSPECTED, round(top, 4), detections)
        return EdgeResult(EDGE_NORMAL, None, [])
