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
import traceback
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

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
    """DynamoDB 는 float 를 받지 못하므로 Decimal 로 변환 (None/null 은 그대로 유지)."""
    return json.loads(json.dumps(obj), parse_float=Decimal, parse_int=Decimal)


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


def _build_success_update(damages, risk, model_id: str) -> Dict:
    """분석 성공 시 UpdateItem 대상 필드(nested)를 구성한다.

    구조는 mock-data/sample_completed_update.json 과 일치한다.
    """
    detections = [
        {
            "damage_class": d.damage_type,
            "severity": d.severity,
            "location": d.location,
            "description": d.note,
        }
        for d in damages
    ]
    confidences = [d.confidence for d in damages]

    review_status = (
        "MANUAL_NEEDED" if risk.risk_level in ("HIGH", "MEDIUM") else "AUTO_OK"
    )
    return {
        "processed_at": _now_iso(),
        "cloud_analysis": {
            "analysis_status": "COMPLETED",
            "model_name": model_id,
            "inspection_result": "damage" if damages else "normal",
            "confidence": round(max(confidences), 3) if confidences else None,
            "detection_count": len(detections),
            "detections": detections,
        },
        "risk": {
            "risk_score": round(risk.risk_score, 1),
            "risk_level": risk.risk_level,
        },
        "review_status": review_status,
    }


def _build_failure_update(error_message: str) -> Dict:
    """분석 실패 시 UpdateItem 대상 필드(nested)를 구성한다.

    구조는 mock-data/sample_failed_update.json 과 일치한다.
    """
    return {
        "processed_at": _now_iso(),
        "cloud_analysis": {
            "analysis_status": "FAILED",
            "error_message": error_message,
        },
        "risk": {
            "risk_score": None,
            "risk_level": None,
        },
        "review_status": "INFERENCE_FAILED",
    }


def _update_dynamo(event_id: str, fields: Dict) -> bool:
    """기존 item 의 지정 필드만 UpdateItem 으로 핀셋 업데이트한다.

    - Key: {"event_id": event_id} (Sort Key 없음)
    - ConditionExpression="attribute_exists(event_id)" 로 기존 item 이 있을 때만 갱신
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
        table.update_item(
            Key={"event_id": event_id},
            UpdateExpression="SET " + ", ".join(set_parts),
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
            ConditionExpression="attribute_exists(event_id)",
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            print(
                f"[스킵] DynamoDB에 event_id={event_id} item이 없어 업데이트하지 않음 "
                f"(Simulator PENDING item 미생성). 새 item을 만들지 않습니다."
            )
            return False
        raise


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


def _process_target(bucket: str, key: str, event_id: str) -> Dict:
    """단일 (bucket, key) 처리. 실패해도 다른 이미지에 영향 없도록 격리."""
    # --- 분석 단계 (실패 시 FAILED 업데이트 시도 후 예외 전파) ---
    try:
        image = _store.download_from(bucket, key)
        damages = _analyzer.analyze(image.body, image.image_format)
        risk = calculate_risk(damages)
    except Exception as exc:  # noqa: BLE001
        print(f"[분석실패] event_id={event_id}: {exc}")
        _update_dynamo(event_id, _build_failure_update(str(exc)))
        raise

    # --- 성공 업데이트 단계 ---
    update = _build_success_update(damages, risk, _analyzer.model_id)
    if not _update_dynamo(event_id, update):
        # 분석은 성공했으나 대상 item 이 없음 → 새로 만들지 않고 에러로 처리
        raise ItemNotFoundError(
            f"event_id={event_id} item이 DynamoDB에 없어 업데이트를 건너뜀"
        )

    notified = _publish_alert(event_id, update["risk"])
    print(
        f"[분석완료] event_id={event_id} → {update['risk']['risk_level']} "
        f"(score={update['risk']['risk_score']}, "
        f"detections={update['cloud_analysis']['detection_count']}, "
        f"notified={notified})"
    )
    return {"event_id": event_id, **update}


def lambda_handler(event: Dict, context=None) -> Dict:
    results: List[Dict] = []
    errors: List[Dict] = []

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
