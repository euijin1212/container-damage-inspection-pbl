"""Inspection event ingest Lambda.

API Gateway POST /inspection-events 뒤에서 실행된다.

역할:
  1. YOLO/Simulator 메타데이터를 DynamoDB PENDING item 으로 저장
  2. 원본 이미지를 S3에 직접 업로드할 presigned PUT URL 반환

이미지 바이트는 API Gateway/Lambda를 통과하지 않는다.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError

_ddb = boto3.resource("dynamodb")
_s3 = boto3.client("s3")

_DEFAULT_TABLE = "InspectionEventTable"
_DEFAULT_BUCKET = "container-damage"
_DEFAULT_UPLOAD_EXPIRES = 900


def _cors_headers() -> Dict[str, str]:
    return {
        "Access-Control-Allow-Origin": os.getenv("CORS_ORIGIN", "*"),
        "Access-Control-Allow-Headers": "Content-Type,Authorization",
        "Access-Control-Allow-Methods": "POST,OPTIONS",
        "Content-Type": "application/json",
    }


def _response(status: int, body: Dict[str, Any]) -> Dict:
    return {
        "statusCode": status,
        "headers": _cors_headers(),
        "body": json.dumps(body, ensure_ascii=False, default=str),
    }


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _parse_body(event: Dict) -> Dict:
    raw = event.get("body")
    if not raw:
        return {}
    if event.get("isBase64Encoded"):
        import base64

        raw = base64.b64decode(raw).decode("utf-8")
    if isinstance(raw, dict):
        return raw
    return json.loads(raw)


def _to_decimal(obj: Any) -> Any:
    return json.loads(json.dumps(obj), parse_float=Decimal, parse_int=Decimal)


def _method(event: Dict) -> str:
    return (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or ""
    ).upper()


def _upload_expires() -> int:
    try:
        return int(os.getenv("UPLOAD_EXPIRES", str(_DEFAULT_UPLOAD_EXPIRES)))
    except ValueError:
        return _DEFAULT_UPLOAD_EXPIRES


def _image_ext(content_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(content_type, ".jpg")


def _build_item(body: Dict, event_id: str, bucket: str, raw_image_key: str) -> Dict:
    return {
        "event_id": event_id,
        "event_date": body.get("event_date") or _now_iso()[:10],
        "captured_at": body.get("captured_at") or _now_iso(),
        "container": {
            "container_id": body.get("container_id", ""),
        },
        "source": {
            "gate_id": body.get("gate_id", ""),
            "camera_id": body.get("camera_id", ""),
        },
        "image": {
            "bucket": bucket,
            "raw_image_key": raw_image_key,
        },
        "edge": {
            "edge_status": body.get("edge_status", "DAMAGE_SUSPECTED"),
            "edge_model": body.get("edge_model", "YOLOv8"),
            "edge_confidence": body.get("edge_confidence"),
            "edge_detections": body.get("edge_detections", []),
        },
        "cloud_analysis": {
            "analysis_status": "PENDING",
        },
        "risk": {
            "risk_score": None,
            "risk_level": None,
        },
        "review_status": "PENDING_CLOUD_ANALYSIS",
        "report": {
            "report_status": "NOT_CREATED",
        },
        "created_at": _now_iso(),
    }


def lambda_handler(event: Dict, context=None) -> Dict:
    if _method(event) == "OPTIONS":
        return _response(200, {"ok": True})

    try:
        body = _parse_body(event or {})
        event_id = body.get("event_id") or f"EVT-{int(time.time())}"
        content_type = body.get("image_content_type", "image/jpeg")
        bucket = os.getenv("S3_BUCKET", _DEFAULT_BUCKET)
        table_name = os.getenv("DDB_TABLE", _DEFAULT_TABLE)
        expires = _upload_expires()

        raw_image_key = body.get("raw_image_key") or (
            f"raw-images/{event_id}{_image_ext(content_type)}"
        )

        item = _build_item(body, event_id, bucket, raw_image_key)
        table = _ddb.Table(table_name)
        table.put_item(
            Item=_to_decimal(item),
            ConditionExpression="attribute_not_exists(event_id)",
        )

        upload_url = _s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": bucket,
                "Key": raw_image_key,
                "ContentType": content_type,
            },
            ExpiresIn=expires,
        )

        return _response(
            201,
            {
                "event_id": event_id,
                "bucket": bucket,
                "raw_image_key": raw_image_key,
                "upload_url": upload_url,
                "expires_in": expires,
            },
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code == "ConditionalCheckFailedException":
            return _response(409, {"error": "event_id already exists"})
        return _response(500, {"error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return _response(500, {"error": str(exc)})
