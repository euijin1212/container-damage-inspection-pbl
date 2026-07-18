"""재검수(Foundation Model 재분석) 공통 실행 로직.

1) Nova Canvas 등으로 이미지 화질 개선
2) 개선본 + 검수 의견으로 손상 재감지
3) DynamoDB 갱신 필드 반환 (항상 MANUAL_NEEDED)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .bedrock_analyzer import BedrockDamageAnalyzer
from .bedrock_image_enhance import BedrockImageEnhancer
from .risk_score import calculate_risk
from .s3_client import S3ImageStore

_analyzer = BedrockDamageAnalyzer()
_enhancer = BedrockImageEnhancer()
_store = S3ImageStore()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _image_size(body: bytes, image_format: str) -> Tuple[Optional[int], Optional[int]]:
    try:
        fmt = (image_format or "").lower()
        if fmt in ("jpeg", "jpg") and body[:2] == b"\xff\xd8":
            i = 2
            while i < len(body) - 8:
                if body[i] != 0xFF:
                    i += 1
                    continue
                marker = body[i + 1]
                if marker in (0xC0, 0xC1, 0xC2):
                    h = int.from_bytes(body[i + 5 : i + 7], "big")
                    w = int.from_bytes(body[i + 7 : i + 9], "big")
                    return w, h
                if marker == 0xD9:
                    break
                length = int.from_bytes(body[i + 2 : i + 4], "big")
                i += 2 + length
        if fmt == "png" and body[:8] == b"\x89PNG\r\n\x1a\n":
            w = int.from_bytes(body[16:20], "big")
            h = int.from_bytes(body[20:24], "big")
            return w, h
    except Exception:  # noqa: BLE001
        pass
    return None, None


def _pixel_bbox_to_pct(
    bbox: Dict, img_w: Optional[int], img_h: Optional[int]
) -> Optional[Dict]:
    try:
        x_min = float(bbox["x_min"])
        y_min = float(bbox["y_min"])
        x_max = float(bbox["x_max"])
        y_max = float(bbox["y_max"])
    except (KeyError, TypeError, ValueError):
        return None
    if not img_w or not img_h or x_max <= x_min or y_max <= y_min:
        return None
    return {
        "x": round(x_min / img_w * 100.0, 2),
        "y": round(y_min / img_h * 100.0, 2),
        "width": round((x_max - x_min) / img_w * 100.0, 2),
        "height": round((y_max - y_min) / img_h * 100.0, 2),
    }


def _normalize_pct_box(raw: Dict) -> Optional[Dict[str, float]]:
    """cloud detection.box / bbox_pct → {x,y,width,height} %."""
    try:
        x = float(raw.get("x", 0))
        y = float(raw.get("y", 0))
        w = float(raw.get("width", 0))
        h = float(raw.get("height", 0))
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    # 0~1 비율로 온 경우 % 로 변환
    if x <= 1 and y <= 1 and w <= 1 and h <= 1:
        x, y, w, h = x * 100.0, y * 100.0, w * 100.0, h * 100.0
    return {
        "x": round(x, 2),
        "y": round(y, 2),
        "width": round(w, 2),
        "height": round(h, 2),
    }


def collect_prior_boxes(
    *,
    cloud_detections: Optional[List] = None,
    edge_detections: Optional[List] = None,
    img_w: Optional[int] = None,
    img_h: Optional[int] = None,
) -> List[Dict[str, float]]:
    """재검수 시 분석할 기존 bbox 목록(이미지 대비 %).

    대시보드에 보이는 cloud detections 를 우선하고, 없으면 edge YOLO bbox 사용.
    """
    boxes: List[Dict[str, float]] = []
    seen = set()

    def _add(box: Optional[Dict[str, float]]) -> None:
        if not box:
            return
        key = (
            round(box["x"], 1),
            round(box["y"], 1),
            round(box["width"], 1),
            round(box["height"], 1),
        )
        if key in seen:
            return
        seen.add(key)
        boxes.append(box)

    for d in cloud_detections or []:
        if not isinstance(d, dict):
            continue
        pct = None
        if isinstance(d.get("box"), dict):
            pct = _normalize_pct_box(d["box"])
        elif isinstance(d.get("bbox_pct"), dict):
            pct = _normalize_pct_box(d["bbox_pct"])
        elif isinstance(d.get("bbox"), dict):
            pct = _pixel_bbox_to_pct(d["bbox"], img_w, img_h)
        _add(pct)

    if boxes:
        return boxes

    for d in edge_detections or []:
        if not isinstance(d, dict):
            continue
        bbox = d.get("bbox")
        if isinstance(bbox, dict):
            _add(_pixel_bbox_to_pct(bbox, img_w, img_h))
    return boxes


def _event_id_from_key(key: str) -> str:
    stem = key.rsplit("/", 1)[-1]
    return stem.rsplit(".", 1)[0] or "unknown"


def build_reinspect_success_fields(
    *,
    damages: List,
    risk: Any,
    model_id: str,
    bucket: str,
    key: str,
    edge_detections: Optional[List] = None,
    img_w: Optional[int] = None,
    img_h: Optional[int] = None,
    reviewer_note: str = "",
    reviewer: str = "dashboard",
    enhanced_image_key: Optional[str] = None,
    enhance_model_id: Optional[str] = None,
    enhance_fallback: bool = False,
    judgment_basis: str = "",
) -> Dict[str, Any]:
    edge_detections = edge_detections or []
    detections = []
    for i, d in enumerate(damages):
        det: Dict[str, Any] = {
            "damage_class": d.damage_type,
            "severity": d.severity,
            "location": d.location,
            "description": d.note,
            "confidence": round(float(d.confidence), 3),
        }
        if d.box:
            det["box"] = d.box
        elif edge_detections:
            edge_d = edge_detections[i % len(edge_detections)]
            if isinstance(edge_d, dict) and isinstance(edge_d.get("bbox"), dict):
                pct = _pixel_bbox_to_pct(edge_d["bbox"], img_w, img_h)
                if pct:
                    det["box"] = pct
                else:
                    det["bbox"] = edge_d["bbox"]
        detections.append(det)

    review_status = "MANUAL_NEEDED"
    note = (reviewer_note or "").strip()
    image_meta: Dict[str, Any] = {
        "bucket": bucket,
        "raw_image_key": key,
    }
    if img_w and img_h:
        image_meta["width"] = int(img_w)
        image_meta["height"] = int(img_h)
    if enhanced_image_key:
        image_meta["enhanced_image_key"] = enhanced_image_key

    cloud: Dict[str, Any] = {
        "analysis_status": "COMPLETED",
        "model_name": model_id,
        "inspection_result": "damage" if damages else "normal",
        "detection_count": len(detections),
        "detections": detections,
        "reinspect": True,
        "image_enhanced": bool(enhanced_image_key) and not enhance_fallback,
        "enhance_fallback": enhance_fallback,
    }
    basis = (judgment_basis or "").strip()
    if basis:
        cloud["judgment_basis"] = basis[:1200]
    if enhance_model_id:
        cloud["enhance_model"] = enhance_model_id
    if note:
        cloud["reinspect_note"] = note[:500]

    return {
        "processed_at": _now_iso(),
        "reviewed_at": _now_iso(),
        "reviewer": reviewer,
        "review_memo": note[:1000] if note else "재검수 요청",
        "cloud_analysis": cloud,
        "risk": {
            "risk_score": round(risk.risk_score, 1),
            "risk_level": risk.risk_level,
        },
        "review_status": review_status,
        "image": image_meta,
    }


def build_standard_success_fields(
    *,
    damages: List,
    risk: Any,
    model_id: str,
    bucket: str,
    key: str,
    edge_detections: Optional[List] = None,
    img_w: Optional[int] = None,
    img_h: Optional[int] = None,
    judgment_basis: str = "",
) -> Dict[str, Any]:
    """최초 클라우드 분석 성공 필드 (항상 MANUAL_NEEDED)."""
    edge_detections = edge_detections or []
    detections = []
    for i, d in enumerate(damages):
        det: Dict[str, Any] = {
            "damage_class": d.damage_type,
            "severity": d.severity,
            "location": d.location,
            "description": d.note,
            "confidence": round(float(d.confidence), 3),
        }
        if d.box:
            det["box"] = d.box
        elif edge_detections:
            edge_d = edge_detections[i % len(edge_detections)]
            if isinstance(edge_d, dict) and isinstance(edge_d.get("bbox"), dict):
                pct = _pixel_bbox_to_pct(edge_d["bbox"], img_w, img_h)
                if pct:
                    det["box"] = pct
                else:
                    det["bbox"] = edge_d["bbox"]
        detections.append(det)

    image_meta: Dict[str, Any] = {
        "bucket": bucket,
        "raw_image_key": key,
    }
    if img_w and img_h:
        image_meta["width"] = int(img_w)
        image_meta["height"] = int(img_h)

    cloud: Dict[str, Any] = {
        "analysis_status": "COMPLETED",
        "model_name": model_id,
        "inspection_result": "damage" if damages else "normal",
        "detection_count": len(detections),
        "detections": detections,
    }
    basis = (judgment_basis or "").strip()
    if basis:
        cloud["judgment_basis"] = basis[:1200]

    return {
        "processed_at": _now_iso(),
        "cloud_analysis": cloud,
        "risk": {
            "risk_score": round(risk.risk_score, 1),
            "risk_level": risk.risk_level,
        },
        "review_status": "MANUAL_NEEDED",
        "image": image_meta,
    }


def run_standard_analysis(
    *,
    bucket: str,
    key: str,
    edge_detections: Optional[List] = None,
) -> Dict[str, Any]:
    """최초 유입 이미지 Foundation Model 분석 (화질개선 없음)."""
    image = _store.download_from(bucket, key)
    analysis = _analyzer.analyze(image.body, image.image_format, reinspect=False)
    damages = analysis.damages
    risk = calculate_risk(damages)
    img_w, img_h = _image_size(image.body, image.image_format)
    return build_standard_success_fields(
        damages=damages,
        risk=risk,
        model_id=_analyzer.model_id,
        bucket=bucket,
        key=key,
        edge_detections=edge_detections,
        img_w=img_w,
        img_h=img_h,
        judgment_basis=analysis.judgment_basis,
    )


def run_reinspect_analysis(
    *,
    bucket: str,
    key: str,
    reviewer_note: str = "",
    edge_detections: Optional[List] = None,
    cloud_detections: Optional[List] = None,
    reviewer: str = "dashboard",
) -> Dict[str, Any]:
    """화질 개선 → 기존 bbox 안만 재판정 → DynamoDB 갱신 필드."""
    image = _store.download_from(bucket, key)
    print(
        f"[reinspect] download s3://{bucket}/{key} bytes={len(image.body)} "
        f"fmt={image.image_format}"
    )

    # prior box 는 원본 해상도 기준으로 수집 (edge 픽셀 bbox 변환용)
    src_w, src_h = _image_size(image.body, image.image_format)
    prior_boxes = collect_prior_boxes(
        cloud_detections=cloud_detections,
        edge_detections=edge_detections,
        img_w=src_w,
        img_h=src_h,
    )
    print(f"[reinspect] prior_boxes={len(prior_boxes)} (bbox 내부만 분석)")

    enhanced = _enhancer.enhance(image.body)
    analyze_bytes = enhanced.body
    analyze_fmt = enhanced.image_format

    enhanced_key: Optional[str] = None
    if not enhanced.used_fallback:
        event_id = _event_id_from_key(key)
        enhanced_key = f"enhanced-images/{event_id}.png"
        try:
            _store.upload(
                enhanced_key,
                enhanced.body,
                bucket=bucket,
                content_type="image/png",
            )
            print(f"[reinspect] enhanced uploaded s3://{bucket}/{enhanced_key}")
        except Exception as exc:  # noqa: BLE001
            print(f"[reinspect] enhanced upload 실패 (분석은 계속): {exc}")
            enhanced_key = None

    analysis = _analyzer.analyze(
        analyze_bytes,
        analyze_fmt,
        reviewer_note=reviewer_note or None,
        reinspect=True,
        prior_boxes=prior_boxes,
    )
    damages = analysis.damages
    risk = calculate_risk(damages)
    img_w, img_h = _image_size(analyze_bytes, analyze_fmt)
    return build_reinspect_success_fields(
        damages=damages,
        risk=risk,
        model_id=_analyzer.model_id,
        bucket=bucket,
        key=key,
        edge_detections=edge_detections,
        img_w=img_w,
        img_h=img_h,
        reviewer_note=reviewer_note,
        reviewer=reviewer,
        enhanced_image_key=enhanced_key,
        enhance_model_id=enhanced.model_id,
        enhance_fallback=enhanced.used_fallback,
        judgment_basis=analysis.judgment_basis,
    )
