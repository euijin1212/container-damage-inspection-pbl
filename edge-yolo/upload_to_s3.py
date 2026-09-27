"""upload_to_s3.py — bbox 이미지 렌더 + presigned URL 로 S3 직접 PUT.

이미지 바이트는 API Gateway/Lambda 를 통과하지 않고, ingest 응답으로 받은
presigned URL 로 S3 에 직접 업로드한다. (AWS 자격증명 불필요)
"""

from __future__ import annotations

from typing import List

import numpy as np
import requests


def _imread_unicode(path: str):
    """Windows 경로/한글 경로에서도 안정적으로 읽는 imread."""
    import cv2

    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def render_bbox(image_path: str, detections: List) -> bytes:
    """원본 이미지에 탐지 bbox 를 그려 JPEG 바이트로 반환한다."""
    import cv2

    img = _imread_unicode(image_path)
    if img is None:
        # 디코드 실패 시 원본 바이트라도 업로드 (깨진 JPEG 생성 방지)
        with open(image_path, "rb") as f:
            raw = f.read()
        if not raw:
            raise RuntimeError(f"이미지 읽기 실패: {image_path}")
        return raw

    h, w = img.shape[:2]
    for d in detections:
        b = getattr(d, "bbox", None) or {}
        try:
            x1 = int(max(0, min(w - 1, b["x_min"])))
            y1 = int(max(0, min(h - 1, b["y_min"])))
            x2 = int(max(0, min(w - 1, b["x_max"])))
            y2 = int(max(0, min(h - 1, b["y_max"])))
        except (KeyError, TypeError, ValueError):
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        # 박스만 그린다(신뢰도 숫자·라벨 없음)
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)

    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        raise RuntimeError(f"JPEG 인코딩 실패: {image_path}")
    return buf.tobytes()


def put_image(upload_url: str, data: bytes, content_type: str = "image/jpeg", timeout: int = 30) -> int:
    """presigned URL 로 이미지 바이트를 S3 에 PUT 한다.

    Content-Type 은 presigned URL 생성 시 지정한 값과 반드시 일치해야 한다.
    """
    resp = requests.put(
        upload_url,
        data=data,
        headers={"Content-Type": content_type},
        timeout=timeout,
    )
    return resp.status_code
