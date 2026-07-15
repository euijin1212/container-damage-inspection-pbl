"""s3_client.py — S3 이미지 조회/다운로드 유틸 (파이프라인 1단계: 입력).

역할
----
엣지에서 업로드되어 손상 bbox 가 표시된 이미지들을 S3 버킷에서 나열하고,
Foundation Model 재분석을 위해 이미지 바이트로 내려받는다.

주요 구성요소
------------
- `S3Image`     : 다운로드된 이미지 1건(버킷/키/바이트/포맷). `.uri` 로 s3:// 경로 제공
- `S3ImageStore`: 버킷 접근 래퍼
    - `list_image_keys()`      : 프리픽스 하위 이미지 키 목록
    - `download(key)`          : 설정된 버킷에서 1장 다운로드
    - `download_from(bkt,key)` : 임의 버킷/키 다운로드 (S3 이벤트/Lambda 용)
    - `iter_images()`          : 프리픽스 하위 전체를 순차 다운로드

입력: 버킷명/프리픽스(config) 또는 이벤트의 bucket/key
출력: `S3Image` (→ bedrock_analyzer 로 전달)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterator, List, Optional

import boto3

from .config import settings

# 이미지로 취급할 확장자
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# 확장자 → Bedrock converse API 가 요구하는 format 값
_FORMAT_MAP = {
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".webp": "webp",
}


@dataclass
class S3Image:
    """다운로드된 S3 이미지 1건."""

    bucket: str
    key: str
    body: bytes
    image_format: str  # "jpeg" | "png" | "webp"

    @property
    def uri(self) -> str:
        return f"s3://{self.bucket}/{self.key}"


class S3ImageStore:
    """손상 이미지 버킷 접근 래퍼."""

    def __init__(
        self,
        bucket: Optional[str] = None,
        prefix: Optional[str] = None,
        client=None,
    ) -> None:
        self.bucket = bucket or settings.s3_bucket
        self.prefix = prefix if prefix is not None else settings.s3_prefix
        self._client = client or boto3.client("s3", region_name=settings.aws_region)

    def list_image_keys(self) -> List[str]:
        """프리픽스 하위의 이미지 오브젝트 키 목록을 반환한다."""
        keys: List[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.lower().endswith(_IMAGE_EXTS):
                    keys.append(key)
        return keys

    def download(self, key: str) -> S3Image:
        """설정된 버킷에서 단일 오브젝트를 바이트로 내려받는다."""
        return self.download_from(self.bucket, key)

    def download_from(self, bucket: str, key: str) -> S3Image:
        """임의 버킷/키 오브젝트를 바이트로 내려받는다 (S3 이벤트용)."""
        resp = self._client.get_object(Bucket=bucket, Key=key)
        body = resp["Body"].read()
        ext = os.path.splitext(key)[1].lower()
        image_format = _FORMAT_MAP.get(ext, "jpeg")
        return S3Image(bucket=bucket, key=key, body=body, image_format=image_format)

    def upload(
        self,
        key: str,
        body: bytes,
        *,
        bucket: Optional[str] = None,
        content_type: str = "image/png",
    ) -> str:
        """바이트를 S3 에 업로드하고 key 를 반환한다."""
        target = bucket or self.bucket
        self._client.put_object(
            Bucket=target,
            Key=key,
            Body=body,
            ContentType=content_type,
        )
        return key

    def iter_images(self) -> Iterator[S3Image]:
        """프리픽스 하위 이미지를 순차적으로 다운로드하며 순회한다."""
        for key in self.list_image_keys():
            yield self.download(key)
