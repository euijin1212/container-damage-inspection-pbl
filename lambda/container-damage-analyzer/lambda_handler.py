"""실시간 손상 분석 Lambda 핸들러 (MVP).


필요 환경변수 (분석 설정은 src/config.py 참조):
  S3_BUCKET        분석 대상 버킷 (트리거 버킷과 동일)
  BEDROCK_MODEL_ID 비전 지원 모델 ID (Sonnet 4.5)
  DDB_TABLE        업데이트 대상 DynamoDB 테이블명 (기본 InspectionEventTable)
  SNS_TOPIC_ARN    고위험 알림 SNS 토픽 ARN (없으면 알림 스킵)
  RISK_ALERT_LEVEL 알림 트리거 등급 (HIGH | MEDIUM, 기본 HIGH)
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

# 공유 라이브러리(src) 경로 확보:
#   - Lambda 배포 시: 빌드가 src/ 를 이 핸들러와 같은 위치(태스크 루트)에 번들 → 그대로 import
#   - 로컬 실행 시: 리포지토리 루트(두 단계 위)에 있는 src/ 를 사용
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.abspath(os.path.join(_HERE, "..", ".."))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.bedrock_analyzer import BedrockDamageAnalyzer  # noqa: E402
from src.config import settings  # noqa: E402
from src.reinspect_runner import run_reinspect_analysis  # noqa: E402
from src.risk_score import calculate_risk  # noqa: E402
from src.s3_client import S3ImageStore, _IMAGE_EXTS  # noqa: E402

# 콜드스타트 시 1회만 초기화하여 호출 간 재사용 (성능 최적화)
_analyzer = BedrockDamageAnalyzer()
_store = S3ImageStore()
_ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
_sns = boto3.client("sns", region_name=settings.aws_region)

_LEVEL_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

# Lambda 가 처리하는 유일한 S3 프리픽스 (원본 이미지 전용)
_RAW_PREFIX = "raw-images/"

# DynamoDB 테이블 기본값
_DEFAULT_TABLE = "InspectionEventTable"


class ItemNotFoundError(Exception):
    """대상 event_id 의 DynamoDB item 이 존재하지 않을 때 발생."""


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _to_decimal(obj):
    """DynamoDB 는 float/None 을 받지 못하므로 Decimal 변환 + None 제거."""

    def _strip(o):
        if isinstance(o, dict):
            return {k: _strip(v) for k, v in o.items() if v is not None}
        if isinstance(o, list):
            return [_strip(v) for v in o]
        return o

    cleaned = _strip(obj)
    return json.loads(json.dumps(cleaned), parse_float=Decimal, parse_int=Decimal)


def _should_alert(level: Optional[str]) -> bool:
    if not level:
        return False
    threshold = os.getenv("RISK_ALERT_LEVEL", "HIGH").upper()
    return _LEVEL_RANK.get(level, 0) >= _LEVEL_RANK.get(threshold, 2)


def extract_event_id(key: str) -> Optional[str]:
    """S3 object key 에서 event_id 를 추출한다.

    조건:
      - `raw-images/` 프리픽스가 아니면 None (처리 대상 아님)
      - 프리픽스 아래 하위 폴더가 더 있으면 None
      - 이미지 확장자가 아니면 None
      - 확장자를 제거한 파일명만 event_id 로 사용

    예) "raw-images/EVT-20260713-0001.jpg" → "EVT-20260713-0001"
    """
    if not key.startswith(_RAW_PREFIX):
        return None
    filename = key[len(_RAW_PREFIX):]
    if not filename or "/" in filename:
        return None
    stem, ext = os.path.splitext(filename)
    if ext.lower() not in _IMAGE_EXTS:
        return None
    if not stem:
        return None
    return stem


def _parse_s3_records(event: Dict) -> List[Dict[str, str]]:
    """S3 이벤트에서 (bucket, key) 목록을 추출한다."""
    targets = []
    for record in event.get("Records", []):
        s3 = record.get("s3", {})
        bucket = s3.get("bucket", {}).get("name")
        raw_key = s3.get("object", {}).get("key", "")
        # S3 이벤트의 키는 URL 인코딩되어 오므로 디코딩 (공백/한글 대응)
        key = urllib.parse.unquote_plus(raw_key)
        if bucket and key:
            targets.append({"bucket": bucket, "key": key})
    return targets


def _build_image_meta(
    bucket: str, key: str, width: Optional[int] = None, height: Optional[int] = None
) -> Dict:
    """실제 S3 객체 키를 DynamoDB image 에 동기화한다 (.jpg/.png 불일치 방지)."""
    meta = {
        "bucket": bucket,
        "raw_image_key": key,
    }
    if width and height:
        meta["width"] = int(width)
        meta["height"] = int(height)
    return meta


def _image_size(body: bytes, image_format: str) -> tuple:
    """JPEG/PNG 헤더에서 (width, height) 추출. 실패 시 (None, None)."""
    try:
        fmt = (image_format or "").lower()
        if fmt in ("jpeg", "jpg") and body[:2] == b"\xff\xd8":
            i = 2
            while i < len(body) - 8:
                if body[i] != 0xFF:
                    i += 1
                    continue
                marker = body[i + 1]
                if marker in (0xC0, 0xC1, 0xC2):  # SOF
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


def _pixel_bbox_to_pct(bbox: Dict, img_w: Optional[int], img_h: Optional[int]) -> Optional[Dict]:
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


def _build_success_update(
    damages,
    risk,
    model_id: str,
    bucket: str,
    key: str,
    *,
    edge_detections: Optional[List] = None,
    img_w: Optional[int] = None,
    img_h: Optional[int] = None,
    judgment_basis: str = "",
) -> Dict:
    """분석 성공 시 UpdateItem 대상 필드(nested)를 구성한다.

    구조는 mock-data/sample_completed_update.json 과 일치한다.
    YOLO edge bbox 를 그대로 detection.box(퍼센트)에 연결한다.
    """
    edge_detections = edge_detections or []
    detections = []
    for i, d in enumerate(damages):
        det = {
            "damage_class": d.damage_type,
            "severity": d.severity,
            "location": d.location,
            "description": d.note,
            "confidence": round(float(d.confidence), 3),
        }
        # 원래 YOLO 박스만 사용 (새로 만들지 않음)
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

    cloud: Dict = {
        "analysis_status": "COMPLETED",
        "model_name": model_id,
        "inspection_result": "damage" if damages else "normal",
        "detection_count": len(detections),
        "detections": detections,
    }
    basis = (judgment_basis or "").strip()
    if basis:
        cloud["judgment_basis"] = basis[:1200]

    # 위험도와 무관하게 전부 수동 검수
    return {
        "processed_at": _now_iso(),
        "cloud_analysis": cloud,
        "risk": {
            "risk_score": round(risk.risk_score, 1),
            "risk_level": risk.risk_level,
        },
        "review_status": "MANUAL_NEEDED",
        "image": _build_image_meta(bucket, key, img_w, img_h),
    }


def _build_failure_update(error_message: str, bucket: str, key: str) -> Dict:
    """분석 실패 시 UpdateItem 대상 필드(nested)를 구성한다.

    구조는 mock-data/sample_failed_update.json 과 일치한다.
    """
    return {
        "processed_at": _now_iso(),
        "cloud_analysis": {
            "analysis_status": "FAILED",
            "error_message": error_message[:1000],
        },
        "risk": {
            "risk_score": 0,
            "risk_level": "LOW",
        },
        "review_status": "INFERENCE_FAILED",
        "image": _build_image_meta(bucket, key),
    }


def _get_item(event_id: str) -> Optional[Dict]:
    table_name = os.getenv("DDB_TABLE", _DEFAULT_TABLE)
    return _ddb.Table(table_name).get_item(Key={"event_id": event_id}).get("Item")


def _is_pending_for_analysis(item: Dict) -> bool:
    if item.get("review_status") != "PENDING_CLOUD_ANALYSIS":
        return False
    cloud = item.get("cloud_analysis") or {}
    status = cloud.get("analysis_status")
    # RUNNING 은 이미 분석 시작됨(또는 kick 선점). force 경로에서만 재처리.
    return status in (None, "", "PENDING", "RUNNING")


def _update_dynamo(event_id: str, fields: Dict, *, require_pending: bool = False) -> bool:
    """기존 item 의 지정 필드만 UpdateItem 으로 핀셋 업데이트한다.

    - Key: {"event_id": event_id} (Sort Key 없음)
    - ConditionExpression="attribute_exists(event_id)" 로 기존 item 이 있을 때만 갱신
    - require_pending=True 이면 아직 분석 대기 상태인 item 만 갱신
    - item 이 없으면(ConditionalCheckFailed) 새로 만들지 않고 로그만 남긴 뒤 False 반환
    - `report` 속성이 아직 없으면 `report_status=NOT_CREATED`(미생성)로 초기화한다
      (이미 CREATED/PENDING 등이면 덮어쓰지 않음)
    """
    table_name = os.getenv("DDB_TABLE", _DEFAULT_TABLE)
    table = _ddb.Table(table_name)

    values = _to_decimal(fields)
    set_parts = [f"#{k} = :{k}" for k in values]
    expr_names = {f"#{k}": k for k in values}
    expr_values = {f":{k}": v for k, v in values.items()}

    # 보고서 메타가 없으면 미생성으로 초기화 (기존 report 값은 유지)
    set_parts.append("#report = if_not_exists(#report, :report_init)")
    expr_names["#report"] = "report"
    expr_values[":report_init"] = {"report_status": "NOT_CREATED"}

    try:
        condition = "attribute_exists(event_id)"
        if require_pending:
            expr_names["#cloud"] = "cloud_analysis"
            expr_names["#analysis_status"] = "analysis_status"
            expr_names["#review_status"] = "review_status"
            expr_values[":pending_analysis"] = "PENDING"
            expr_values[":running_analysis"] = "RUNNING"
            expr_values[":pending_review"] = "PENDING_CLOUD_ANALYSIS"
            # analysis_status 가 아직 없거나 PENDING/RUNNING 이면 갱신 허용
            condition = (
                "attribute_exists(event_id) AND "
                "#review_status = :pending_review AND "
                "(attribute_not_exists(#cloud.#analysis_status) OR "
                "#cloud.#analysis_status = :pending_analysis OR "
                "#cloud.#analysis_status = :running_analysis)"
            )

        table.update_item(
            Key={"event_id": event_id},
            UpdateExpression="SET " + ", ".join(set_parts),
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
            ConditionExpression=condition,
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            print(
                f"[스킵] event_id={event_id} item이 없거나 이미 처리되어 업데이트하지 않음"
            )
            return False
        raise


def _get_item_with_retry(event_id: str, *, attempts: int = 6, delay_sec: float = 1.0) -> Optional[Dict]:
    """S3 업로드가 PutItem 보다 먼저 올 수 있어 짧게 재시도한다."""
    last: Optional[Dict] = None
    for i in range(attempts):
        last = _get_item(event_id)
        if last:
            if i > 0:
                print(f"[대기] event_id={event_id} DynamoDB item 확인 (시도 {i + 1}/{attempts})")
            return last
        if i + 1 < attempts:
            time.sleep(delay_sec)
    return last


def _publish_alert(event_id: str, risk: Dict) -> bool:
    """고위험일 때 SNS 알림. event_id / risk_level / risk_score 중심으로 단순화."""
    topic = os.getenv("SNS_TOPIC_ARN")
    level = risk.get("risk_level")
    if not topic or not _should_alert(level):
        return False
    msg = (
        "[컨테이너 손상 경보]\n"
        f"event_id: {event_id}\n"
        f"risk_level: {level}\n"
        f"risk_score: {risk.get('risk_score')}"
    )
    _sns.publish(
        TopicArn=topic,
        Subject=f"[{level}] 컨테이너 손상 탐지",
        Message=msg,
    )
    return True


def _resolve_existing_image_key(bucket: str, key: str) -> str:
    """DDB 키와 S3 실제 확장자가 달라도 같은 stem 으로 찾는다."""
    try:
        _store._client.head_object(Bucket=bucket, Key=key)
        return key
    except ClientError:
        pass
    stem, ext = os.path.splitext(key)
    for alt in _IMAGE_EXTS:
        if alt.lower() == ext.lower():
            continue
        candidate = f"{stem}{alt}"
        try:
            _store._client.head_object(Bucket=bucket, Key=candidate)
            print(f"[image] key fallback s3://{bucket}/{key} → {candidate}")
            return candidate
        except ClientError:
            continue
    return key


def _mark_running(event_id: str) -> None:
    """분석 시작 표시. 실패해도 본 분석은 계속한다."""
    try:
        _update_dynamo(
            event_id,
            {
                "cloud_analysis": {
                    "analysis_status": "RUNNING",
                    "started_at": _now_iso(),
                },
            },
            require_pending=False,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[RUNNING 표시 실패] event_id={event_id}: {exc}")


def _process_target(
    bucket: str,
    key: str,
    event_id: str,
    *,
    force: bool = False,
    reviewer_note: str = "",
    reinspect: bool = False,
) -> Dict:
    """단일 (bucket, key) 처리. 실패해도 다른 이미지에 영향 없도록 격리.

    force=True 이면 이미 분석된 item 도 강제 재처리한다.
    reinspect=True 이면 재검수 메모 등 부가 필드를 함께 남긴다.
    """
    existing = _get_item_with_retry(event_id)
    if not existing:
        raise ItemNotFoundError(
            f"event_id={event_id} item이 DynamoDB에 없어 분석을 시작하지 않음"
        )
    print(
        f"[분석시작] event_id={event_id} force={force} "
        f"review_status={existing.get('review_status')} "
        f"model={_analyzer.model_id} s3://{bucket}/{key}"
    )
    if not force and not _is_pending_for_analysis(existing):
        cloud = existing.get("cloud_analysis") or {}
        reason = (
            f"review_status={existing.get('review_status')}, "
            f"analysis_status={cloud.get('analysis_status')}"
        )
        print(f"[스킵] event_id={event_id} 이미 처리됨: {reason}")
        return {
            "event_id": event_id,
            "skipped": True,
            "reason": "already_processed",
            "review_status": existing.get("review_status"),
            "analysis_status": cloud.get("analysis_status"),
        }

    # DDB 에 저장된 키가 더 정확할 수 있음
    image_meta = existing.get("image") or {}
    ddb_bucket = image_meta.get("bucket") or bucket
    ddb_key = image_meta.get("raw_image_key") or key
    bucket = str(ddb_bucket)
    key = _resolve_existing_image_key(bucket, str(ddb_key))

    edge = existing.get("edge") or {}
    edge_detections = list(edge.get("edge_detections") or [])

    # --- 다운로드 먼저 (실패 시 RUNNING 으로 안 남김) ---
    # ingest POST 직후·S3 PUT 전 race / 일시 AccessDenied 대비 짧은 재시도
    image = None
    last_exc: Optional[BaseException] = None
    for attempt in range(1, 6):
        try:
            key = _resolve_existing_image_key(bucket, key)
            image = _store.download_from(bucket, key)
            print(
                f"[다운로드] event_id={event_id} bytes={len(image.body)} "
                f"fmt={image.image_format} attempt={attempt}"
            )
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            print(f"[다운로드대기] event_id={event_id} attempt={attempt}/5: {exc}")
            if attempt < 5:
                time.sleep(2 * attempt)
    if image is None:
        print(f"[다운로드실패] event_id={event_id}: {last_exc}")
        traceback.print_exc()
        try:
            _update_dynamo(
                event_id,
                _build_failure_update(
                    f"s3 download failed: {last_exc}", bucket, key
                ),
                require_pending=False,
            )
        except Exception as upd_exc:  # noqa: BLE001
            print(f"[실패저장도 실패] event_id={event_id}: {upd_exc}")
        raise last_exc if last_exc else RuntimeError("s3 download failed")

    if not force:
        _mark_running(event_id)

    # --- 분석 단계 ---
    try:
        analysis = _analyzer.analyze(
            image.body,
            image.image_format,
            reviewer_note=reviewer_note or None,
        )
        damages = analysis.damages
        judgment_basis = analysis.judgment_basis
        risk = calculate_risk(damages)
        print(
            f"[모델응답] event_id={event_id} damages={len(damages)} "
            f"risk={risk.risk_level}/{risk.risk_score} "
            f"judgment_len={len(judgment_basis or '')}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[분석실패] event_id={event_id}: {exc}")
        traceback.print_exc()
        try:
            _update_dynamo(
                event_id,
                _build_failure_update(str(exc), bucket, key),
                require_pending=False,
            )
        except Exception as upd_exc:  # noqa: BLE001
            print(f"[실패저장도 실패] event_id={event_id}: {upd_exc}")
        raise

    img_w, img_h = _image_size(image.body, image.image_format)

    # --- 성공 업데이트 단계 ---
    update = _build_success_update(
        damages,
        risk,
        _analyzer.model_id,
        bucket,
        key,
        edge_detections=edge_detections,
        img_w=img_w,
        img_h=img_h,
        judgment_basis=judgment_basis,
    )
    if reviewer_note.strip():
        update["review_memo"] = reviewer_note.strip()[:1000]

    try:
        ok = _update_dynamo(event_id, update, require_pending=not force)
    except Exception as exc:  # noqa: BLE001
        print(f"[업데이트실패] event_id={event_id}: {exc}")
        traceback.print_exc()
        ok = False

    if not ok:
        # PENDING 고착 방지: 조건 없이 재시도
        try:
            ok = _update_dynamo(event_id, update, require_pending=False)
        except Exception as exc:  # noqa: BLE001
            print(f"[업데이트 재시도 실패] event_id={event_id}: {exc}")
            traceback.print_exc()
            ok = False

    if not ok:
        return {
            "event_id": event_id,
            "skipped": True,
            "reason": "already_processed_during_update",
        }

    notified = _publish_alert(event_id, update["risk"])
    print(
        f"[분석완료] event_id={event_id} → {update['review_status']} "
        f"risk={update['risk']['risk_level']} "
        f"(score={update['risk']['risk_score']}, "
        f"detections={update['cloud_analysis']['detection_count']}, "
        f"force={force}, notified={notified})"
    )
    return {"event_id": event_id, **update}


def _resolve_image_location(item: Dict) -> Tuple[str, str]:
    """item.image 에서 (bucket, key) 를 얻는다."""
    image = item.get("image") or {}
    bucket = image.get("bucket") or os.getenv("S3_BUCKET") or settings.s3_bucket
    key = image.get("raw_image_key")
    if not bucket or not key:
        raise ValueError("image.bucket / image.raw_image_key 가 없어 재검수할 수 없음")
    return str(bucket), str(key)


def _mark_reinspect_pending(event_id: str, reviewer_note: str) -> None:
    """재검수 시작 전 상태를 분석 대기로 되돌린다."""
    note = (reviewer_note or "").strip()
    cloud: Dict = {
        "analysis_status": "PENDING",
        "reinspect": True,
    }
    if note:
        cloud["reinspect_note"] = note[:500]
    _update_dynamo(
        event_id,
        {
            "review_status": "PENDING_CLOUD_ANALYSIS",
            "cloud_analysis": cloud,
            "review_memo": note[:1000] if note else "재검수 요청",
        },
        require_pending=False,
    )


def _process_reinspect(event_id: str, reviewer_note: str = "") -> Dict:
    """재검수: 기존 bbox 안만 화질개선·재판정 후 DynamoDB 갱신."""
    existing = _get_item(event_id)
    if not existing:
        raise ItemNotFoundError(f"event_id={event_id} item이 DynamoDB에 없음")

    bucket, key = _resolve_image_location(existing)
    key = _resolve_existing_image_key(bucket, key)
    note = (reviewer_note or "").strip()
    edge = existing.get("edge") or {}
    cloud = existing.get("cloud_analysis") or {}
    print(f"[재검수] event_id={event_id} note_len={len(note)} s3://{bucket}/{key}")
    _mark_reinspect_pending(event_id, note)
    fields = run_reinspect_analysis(
        bucket=bucket,
        key=key,
        reviewer_note=note,
        edge_detections=list(edge.get("edge_detections") or []),
        cloud_detections=list(cloud.get("detections") or []),
        reviewer="analyzer",
    )
    ok = _update_dynamo(event_id, fields, require_pending=False)
    return {"event_id": event_id, "updated": ok, **fields}


def lambda_handler(event: Dict, context=None) -> Dict:
    event = event or {}
    results: List[Dict] = []
    errors: List[Dict] = []

    # 진입 로그 (S3 트리거 여부 판별용)
    records = event.get("Records") or []
    print(
        f"[handler] action={event.get('action')!r} "
        f"event_id={event.get('event_id')!r} "
        f"s3_records={len(records)} "
        f"model={_analyzer.model_id}"
    )
    if records:
        for i, rec in enumerate(records[:3]):
            s3 = (rec or {}).get("s3") or {}
            print(
                f"[handler] record[{i}] "
                f"bucket={(s3.get('bucket') or {}).get('name')} "
                f"key={(s3.get('object') or {}).get('key')}"
            )

    # 대시보드/복구 직접 호출: { "action": "reinspect"|"analyze", "event_id": "...", ... }
    if event.get("action") in ("reinspect", "analyze") and event.get("event_id"):
        event_id = str(event["event_id"])
        note = str(event.get("reviewer_note") or event.get("memo") or "")
        try:
            if event.get("action") == "reinspect":
                results.append(_process_reinspect(event_id, note))
            else:
                # 분석 중으로 멈춘 건 강제 재처리
                existing = _get_item(event_id)
                if not existing:
                    raise ItemNotFoundError(f"event_id={event_id} 없음")
                bucket, key = _resolve_image_location(existing)
                results.append(
                    _process_target(bucket, key, event_id, force=True, reviewer_note=note)
                )
        except Exception as exc:  # noqa: BLE001
            print(f"[오류] {event.get('action')} event_id={event_id}: {exc}")
            traceback.print_exc()
            errors.append({"event_id": event_id, "error": str(exc)})
        return {
            "statusCode": 200 if not errors else 207,
            "mode": str(event.get("action")),
            "processed": len(results),
            "failed": len(errors),
            "results": results,
            "errors": errors,
        }

    for target in _parse_s3_records(event):
        bucket, key = target["bucket"], target["key"]
        event_id = extract_event_id(key)
        if event_id is None:
            # raw-images/ 프리픽스가 아니거나 이미지가 아닌 key 는 스킵
            print(f"[스킵] 처리 대상 아님: s3://{bucket}/{key}")
            continue
        try:
            results.append(_process_target(bucket, key, event_id))
        except Exception as exc:  # noqa: BLE001 - 한 장 실패가 전체를 막지 않도록
            print(f"[오류] s3://{bucket}/{key} (event_id={event_id}): {exc}")
            traceback.print_exc()
            errors.append({"key": key, "event_id": event_id, "error": str(exc)})

    return {
        "statusCode": 200 if not errors else 207,
        "processed": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }
