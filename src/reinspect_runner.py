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

    confidences = [d.confidence for d in damages]
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
            "confidence": round(max(confidences), 3) if confidences else 0.0,
        "detection_count": len(detections),
        "detections": detections,
        "reinspect": True,
        "image_enhanced": bool(enhanced_image_key) and not enhance_fallback,
        "enhance_fallback": enhance_fallback,
    }
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

    confidences = [d.confidence for d in damages]
    image_meta: Dict[str, Any] = {
        "bucket": bucket,
        "raw_image_key": key,
    }
    if img_w and img_h:
        image_meta["width"] = int(img_w)
        image_meta["height"] = int(img_h)

    return {
        "processed_at": _now_iso(),
        "cloud_analysis": {
            "analysis_status": "COMPLETED",
            "model_name": model_id,
            "inspection_result": "damage" if damages else "normal",
            "confidence": round(max(confidences), 3) if confidences else 0.0,
            "detection_count": len(detections),
            "detections": detections,
        },
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
    damages = _analyzer.analyze(image.body, image.image_format, reinspect=False)
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
    )


def run_reinspect_analysis(
    *,
    bucket: str,
    key: str,
    reviewer_note: str = "",
    edge_detections: Optional[List] = None,
    reviewer: str = "dashboard",
) -> Dict[str, Any]:
    """화질 개선 → 검수 의견 포함 재감지 → DynamoDB 갱신 필드."""
    image = _store.download_from(bucket, key)
    print(
        f"[reinspect] download s3://{bucket}/{key} bytes={len(image.body)} "
        f"fmt={image.image_format}"
    )

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

    damages = _analyzer.analyze(
        analyze_bytes,
        analyze_fmt,
        reviewer_note=reviewer_note or None,
        reinspect=True,
    )
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
    )
