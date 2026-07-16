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


class Stage1Detector:
    """1단계 손상 여부 탐지기 (ultralytics YOLO 래퍼)."""

    def __init__(self, model_path: str, conf: float = 0.15, imgsz: int = 896) -> None:
        from ultralytics import YOLO  # 무거운 import 는 여기서

        self.model = YOLO(model_path)
        self.conf = conf
        self.imgsz = imgsz

    def infer(self, image_path: str) -> EdgeResult:
        r = self.model.predict(image_path, conf=self.conf, imgsz=self.imgsz, verbose=False)[0]

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

        if detections:
            top = max(d.confidence for d in detections)
            return EdgeResult(EDGE_DAMAGE_SUSPECTED, round(top, 4), detections)
        return EdgeResult(EDGE_NORMAL, None, [])
