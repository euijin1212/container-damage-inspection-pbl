"""검수자 대시보드 API Lambda (API Gateway 뒤).

역할
----
프론트엔드(Next.js 대시보드)가 DynamoDB/S3 를 직접 건드리지 않도록,
검수 큐 조회·상세·검수 처리·보고서 조회 API 를 제공한다.

엔드포인트 (API Gateway HTTP API / REST 공통)
--------------------------------------------
  GET  /inspections?status=MANUAL_NEEDED&date=YYYY-MM-DD
  GET  /inspections/{event_id}
  POST /inspections/{event_id}/review
       body: { "action": "approve"|"modify"|"reject", "reviewer"?, "memo"?, "risk_level"? }
  GET  /inspections/{event_id}/report

검수 승인(approve/modify → review_status=DONE) 시 DynamoDB Streams 가
report_generator 를 트리거해 EIR PDF 를 자동 생성한다.

필요 환경변수:
  DDB_TABLE              테이블명 (기본 InspectionEventTable)
  REVIEW_STATUS_INDEX    GSI 이름 (기본 ReviewStatusIndex). 없으면 Scan 폴백
  S3_BUCKET              이미지/보고서 버킷 (기본 container-damage)
  PRESIGN_EXPIRES        Presigned URL 만료(초, 기본 3600)
  CORS_ORIGIN            CORS Allow-Origin (기본 *)

배포 핸들러: handler.lambda_handler
"""

from __future__ import annotations

import json
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote

import boto3
from botocore.exceptions import ClientError

# 공유 라이브러리(src) 경로 확보
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.abspath(os.path.join(_HERE, "..", ".."))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.config import settings  # noqa: E402
from src.record_adapter import (  # noqa: E402
    REPORT_CREATED,
    REPORT_FAILED,
    REPORT_NOT_CREATED,
    REPORT_PENDING,
    get_report_status,
)

_ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
_s3 = boto3.client("s3", region_name=settings.aws_region)

_DEFAULT_TABLE = "InspectionEventTable"
_DEFAULT_INDEX = "ReviewStatusIndex"
_DEFAULT_BUCKET = "container-damage"

# DynamoDB review_status → 프론트 status
_REVIEW_TO_FRONT = {
    "PENDING_CLOUD_ANALYSIS": "PROCESSING",
    "MANUAL_NEEDED": "MANUAL_NEEDED",
    "AUTO_OK": "AUTO_OK",
    "DONE": "DONE",
    "INFERENCE_FAILED": "FAILED",
    "REJECTED": "MANUAL_NEEDED",
}

# DynamoDB report.report_status → 프론트 reportStatus
_REPORT_TO_FRONT = {
    REPORT_NOT_CREATED: "PENDING",
    REPORT_PENDING: "GENERATING",
    REPORT_CREATED: "CREATED",
    REPORT_FAILED: "FAILED",
    None: "PENDING",
    "": "PENDING",
}

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": os.getenv("CORS_ORIGIN", "*"),
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Content-Type": "application/json",
}


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _to_native(obj: Any) -> Any:
    if isinstance(obj, list):
        return [_to_native(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    return obj


def _table():
    name = os.getenv("DDB_TABLE", _DEFAULT_TABLE)
    return _ddb.Table(name)


def _bucket() -> str:
    return os.getenv("S3_BUCKET") or settings.s3_bucket or _DEFAULT_BUCKET


def _presign_expires() -> int:
    try:
        return int(os.getenv("PRESIGN_EXPIRES", "3600"))
    except ValueError:
        return 3600


def _response(status: int, body: Any) -> Dict:
    return {
        "statusCode": status,
        "headers": _CORS_HEADERS,
        "body": json.dumps(body, ensure_ascii=False, default=str),
    }


def _parse_event(event: Dict) -> Tuple[str, str, Dict[str, str], Dict, Dict]:
    """API Gateway HTTP API(v2) / REST(v1) / 로컬 테스트 이벤트를 정규화한다.

    Returns: method, path, query, path_params, body_dict
    """
    # HTTP API (payload 2.0)
    rc = event.get("requestContext") or {}
    http = rc.get("http") or {}
    if http.get("method"):
        method = http["method"].upper()
        path = event.get("rawPath") or event.get("requestContext", {}).get("http", {}).get("path") or "/"
        query = event.get("queryStringParameters") or {}
        path_params = event.get("pathParameters") or {}
    else:
        # REST API (v1) or direct invoke
        method = (event.get("httpMethod") or event.get("method") or "GET").upper()
        path = event.get("path") or event.get("resource") or "/"
        query = event.get("queryStringParameters") or {}
        path_params = event.get("pathParameters") or {}

    raw_body = event.get("body")
    body: Dict = {}
    if raw_body:
        if event.get("isBase64Encoded"):
            import base64

            raw_body = base64.b64decode(raw_body).decode("utf-8")
        try:
            body = json.loads(raw_body) if isinstance(raw_body, str) else (raw_body or {})
        except json.JSONDecodeError:
            body = {}

    # pathParameters 가 없을 때 path 에서 event_id 추출
    if not path_params.get("event_id"):
        m = re.search(r"/inspections/([^/]+)", path or "")
        if m:
            path_params = {**path_params, "event_id": unquote(m.group(1))}

    return method, path or "/", query, path_params, body


_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def _object_exists(bucket: str, key: str) -> bool:
    try:
        _s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        return False


def _resolve_image_key(bucket: str, key: str) -> Optional[str]:
    """DDB 키와 S3 실제 확장자(.jpg/.png 등)가 달라도 같은 파일명 stem 으로 찾는다."""
    if not bucket or not key:
        return None
    if _object_exists(bucket, key):
        return key

    stem, ext = os.path.splitext(key)
    for alt in _IMAGE_EXTS:
        if alt.lower() == ext.lower():
            continue
        candidate = f"{stem}{alt}"
        if _object_exists(bucket, candidate):
            print(f"[image] key fallback s3://{bucket}/{key} → {candidate}")
            return candidate
    # 객체를 못 찾아도 원래 키로 Presign (호출 측에서 확인 가능)
    return key


def _presign(bucket: str, key: Optional[str]) -> Optional[str]:
    if not bucket or not key:
        return None
    try:
        return _s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=_presign_expires(),
        )
    except ClientError as exc:
        print(f"[presign 실패] s3://{bucket}/{key}: {exc}")
        return None


def _report_key_from_path(report_path: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """s3://bucket/key → (bucket, key)."""
    if not report_path or not str(report_path).startswith("s3://"):
        return None, None
    rest = str(report_path)[5:]
    bucket, _, key = rest.partition("/")
    return bucket or None, key or None


def _as_confidence(value: Any) -> Optional[float]:
    """0~1 로 정규화. 0~100 입력이면 100으로 나눈다."""
    if value is None:
        return None
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return None
    if conf > 1.0:
        conf = conf / 100.0
    if conf < 0:
        return 0.0
    if conf > 1:
        return 1.0
    return conf


def _pixel_bbox_to_pct(
    bbox: Dict, img_w: Optional[float], img_h: Optional[float]
) -> Optional[Dict[str, float]]:
    """YOLO 픽셀 bbox → 퍼센트 box. 이미지 크기가 없으면 bbox 우하단을 근사 크기로 사용."""
    try:
        x_min = float(bbox.get("x_min"))
        y_min = float(bbox.get("y_min"))
        x_max = float(bbox.get("x_max"))
        y_max = float(bbox.get("y_max"))
    except (TypeError, ValueError, AttributeError):
        return None
    if x_max <= x_min or y_max <= y_min:
        return None

    w = float(img_w) if img_w and img_w > 0 else max(x_max * 1.05, x_max + 1.0)
    h = float(img_h) if img_h and img_h > 0 else max(y_max * 1.05, y_max + 1.0)
    return {
        "x": round(max(0.0, x_min / w * 100.0), 2),
        "y": round(max(0.0, y_min / h * 100.0), 2),
        "width": round(min(100.0, (x_max - x_min) / w * 100.0), 2),
        "height": round(min(100.0, (y_max - y_min) / h * 100.0), 2),
    }


def _normalize_box(
    d: Dict,
    idx: int,
    *,
    edge_detections: List[Dict],
    img_w: Optional[float],
    img_h: Optional[float],
) -> Optional[Dict[str, float]]:
    """원래 있는 bbox 만 사용한다. 새 박스를 만들지 않는다.

    우선순위:
      1) detection 퍼센트 box (analyzer 가 edge 에서 복사한 값)
      2) detection 픽셀 bbox
      3) edge YOLO bbox (인덱스 매핑 — 분석 대상 구역)
    """
    raw_box = d.get("box")
    if isinstance(raw_box, dict):
        try:
            x = float(raw_box.get("x", 0))
            y = float(raw_box.get("y", 0))
            w = float(raw_box.get("width", 0))
            h = float(raw_box.get("height", 0))
            if w > 0 and h > 0:
                return {"x": x, "y": y, "width": w, "height": h}
        except (TypeError, ValueError):
            pass

    pixel = d.get("bbox") if isinstance(d.get("bbox"), dict) else None
    if pixel is None and edge_detections:
        edge_d = edge_detections[(idx - 1) % len(edge_detections)]
        if isinstance(edge_d, dict) and isinstance(edge_d.get("bbox"), dict):
            pixel = edge_d["bbox"]

    if isinstance(pixel, dict):
        return _pixel_bbox_to_pct(pixel, img_w, img_h)

    return None


def _serialize_detection(
    d: Dict,
    idx: int,
    *,
    fallback_confidence: Optional[float] = None,
    edge_detections: Optional[List[Dict]] = None,
    img_w: Optional[float] = None,
    img_h: Optional[float] = None,
) -> Dict:
    conf = _as_confidence(d.get("confidence"))
    if conf is None:
        conf = _as_confidence(fallback_confidence)
    box = _normalize_box(
        d,
        idx,
        edge_detections=edge_detections or [],
        img_w=img_w,
        img_h=img_h,
    )
    out = {
        "id": f"d{idx}",
        "label": d.get("damage_class") or d.get("class") or "unknown",
        "confidence": conf if conf is not None else 0.0,
        "severity": (d.get("severity") or "medium").upper()
        if str(d.get("severity", "")).lower() in ("low", "medium", "high")
        else (d.get("severity") or "MEDIUM"),
        "description": d.get("description") or d.get("note") or "",
        "location": d.get("location"),
    }
    if box:
        out["box"] = box
    return out


def _serialize_item(item: Dict, *, detail: bool = False) -> Dict:
    """DynamoDB MVP item → 프론트 Inspection 친화 JSON."""
    item = _to_native(item)
    cloud = item.get("cloud_analysis") or {}
    risk = item.get("risk") or {}
    container = item.get("container") or {}
    source = item.get("source") or {}
    image = item.get("image") or {}
    report = item.get("report") or {}
    edge = item.get("edge") or {}

    detections_raw = cloud.get("detections") or []
    edge_detections = edge.get("edge_detections") or []
    # 클라우드 분석 전이면 엣지 YOLO 결과로 폴백
    if not detections_raw:
        detections_raw = edge_detections

    fallback_conf = cloud.get("confidence")
    if fallback_conf is None:
        fallback_conf = edge.get("edge_confidence")

    img_w = image.get("width") or image.get("image_width")
    img_h = image.get("height") or image.get("image_height")
    try:
        img_w = float(img_w) if img_w is not None else None
        img_h = float(img_h) if img_h is not None else None
    except (TypeError, ValueError):
        img_w, img_h = None, None

    detections = [
        _serialize_detection(
            d,
            i + 1,
            fallback_confidence=fallback_conf,
            edge_detections=edge_detections,
            img_w=img_w,
            img_h=img_h,
        )
        for i, d in enumerate(detections_raw)
    ]

    review = item.get("review_status") or "PENDING_CLOUD_ANALYSIS"
    report_status = get_report_status(item)

    labels = []
    seen_labels = set()
    for d in detections:
        lab = (d.get("label") or "").strip()
        if lab and lab not in seen_labels:
            seen_labels.add(lab)
            labels.append(lab)
    detected_damage = ", ".join(labels) if labels else (
        "탐지된 손상 없음" if cloud.get("inspection_result") == "normal" else "손상 의심"
    )

    # 응답 detections 에서는 confidence 미노출 (위험도 계산은 analyzer 내부에서 수행)
    detections_public = [
        {k: v for k, v in d.items() if k != "confidence"} for d in detections
    ]

    out: Dict[str, Any] = {
        "id": item.get("event_id"),
        "event_id": item.get("event_id"),
        "containerId": container.get("container_id"),
        "container_id": container.get("container_id"),
        "capturedAt": item.get("captured_at"),
        "captured_at": item.get("captured_at"),
        "eventDate": item.get("event_date"),
        "processedAt": item.get("processed_at"),
        "detectedDamage": detected_damage,
        "damage_summary": detected_damage,
        "riskScore": risk.get("risk_score"),
        "risk_score": risk.get("risk_score"),
        "riskLevel": risk.get("risk_level"),
        "risk_level": risk.get("risk_level"),
        "status": _REVIEW_TO_FRONT.get(review, review),
        "review_status": review,
        "detectionCount": cloud.get("detection_count", len(detections)),
        "detections": detections_public,
        "gate": source.get("gate_id") or "",
        "lane": source.get("camera_id") or "",
        "inspector": item.get("reviewer") or "담당자 미지정",
        "reportStatus": _REPORT_TO_FRONT.get(report_status, report_status or "PENDING"),
        "report_status": report_status or REPORT_NOT_CREATED,
    }

    # 목록/상세 공통: 생성된 PDF Presigned URL
    report_path = report.get("report_path")
    rb, rk = _report_key_from_path(report_path)
    report_url = _presign(rb or _bucket(), rk) if rk else None
    if report_url:
        out["reportUrl"] = report_url
        out["report_url"] = report_url

    if detail:
        bucket = image.get("bucket") or _bucket()
        raw_key = image.get("raw_image_key")
        key = _resolve_image_key(bucket, raw_key) if raw_key else None
        original_url = _presign(bucket, key) if key else None

        out.update(
            {
                "originalImage": original_url,
                "raw_image_url": original_url,
                "image_s3_url": original_url,
                "imageKey": key,
                "detections": detections_public,
                "cloudAnalysis": cloud,
                "edge": edge,
                "risk": risk,
                "report": {
                    "report_status": report_status or REPORT_NOT_CREATED,
                    "reportStatus": _REPORT_TO_FRONT.get(
                        report_status, report_status or "PENDING"
                    ),
                    "report_path": report_path,
                    "reportUrl": report_url,
                    "report_url": report_url,
                    "report_generated_at": report.get("report_generated_at"),
                    "reuse_decision": report.get("reuse_decision"),
                    "report_summary": report.get("report_summary"),
                    "error_message": report.get("error_message"),
                },
                "aiSummary": report.get("report_summary")
                or cloud.get("error_message")
                or detected_damage,
                "verdict": report.get("reuse_decision") or "",
                "reviewerComment": item.get("review_memo"),
                "errorMessage": (cloud.get("error_message") if review == "INFERENCE_FAILED" else None)
                or report.get("error_message"),
            }
        )
    return out


def list_inspections(query: Dict[str, str]) -> Dict:
    """검수 목록. status 기본 MANUAL_NEEDED. date(선택)로 SK 범위 필터."""
    status = (query.get("status") or "MANUAL_NEEDED").strip()
    event_date = (query.get("date") or "").strip() or None
    table = _table()
    index = os.getenv("REVIEW_STATUS_INDEX", _DEFAULT_INDEX)

    items: List[Dict] = []
    try:
        kwargs: Dict[str, Any] = {
            "IndexName": index,
            "KeyConditionExpression": "review_status = :s",
            "ExpressionAttributeValues": {":s": status},
        }
        if event_date:
            kwargs["KeyConditionExpression"] = (
                "review_status = :s AND event_date = :d"
            )
            kwargs["ExpressionAttributeValues"][":d"] = event_date

        resp = table.query(**kwargs)
        items = resp.get("Items") or []
        while resp.get("LastEvaluatedKey"):
            resp = table.query(ExclusiveStartKey=resp["LastEvaluatedKey"], **kwargs)
            items.extend(resp.get("Items") or [])
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        # GSI 미존재 등 → Scan 폴백
        print(f"[list] Query 실패({code}), Scan 폴백: {exc}")
        scan_kwargs: Dict[str, Any] = {
            "FilterExpression": "review_status = :s",
            "ExpressionAttributeValues": {":s": status},
        }
        if event_date:
            scan_kwargs["FilterExpression"] = (
                "review_status = :s AND event_date = :d"
            )
            scan_kwargs["ExpressionAttributeValues"][":d"] = event_date
        resp = table.scan(**scan_kwargs)
        items = resp.get("Items") or []
        while resp.get("LastEvaluatedKey"):
            resp = table.scan(
                ExclusiveStartKey=resp["LastEvaluatedKey"], **scan_kwargs
            )
            items.extend(resp.get("Items") or [])

    serialized = [_serialize_item(it, detail=False) for it in items]
    # 고위험 우선
    rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    serialized.sort(
        key=lambda x: (
            rank.get(str(x.get("riskLevel") or ""), 9),
            -(x.get("riskScore") or 0),
            x.get("capturedAt") or "",
        )
    )
    return _response(200, {"items": serialized, "count": len(serialized)})


def get_inspection(event_id: str) -> Dict:
    if not event_id:
        return _response(400, {"error": "event_id required"})
    resp = _table().get_item(Key={"event_id": event_id})
    item = resp.get("Item")
    if not item:
        return _response(404, {"error": "not found", "event_id": event_id})
    return _response(200, _serialize_item(item, detail=True))


def get_report(event_id: str) -> Dict:
    if not event_id:
        return _response(400, {"error": "event_id required"})
    resp = _table().get_item(Key={"event_id": event_id})
    item = resp.get("Item")
    if not item:
        return _response(404, {"error": "not found", "event_id": event_id})
    detail = _serialize_item(item, detail=True)
    return _response(
        200,
        {
            "event_id": event_id,
            "report": detail.get("report"),
            "reportStatus": detail.get("reportStatus"),
        },
    )


def review_inspection(event_id: str, body: Dict) -> Dict:
    """검수 처리. approve/modify → DONE (보고서 트리거). reject → REJECTED."""
    if not event_id:
        return _response(400, {"error": "event_id required"})

    action = str(body.get("action") or "").strip().lower()
    if action not in ("approve", "modify", "reject"):
        return _response(
            400,
            {"error": "action must be approve|modify|reject"},
        )

    table = _table()
    existing = table.get_item(Key={"event_id": event_id}).get("Item")
    if not existing:
        return _response(404, {"error": "not found", "event_id": event_id})

    reviewer = body.get("reviewer") or "dashboard"
    memo = body.get("memo") or ""
    now = _now_iso()

    if action == "reject":
        new_status = "REJECTED"
        update_expr = (
            "SET review_status = :rs, reviewer = :rv, review_memo = :memo, "
            "reviewed_at = :at"
        )
        values: Dict[str, Any] = {
            ":rs": new_status,
            ":rv": reviewer,
            ":memo": memo,
            ":at": now,
        }
        names = None
    else:
        # approve / modify → DONE
        new_status = "DONE"
        update_expr = (
            "SET review_status = :rs, reviewer = :rv, review_memo = :memo, "
            "reviewed_at = :at"
        )
        values = {
            ":rs": new_status,
            ":rv": reviewer,
            ":memo": memo,
            ":at": now,
        }
        names = None

        # modify: risk_level 변경 (risk map 부분 갱신)
        if action == "modify" and body.get("risk_level"):
            level = str(body["risk_level"]).upper()
            if level not in ("HIGH", "MEDIUM", "LOW"):
                return _response(400, {"error": "risk_level must be HIGH|MEDIUM|LOW"})
            update_expr += ", #risk.#rl = :rl"
            names = {"#risk": "risk", "#rl": "risk_level"}
            values[":rl"] = level

    try:
        kwargs: Dict[str, Any] = {
            "Key": {"event_id": event_id},
            "UpdateExpression": update_expr,
            "ExpressionAttributeValues": values,
            "ConditionExpression": "attribute_exists(event_id)",
            "ReturnValues": "ALL_NEW",
        }
        if names:
            kwargs["ExpressionAttributeNames"] = names
        result = table.update_item(**kwargs)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return _response(404, {"error": "not found", "event_id": event_id})
        raise

    updated = _to_native(result.get("Attributes") or {})
    print(
        f"[review] event_id={event_id} action={action} → review_status={new_status}"
    )
    return _response(
        200,
        {
            "ok": True,
            "action": action,
            "event_id": event_id,
            "review_status": new_status,
            "item": _serialize_item(updated, detail=True),
        },
    )


def lambda_handler(event: Dict, context=None) -> Dict:
    try:
        method, path, query, path_params, body = _parse_event(event or {})

        if method == "OPTIONS":
            return _response(200, {"ok": True})

        event_id = path_params.get("event_id")
        path_l = (path or "").rstrip("/")

        # /inspections/{id}/report
        if method == "GET" and event_id and path_l.endswith("/report"):
            return get_report(event_id)

        # /inspections/{id}/review
        if method == "POST" and event_id and path_l.endswith("/review"):
            return review_inspection(event_id, body)

        # /inspections/{id}
        if method == "GET" and event_id and "/inspections/" in path_l:
            return get_inspection(event_id)

        # /inspections
        if method == "GET" and path_l.endswith("/inspections"):
            return list_inspections(query)

        # direct invoke helpers (로컬/테스트)
        if event.get("action") == "list":
            return list_inspections(event.get("query") or {})
        if event.get("action") == "get":
            return get_inspection(event.get("event_id", ""))
        if event.get("action") == "review":
            return review_inspection(event.get("event_id", ""), event.get("body") or {})

        return _response(
            404,
            {
                "error": "route not found",
                "method": method,
                "path": path,
            },
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[dashboard_api 오류] {exc}")
        traceback.print_exc()
        return _response(500, {"error": str(exc)})
