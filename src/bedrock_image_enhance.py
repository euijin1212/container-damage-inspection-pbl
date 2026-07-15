"""Bedrock Foundation Model 기반 이미지 화질 개선.

재검수 시 Nova Canvas IMAGE_VARIATION 으로 선명도·대비를 올린 뒤
손상 재감지에 사용한다. (Nova Canvas 는 ap-northeast-2 미지원 → 기본 us-east-1)
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from .config import settings

_ENHANCE_PROMPT = (
    "Enhance this shipping container inspection photo: increase sharpness, "
    "clarity, local contrast and reduce noise/blur. Keep the exact same "
    "container, camera angle, damage regions and any bounding-box markings. "
    "Photorealistic, no new objects, no text overlay, no style change."
)

_NEGATIVE = (
    "blurry, low resolution, cartoon, painting, distorted structure, "
    "added objects, removed damage, watermark, text overlay"
)


@dataclass
class EnhancedImage:
    body: bytes
    image_format: str  # "png" | "jpeg"
    model_id: str
    used_fallback: bool = False


class BedrockImageEnhancer:
    """Foundation Model 으로 검수 이미지 화질을 개선한다."""

    def __init__(
        self,
        model_id: Optional[str] = None,
        region: Optional[str] = None,
        client=None,
    ) -> None:
        self.model_id = model_id or settings.bedrock_image_model_id
        self.region = region or settings.bedrock_image_region
        self._client = client or boto3.client(
            "bedrock-runtime", region_name=self.region
        )

    def enhance(
        self,
        image_bytes: bytes,
        *,
        similarity_strength: float = 0.85,
    ) -> EnhancedImage:
        """화질 개선 이미지를 반환. 실패 시 원본을 fallback 으로 반환."""
        if not image_bytes:
            raise ValueError("empty image")

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        body = {
            "taskType": "IMAGE_VARIATION",
            "imageVariationParams": {
                "text": _ENHANCE_PROMPT,
                "negativeText": _NEGATIVE,
                "images": [b64],
                "similarityStrength": max(0.2, min(1.0, similarity_strength)),
            },
            "imageGenerationConfig": {
                "numberOfImages": 1,
                "quality": "premium",
                "cfgScale": 6.5,
            },
        }

        try:
            resp = self._client.invoke_model(
                modelId=self.model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body),
            )
            payload = json.loads(resp["body"].read())
            if payload.get("error"):
                raise RuntimeError(str(payload["error"]))
            images = payload.get("images") or []
            if not images:
                raise RuntimeError("Nova Canvas returned no images")
            out = base64.b64decode(images[0])
            print(
                f"[image-enhance] ok model={self.model_id} "
                f"region={self.region} bytes={len(out)}"
            )
            return EnhancedImage(
                body=out,
                image_format="png",
                model_id=self.model_id,
                used_fallback=False,
            )
        except (ClientError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            print(f"[image-enhance] fallback to original: {exc}")
            # JPEG magic
            fmt = "jpeg" if image_bytes[:2] == b"\xff\xd8" else "png"
            return EnhancedImage(
                body=image_bytes,
                image_format=fmt,
                model_id=self.model_id,
                used_fallback=True,
            )
