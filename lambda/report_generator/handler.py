"""비동기 보고서 자동화 Lambda 핸들러 (DynamoDB Streams 트리거).

아키텍처 4계층("비동기 보고서 자동화")을 구현한다:

    DynamoDB(검수 상태 변경) → Streams → 이 Lambda → Bedrock(초안) →
    PDF 렌더 → S3(reports/, 최종 EIR) → DynamoDB(보고서 메타 업데이트)

report.report_status 전이
-------------------------
  NOT_CREATED(미생성) → PENDING(생성중) → CREATED(생성완료)
                                       └→ FAILED(생성실패)

동작
----
검수자가 대시보드에서 검수를 마쳐 item 의 `review_status` 가 `DONE` 으로 바뀌면,
DynamoDB Streams 가 이 Lambda 를 트리거한다. Lambda 는 해당 item 으로 EIR 보고서를
Bedrock 으로 작성하고 PDF 로 만들어 S3 에 저장한 뒤, 원본 item 의 `report` 중첩
객체를 갱신한다.

멱등성
------
`report.report_status` 가 이미 `CREATED`/`PENDING` 이면 재생성하지 않는다
(중복 트리거·스트림 재처리 방지). `FAILED` 는 재시도 가능.

배포 핸들러: `handler.lambda_handler`

필요 환경변수:
  DDB_TABLE        검수 이벤트 테이블명 (기본 InspectionEventTable)
  REPORT_BUCKET    PDF 저장 버킷 (없으면 S3_BUCKET 사용)
  REPORT_PREFIX    PDF 키 프리픽스 (기본 "reports/")
  BEDROCK_MODEL_ID 보고서 생성 모델 ID (src/config.py 기본값)
  REPORT_FONT_PATH 한글 TTF 경로 (PDF 한글 렌더링용, 선택)
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

import boto3
from boto3.dynamodb.types import TypeDeserializer

# 공유 라이브러리(src) 경로 확보 (analyzer 핸들러와 동일 전략):
#   - 배포 시: 빌드가 src/ 를 핸들러 옆(태스크 루트)에 번들
#   - 로컬 실행 시: 리포지토리 루트(두 단계 위)의 src/ 사용
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

# 콜드스타트 시 1회 초기화하여 호출 간 재사용
_writer = BedrockReportWriter()
_s3 = boto3.client("s3", region_name=settings.aws_region)
_ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
_deserializer = TypeDeserializer()

_DEFAULT_TABLE = "InspectionEventTable"

# 생성중/생성완료면 재생성하지 않는다 (FAILED·NOT_CREATED 는 재시도 허용)
_SKIP_REPORT_STATUS = {REPORT_CREATED, REPORT_PENDING}
# 이 값으로 review_status 가 바뀌었을 때만 보고서를 생성한다.
_TRIGGER_REVIEW_STATUS = "DONE"
# 재시도 가능한 보고서 상태
_RETRYABLE_REPORT_STATUS = {None, "", REPORT_NOT_CREATED, REPORT_FAILED}


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _to_native(obj):
    """DynamoDB Decimal 을 사람이 쓰기 좋은 int/float 로 변환한다."""
    if isinstance(obj, list):
        return [_to_native(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    return obj


def _deserialize_image(image: Optional[Dict]) -> Dict:
    """Streams 의 타입 표기(image)를 일반 파이썬 dict 로 변환한다."""
    if not image:
        return {}
    plain = {k: _deserializer.deserialize(v) for k, v in image.items()}
    return _to_native(plain)


def _should_generate(new_img: Dict, old_img: Dict) -> bool:
    """보고서 생성 트리거 조건.

    - review_status 가 DONE 일 것
    - report_status 가 CREATED/PENDING 이 아닐 것 (생성중·완료면 스킵)
    - 이미 DONE 이었던 item 은 NOT_CREATED/FAILED/없음 일 때만 생성(재시도)
    """
    if new_img.get("review_status") != _TRIGGER_REVIEW_STATUS:
        return False

    status = get_report_status(new_img)
    if status in _SKIP_REPORT_STATUS:
        return False

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
    """원본 item 의 `report` 중첩 객체를 UpdateItem 으로 갱신한다."""
    table_name = os.getenv("DDB_TABLE", _DEFAULT_TABLE)
    if not ddb_key:
        print("[report] 스트림 Keys 없음 → 메타 업데이트 스킵")
        return

    status = report_fields.get("report_status", "?")
    print(
        f"[report_status] event_id={ddb_key.get('event_id')} → {status}"
    )
    _ddb.Table(table_name).update_item(
        Key=ddb_key,
        UpdateExpression="SET #report = :report",
        ExpressionAttributeNames={"#report": "report"},
        ExpressionAttributeValues={":report": report_fields},
    )


def generate_report(record: Dict, ddb_key: Dict) -> Dict:
    """검수 레코드 1건으로 보고서를 생성·저장하고 report_status 를 갱신한다.

    전이: NOT_CREATED/없음 → PENDING → CREATED (실패 시 FAILED)
    """
    bucket = os.getenv("REPORT_BUCKET") or settings.s3_bucket
    key = _report_key(record)
    event_id = record.get("event_id")

    # 1) 생성중
    _update_report_meta(ddb_key, pending_report_meta())

    try:
        draft = _writer.write(record)
        pdf_bytes = build_report_pdf(record, draft)

        _s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
        report_path = f"s3://{bucket}/{key}"
        generated_at = _now_iso()

        # 2) 생성완료
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
        # 3) 생성실패 — 호출측에서 로깅/집계. 여기서는 status 만 FAILED 로 남긴다.
        raise


def lambda_handler(event: Dict, context=None) -> Dict:
    results: List[Dict] = []
    skipped = 0
    errors: List[Dict] = []

    for rec in event.get("Records", []):
        if rec.get("eventName") not in ("INSERT", "MODIFY"):
            skipped += 1
            continue

        ddb = rec.get("dynamodb", {})
        new_img = _deserialize_image(ddb.get("NewImage"))
        old_img = _deserialize_image(ddb.get("OldImage"))
        # 스트림이 제공하는 실제 테이블 기본 키(파티션/정렬 키)를 그대로 사용
        ddb_key = _deserialize_image(ddb.get("Keys"))

        if not _should_generate(new_img, old_img):
            skipped += 1
            continue

        try:
            results.append(generate_report(new_img, ddb_key))
        except Exception as exc:  # noqa: BLE001 - 한 건 실패가 전체를 막지 않도록
            print(f"[오류] event_id={new_img.get('event_id')}: {exc}")
            traceback.print_exc()
            errors.append({"event_id": new_img.get("event_id"), "error": str(exc)})
            try:
                _update_report_meta(ddb_key, failed_report_meta(str(exc)))
            except Exception as meta_exc:  # noqa: BLE001
                print(f"[report_status FAILED 기록 실패] {meta_exc}")

    return {
        "statusCode": 200 if not errors else 207,
        "generated": len(results),
        "skipped": skipped,
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }
