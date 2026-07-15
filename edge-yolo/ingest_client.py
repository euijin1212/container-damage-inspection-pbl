"""ingest_client.py — inspection-event-ingest API 호출.

POST {INGEST_API_URL}/inspection-events 로 메타데이터를 보내면,
ingest Lambda 가 DynamoDB PENDING PutItem 후 presigned PUT URL 을 돌려준다.
(lambda/inspection-event-ingest/handler.py 계약)
"""

from __future__ import annotations

from typing import Dict, Tuple

import requests


def post_event(
    api_url: str,
    payload: Dict,
    path: str = "/inspection-events",
    timeout: int = 15,
) -> Tuple[int, Dict]:
    """메타데이터를 POST 하고 (status_code, 응답 JSON) 을 반환한다.

    성공(201) 응답 예: {event_id, bucket, raw_image_key, upload_url, expires_in}
    """
    url = api_url.rstrip("/") + path
    resp = requests.post(url, json=payload, timeout=timeout)
    data: Dict = {}
    try:
        data = resp.json() if resp.content else {}
    except ValueError:
        data = {"raw": resp.text}
    return resp.status_code, data
