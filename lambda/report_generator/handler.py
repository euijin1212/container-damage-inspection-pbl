"""비동기 보고서 자동화 Lambda 핸들러.

트리거
------
1) DynamoDB Streams: review_status 가 DONE 으로 바뀌면
2) 직접 호출: { "event_id": "...", "force": true }
   (dashboard_api 승인 직후 비동기 invoke — Streams 미동작 대비)

흐름: Bedrock 초안 → PDF → S3(reports/) → DynamoDB report 메타 갱신

report.report_status: NOT_CREATED → PENDING → CREATED (또는 FAILED)

배포 핸들러: handler.lambda_handler

환경변수:
  DDB_TABLE        검수 테이블 (기본 InspectionEventTable)
  REPORT_BUCKET    PDF 버킷 (없으면 S3_BUCKET / container-damage)
  REPORT_PREFIX    키 프리픽스 (기본 reports/)
  BEDROCK_MODEL_ID 보고서 모델
  REPORT_FONT_PATH 한글 TTF (선택)
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

import boto3
from boto3.dynamodb.types import TypeDeserializer

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.abspath(os.path.join(_HERE, "..", ".."))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.config import settings  # noqa: E402
from src.pdf_report import build_report_pdf  # noqa: E402
from src.record_adapter import (  # noqa: E402
    REPORT_CREATED,
    REPORT_FAILED,
    REPORT_NOT_CREATED,
    REPORT_PENDING,
    created_report_meta,
    failed_report_meta,
    get_report_status,
    pending_report_meta,
)
from src.report_writer import BedrockReportWriter  # noqa: E402

_writer = BedrockReportWriter()
_s3 = boto3.client("s3", region_name=settings.aws_region)
_ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
_deserializer = TypeDeserializer()

_DEFAULT_TABLE = "InspectionEventTable"
_SKIP_REPORT_STATUS = {REPORT_CREATED, REPORT_PENDING}
_TRIGGER_REVIEW_STATUS = "DONE"
_RETRYABLE_REPORT_STATUS = {None, "", REPORT_NOT_CREATED, REPORT_FAILED}


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _to_native(obj):
    if isinstance(obj, list):
        return [_to_native(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    return obj


def _deserialize_image(image: Optional[Dict]) -> Dict:
    if not image:
        return {}
    plain = {k: _deserializer.deserialize(v) for k, v in image.items()}
    return _to_native(plain)


def _table():
    return _ddb.Table(os.getenv("DDB_TABLE", _DEFAULT_TABLE))


def _report_bucket() -> str:
    return (
        os.getenv("REPORT_BUCKET")
        or os.getenv("S3_BUCKET")
        or settings.s3_bucket
        or "container-damage"
    )


def _should_generate(new_img: Dict, old_img: Dict, *, force: bool = False) -> bool:
    if new_img.get("review_status") != _TRIGGER_REVIEW_STATUS:
        return False

    status = get_report_status(new_img)
    if status == REPORT_CREATED and not force:
        return False
    # force 이면 멈춘 PENDING 도 재시도
    if status == REPORT_PENDING and not force:
        return False

    if force:
        return True

    already_done = old_img.get("review_status") == _TRIGGER_REVIEW_STATUS
    if already_done and status not in _RETRYABLE_REPORT_STATUS:
        return False
    return True


def _report_key(record: Dict) -> str:
    prefix = os.getenv("REPORT_PREFIX", "reports/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return f"{prefix}{record.get('event_id', 'unknown')}.pdf"


def _update_report_meta(ddb_key: Dict, report_fields: Dict) -> None:
    if not ddb_key:
        print("[report] Keys 없음 → 메타 업데이트 스킵")
        return

    status = report_fields.get("report_status", "?")
    print(f"[report_status] event_id={ddb_key.get('event_id')} → {status}")
    _table().update_item(
        Key=ddb_key,
        UpdateExpression="SET #report = :report",
        ExpressionAttributeNames={"#report": "report"},
        ExpressionAttributeValues={":report": report_fields},
    )


def generate_report(record: Dict, ddb_key: Dict) -> Dict:
    bucket = _report_bucket()
    key = _report_key(record)
    event_id = record.get("event_id")

    print(f"[보고서시작] event_id={event_id} bucket={bucket} key={key}")
    _update_report_meta(ddb_key, pending_report_meta())

    try:
        draft = _writer.write(record)
        pdf_bytes = build_report_pdf(record, draft)
        print(f"[PDF] event_id={event_id} bytes={len(pdf_bytes)}")

        _s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
        report_path = f"s3://{bucket}/{key}"
        generated_at = _now_iso()

        _update_report_meta(
            ddb_key,
            created_report_meta(
                report_path=report_path,
                generated_at=generated_at,
                reuse_decision=draft.get("reuse_decision", ""),
                report_summary=draft.get("summary", ""),
            ),
        )
        print(
            f"[보고서생성] {event_id} → {report_path} "
            f"(reuse={draft.get('reuse_decision')}, status={REPORT_CREATED})"
        )
        return {
            "event_id": event_id,
            "report_path": report_path,
            "report_status": REPORT_CREATED,
            "reuse_decision": draft.get("reuse_decision"),
        }
    except Exception:
        raise


def generate_for_event_id(event_id: str, *, force: bool = False) -> Dict:
    """DDB 에서 item 을 읽어 보고서를 생성한다 (직접 호출용)."""
    if not event_id:
        return {"skipped": True, "reason": "event_id required"}

    item = _table().get_item(Key={"event_id": event_id}).get("Item")
    if not item:
        return {"skipped": True, "reason": "not found", "event_id": event_id}

    record = _to_native(item)
    ddb_key = {"event_id": event_id}

    if not _should_generate(record, {}, force=force):
        return {
            "skipped": True,
            "event_id": event_id,
            "review_status": record.get("review_status"),
            "report_status": get_report_status(record),
            "reason": "should_generate=false",
        }

    return generate_report(record, ddb_key)


def lambda_handler(event: Dict, context=None) -> Dict:
    event = event or {}
    results: List[Dict] = []
    skipped = 0
    errors: List[Dict] = []

    # --- 직접 호출: { "event_id": "...", "force": true } ---
    if event.get("event_id") and "Records" not in event:
        event_id = str(event["event_id"])
        force = bool(event.get("force", True))
        print(f"[direct] event_id={event_id} force={force}")
        try:
            out = generate_for_event_id(event_id, force=force)
            if out.get("skipped"):
                skipped += 1
            else:
                results.append(out)
        except Exception as exc:  # noqa: BLE001
            print(f"[오류] event_id={event_id}: {exc}")
            traceback.print_exc()
            errors.append({"event_id": event_id, "error": str(exc)})
            try:
                _update_report_meta(
                    {"event_id": event_id}, failed_report_meta(str(exc))
                )
            except Exception as meta_exc:  # noqa: BLE001
                print(f"[report_status FAILED 기록 실패] {meta_exc}")

        return {
            "statusCode": 200 if not errors else 207,
            "mode": "direct",
            "generated": len(results),
            "skipped": skipped,
            "failed": len(errors),
            "results": results,
            "errors": errors,
        }

    # --- DynamoDB Streams ---
    for rec in event.get("Records", []):
        if rec.get("eventName") not in ("INSERT", "MODIFY"):
            skipped += 1
            continue

        ddb = rec.get("dynamodb", {})
        new_img = _deserialize_image(ddb.get("NewImage"))
        old_img = _deserialize_image(ddb.get("OldImage"))
        ddb_key = _deserialize_image(ddb.get("Keys"))
        if not ddb_key and new_img.get("event_id"):
            ddb_key = {"event_id": new_img["event_id"]}

        if not _should_generate(new_img, old_img):
            skipped += 1
            print(
                f"[skip] event_id={new_img.get('event_id')} "
                f"review={new_img.get('review_status')} "
                f"report={get_report_status(new_img)}"
            )
            continue

        try:
            results.append(generate_report(new_img, ddb_key))
        except Exception as exc:  # noqa: BLE001
            print(f"[오류] event_id={new_img.get('event_id')}: {exc}")
            traceback.print_exc()
            errors.append({"event_id": new_img.get("event_id"), "error": str(exc)})
            try:
                _update_report_meta(ddb_key, failed_report_meta(str(exc)))
            except Exception as meta_exc:  # noqa: BLE001
                print(f"[report_status FAILED 기록 실패] {meta_exc}")

    return {
        "statusCode": 200 if not errors else 207,
        "mode": "stream",
        "generated": len(results),
        "skipped": skipped,
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }
