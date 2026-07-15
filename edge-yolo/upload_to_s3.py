"""upload_to_s3.py — bbox 이미지 렌더 + presigned URL 로 S3 직접 PUT.

이미지 바이트는 API Gateway/Lambda 를 통과하지 않고, ingest 응답으로 받은
presigned URL 로 S3 에 직접 업로드한다. (AWS 자격증명 불필요)
"""

from __future__ import annotations

from typing import List

import requests


def render_bbox(image_path: str, detections: List) -> bytes:
    """원본 이미지에 탐지 bbox+라벨을 그려 JPEG 바이트로 반환한다."""
    import cv2  # ultralytics 와 함께 설치됨

    img = cv2.imread(image_path)
    for d in detections:
        b = d.bbox
        cv2.rectangle(img, (b["x_min"], b["y_min"]), (b["x_max"], b["y_max"]), (0, 0, 255), 2)
        label = f"{d.damage_class} {d.confidence:.2f}"
        cv2.putText(
            img, label, (b["x_min"], max(b["y_min"] - 6, 12)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2,
        )
    ok, buf = cv2.imencode(".jpg", img)
    if not ok:
        raise RuntimeError(f"JPEG 인코딩 실패: {image_path}")
    return buf.tobytes()


def put_image(upload_url: str, data: bytes, content_type: str = "image/jpeg", timeout: int = 30) -> int:
    """presigned URL 로 이미지 바이트를 S3 에 PUT 한다.

    Content-Type 은 presigned URL 생성 시 지정한 값과 반드시 일치해야 한다.
    """
    resp = requests.put(upload_url, data=data, headers={"Content-Type": content_type}, timeout=timeout)
    return resp.status_code
