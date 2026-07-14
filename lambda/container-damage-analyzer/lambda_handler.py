"""실시간 손상 분석 Lambda 핸들러.

S3(`container-damage`) 버킷에 이미지가 업로드되면 ObjectCreated 이벤트로 트리거되어,
방금 올라온 이미지 1장을 Foundation Model(Sonnet 4.5)로 분석하고 Risk Score를 산출한 뒤,
S3 메타데이터 · YOLO 결과 · Foundation Model 결과를 통합해 DynamoDB에 저장하고
고위험이면 SNS로 알림한다.

배포 핸들러: `lambda_handler.lambda_handler`

필요 환경변수 (분석 설정은 src/config.py 참조):
  S3_BUCKET        분석 대상 버킷 (트리거 버킷과 동일)
  BEDROCK_MODEL_ID 비전 지원 모델 ID (Sonnet 4.5)
  DDB_TABLE        결과 기록 DynamoDB 테이블명 (없으면 기록 스킵)
  SNS_TOPIC_ARN    고위험 알림 SNS 토픽 ARN (없으면 알림 스킵)
  RISK_ALERT_LEVEL 알림 트리거 등급 (HIGH | MEDIUM, 기본 HIGH)
"""

from __future__ import annotations

import json
import os
import sys
import traceback
import urllib.parse
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List

import boto3

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


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _to_decimal(obj):
    """DynamoDB 는 float 를 받지 못하므로 Decimal 로 변환."""
    return json.loads(json.dumps(obj), parse_float=Decimal, parse_int=Decimal)


def _should_alert(level: str) -> bool:
    threshold = os.getenv("RISK_ALERT_LEVEL", "HIGH").upper()
    return _LEVEL_RANK.get(level, 0) >= _LEVEL_RANK.get(threshold, 2)


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


def analyze_one(bucket: str, key: str) -> Dict:
    """이미지 1장을 분석해 검수 결과 레코드를 만든다."""
    image = _store.download_from(bucket, key)
    damages = _analyzer.analyze(image.body, image.image_format)
    risk = calculate_risk(damages)

    detections = [
        {
            "class": d.damage_type,
            "severity": d.severity,
            "confidence": round(d.confidence, 3),
            "location": d.location,
            "note": d.note,
        }
        for d in damages
    ]

    # 대표값: 가장 위험한 손상 기준
    top = risk.components[0] if risk.components else None
    processed_at = _now_iso()
    return {
        "event_id": "evt_" + uuid.uuid4().hex[:12],
        "event_date": processed_at[:10],
        "processed_at": processed_at,
        "inspection_result": "damage" if damages else "normal",
        "confidence": max((d["confidence"] for d in detections), default=None),
        "detection_count": len(detections),
        "detections": detections,
        "location": top["location"] if top else None,
        "risk_score": round(risk.risk_score, 1),
        "risk_level": risk.risk_level,
        "risk_breakdown": risk.components,
        "image_path": image.uri,
        "image_type": "annotated" if damages else "raw",
        "model_version": _analyzer.model_id,
        "review_status": "MANUAL_NEEDED"
        if risk.risk_level in ("HIGH", "MEDIUM")
        else "AUTO_OK",
        "notified": False,
    }


def _save_to_dynamo(record: Dict) -> None:
    table_name = os.getenv("DDB_TABLE")
    if not table_name:
        return
    _ddb.Table(table_name).put_item(Item=_to_decimal(record))


def _publish_alert(record: Dict) -> bool:
    topic = os.getenv("SNS_TOPIC_ARN")
    if not topic or not _should_alert(record["risk_level"]):
        return False
    msg = (
        f"[컨테이너 손상 경보] {record['risk_level']} (score={record['risk_score']})\n"
        f"이미지: {record['image_path']}\n"
        f"손상 {record['detection_count']}건: "
        + ", ".join(f"{d['class']}/{d['severity']}" for d in record["detections"])
    )
    _sns.publish(
        TopicArn=topic,
        Subject=f"[{record['risk_level']}] 컨테이너 손상 탐지",
        Message=msg,
    )
    return True


def _process_target(bucket: str, key: str) -> Dict:
    """단일 (bucket, key) 처리. 실패해도 다른 이미지에 영향 없도록 격리."""
    record = analyze_one(bucket, key)
    record["notified"] = _publish_alert(record)
    _save_to_dynamo(record)
    print(
        f"[분석완료] {record['image_path']} → {record['risk_level']} "
        f"(score={record['risk_score']}, detections={record['detection_count']})"
    )
    return record


def lambda_handler(event: Dict, context=None) -> Dict:
    results: List[Dict] = []
    errors: List[Dict] = []

    for target in _parse_s3_records(event):
        bucket, key = target["bucket"], target["key"]
        if not key.lower().endswith(_IMAGE_EXTS):
            print(f"[스킵] 이미지 아님: s3://{bucket}/{key}")
            continue
        try:
            results.append(_process_target(bucket, key))
        except Exception as exc:  # noqa: BLE001 - 한 장 실패가 전체를 막지 않도록
            print(f"[오류] s3://{bucket}/{key}: {exc}")
            traceback.print_exc()
            errors.append({"key": key, "error": str(exc)})

    return {
        "statusCode": 200 if not errors else 207,
        "processed": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }
