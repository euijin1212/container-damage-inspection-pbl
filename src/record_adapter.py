"""record_adapter.py — MVP DynamoDB item → 보고서 계층용 flat dict 변환.

MVP 스키마는 `container`, `cloud_analysis`, `risk`, `report` 등 중첩 구조를 사용한다.
`report_writer` / `pdf_report` 는 내부적으로 flat dict 를 사용하므로,
이 모듈에서 한 번 정규화한다.
"""

from __future__ import annotations

from typing import Dict, List, Optional

# 보고서 생성 상태 (report.report_status)
REPORT_NOT_CREATED = "NOT_CREATED"  # 미생성
REPORT_PENDING = "PENDING"          # 생성중
REPORT_CREATED = "CREATED"          # 생성완료
REPORT_FAILED = "FAILED"            # 생성실패


def _first_location(detections: List[Dict]) -> Optional[str]:
    for d in detections:
        loc = d.get("location")
        if loc:
            return loc
    return None


def normalize_inspection_record(record: Dict) -> Dict:
    """DynamoDB 검수 item(MVP 중첩 또는 legacy flat)을 보고서용 flat dict 로 변환."""
    # 이미 flat 필드가 있으면 MVP 중첩 값으로 보완만 한다.
    if record.get("detections") and not (record.get("cloud_analysis") or {}).get("detections"):
        return {
            "event_id": record.get("event_id"),
            "container_id": record.get("container_id")
            or (record.get("container") or {}).get("container_id"),
            "captured_at": record.get("captured_at"),
            "processed_at": record.get("processed_at"),
            "inspection_result": record.get("inspection_result"),
            "detection_count": record.get("detection_count", len(record.get("detections") or [])),
            "detections": record.get("detections") or [],
            "risk_score": record.get("risk_score") or (record.get("risk") or {}).get("risk_score"),
            "risk_level": record.get("risk_level") or (record.get("risk") or {}).get("risk_level"),
            "model_version": record.get("model_version")
            or (record.get("cloud_analysis") or {}).get("model_name"),
            "location": record.get("location") or _first_location(record.get("detections") or []),
        }

    cloud = record.get("cloud_analysis") or {}
    risk = record.get("risk") or {}
    container = record.get("container") or {}

    detections: List[Dict] = []
    for d in cloud.get("detections") or []:
        detections.append(
            {
                "class": d.get("damage_class"),
                "severity": d.get("severity"),
                "confidence": d.get("confidence") or cloud.get("confidence"),
                "location": d.get("location"),
                "description": d.get("description"),
            }
        )

    return {
        "event_id": record.get("event_id"),
        "container_id": container.get("container_id"),
        "captured_at": record.get("captured_at"),
        "processed_at": record.get("processed_at"),
        "inspection_result": cloud.get("inspection_result"),
        "detection_count": cloud.get("detection_count", len(detections)),
        "detections": detections,
        "risk_score": risk.get("risk_score"),
        "risk_level": risk.get("risk_level"),
        "model_version": cloud.get("model_name"),
        "location": _first_location(detections),
    }


def get_report_status(record: Dict) -> Optional[str]:
    """MVP `report.report_status` 또는 legacy `report_status` 를 읽는다."""
    report = record.get("report") or {}
    return report.get("report_status") or record.get("report_status")


def initial_report_meta() -> Dict:
    """PutItem/분석 완료 시점에 넣는 보고서 초기 메타 (미생성)."""
    return {"report_status": REPORT_NOT_CREATED}


def pending_report_meta() -> Dict:
    """보고서 생성 시작 시 메타 (생성중)."""
    return {"report_status": REPORT_PENDING}


def created_report_meta(
    *,
    report_path: str,
    generated_at: str,
    reuse_decision: str = "",
    report_summary: str = "",
) -> Dict:
    """보고서 생성 완료 시 메타."""
    return {
        "report_status": REPORT_CREATED,
        "report_path": report_path,
        "report_generated_at": generated_at,
        "reuse_decision": reuse_decision,
        "report_summary": report_summary,
    }


def failed_report_meta(error_message: str) -> Dict:
    """보고서 생성 실패 시 메타."""
    return {
        "report_status": REPORT_FAILED,
        "error_message": (error_message or "")[:500],
    }
