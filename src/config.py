"""config.py — 전역 설정 로더 (모든 모듈의 진입점 설정 소스).

역할
----
프로젝트 전체가 공유하는 설정값을 한곳에서 관리한다. `.env` 파일이 있으면
자동 로드하고, 없으면 시스템/Lambda 환경 변수를 사용한다.

관리 항목
--------
- AWS 리소스: 리전(`aws_region`), S3 버킷(`s3_bucket`), SageMaker 인스턴스 타입
- Bedrock: 리전(`bedrock_region`), 모델 ID(`bedrock_model_id` = Sonnet 4.5)
- Risk Score: 손상 유형별 가중치(구멍 ≥ 찌그러짐 > 녹슴), 등급 임계값
- 표준 상수: 손상 유형(DAMAGE_HOLE/DENT/RUST), 손상 정도 계수(SEVERITY_FACTORS)

사용법
------
    from src.config import settings
    settings.bedrock_model_id, settings.type_weights ...

주의: 환경 변수는 import 시점에 읽히므로, 값을 바꾼 뒤에는 모듈을 reload 해야
반영된다(노트북에서 importlib.reload 사용).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict

try:  # python-dotenv 는 선택 의존성
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv 미설치 환경 대비
    pass


# 표준 손상 유형 (모델/스코어 로직 공통 계약)
DAMAGE_HOLE = "hole"  # 구멍
DAMAGE_DENT = "dent"  # 찌그러짐
DAMAGE_RUST = "rust"  # 녹슴

# 손상 정도 → 계수 (0~1)
SEVERITY_FACTORS: Dict[str, float] = {
    "low": 0.3,      # 경미
    "medium": 0.6,   # 중간
    "high": 1.0,     # 심각
}


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip()


@dataclass(frozen=True)
class Settings:
    # AWS 공통
    aws_region: str = _env("AWS_REGION", "ap-northeast-2")

    # S3 (이미지 조회 버킷 · 서울 리전)
    s3_bucket: str = _env("S3_BUCKET", "container-damage")
    s3_prefix: str = os.getenv("S3_PREFIX", "") or ""

    # SageMaker (노트북/재분석 인스턴스 타입)
    sagemaker_instance_type: str = _env("SAGEMAKER_INSTANCE_TYPE", "ml.t3.medium")

    # Bedrock (서울 리전 Sonnet 4.5 는 apac/global 추론 프로파일 필요)
    bedrock_region: str = _env(
        "BEDROCK_REGION", _env("AWS_REGION", "ap-northeast-2")
    )
    bedrock_model_id: str = _env(
        "BEDROCK_MODEL_ID", "apac.anthropic.claude-sonnet-4-5-20250929-v1:0"
    )

    # 재검수 화질 개선 (Nova Canvas — 서울 미지원, 기본 us-east-1)
    bedrock_image_model_id: str = _env(
        "BEDROCK_IMAGE_MODEL_ID", "amazon.nova-canvas-v1:0"
    )
    bedrock_image_region: str = _env("BEDROCK_IMAGE_REGION", "us-east-1")

    # Bedrock Knowledge Base (보고서 RAG). 비우면 RAG 없이 동작
    knowledge_base_id: str = os.getenv("KNOWLEDGE_BASE_ID", "")
    kb_max_results: int = int(_get_float("KB_MAX_RESULTS", 4))

    # Risk Score - 손상 유형별 가중치 (구멍 >= 찌그러짐 > 녹슴)
    type_weights: Dict[str, float] = field(
        default_factory=lambda: {
            DAMAGE_HOLE: _get_float("RISK_WEIGHT_HOLE", 1.0),
            DAMAGE_DENT: _get_float("RISK_WEIGHT_DENT", 0.85),
            DAMAGE_RUST: _get_float("RISK_WEIGHT_RUST", 0.35),
        }
    )

    # Risk Level 판정 임계값 (0~100)
    threshold_high: float = _get_float("RISK_THRESHOLD_HIGH", 66.0)
    threshold_medium: float = _get_float("RISK_THRESHOLD_MEDIUM", 33.0)


settings = Settings()
