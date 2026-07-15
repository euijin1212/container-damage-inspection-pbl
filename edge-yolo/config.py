"""config.py — 엣지 시뮬레이터 설정 로더 (.env / 환경변수).

새 구조(ingest API): 시뮬레이터는 API Gateway 로 메타데이터를 POST 하고,
응답의 presigned URL 로 이미지를 S3 에 직접 PUT 한다. AWS 자격증명 불필요.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

try:  # python-dotenv 는 선택 의존성
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))


@dataclass(frozen=True)
class EdgeConfig:
    # ===== Ingest API (API Gateway → inspection-event-ingest Lambda) =====
    ingest_api_url: str = os.getenv(
        "INGEST_API_URL", "https://7tevpqwqmj.execute-api.ap-northeast-2.amazonaws.com"
    )
    ingest_path: str = os.getenv("INGEST_PATH", "/inspection-events")

    # ===== 게이트/카메라 (시뮬레이션 소스) =====
    gate_id: str = os.getenv("GATE_ID", "GATE-01")
    camera_id: str = os.getenv("CAMERA_ID", "CAM-01")

    # ===== 1단계(손상 여부) 모델 =====
    model_path: str = os.getenv(
        "EDGE_MODEL_PATH", os.path.join(_HERE, "weights", "stage1_best.pt")
    )
    edge_model_name: str = os.getenv("EDGE_MODEL_NAME", "yolov8s-stage1")
    edge_conf: float = float(os.getenv("EDGE_CONF", "0.15"))  # 낮을수록 민감(놓침↓)
    edge_imgsz: int = int(os.getenv("EDGE_IMGSZ", "896"))

    # ===== 입출력 =====
    input_dir: str = os.getenv("EDGE_INPUT_DIR", os.path.join(_HERE, "input_images"))
    output_dir: str = os.getenv("EDGE_OUTPUT_DIR", os.path.join(_HERE, "output_results"))

    # ===== 실행 모드 =====
    # true 면 API 호출을 건너뛰고 생성 payload/이미지만 로컬 저장(엔드포인트 없이 로직 검증)
    dry_run: bool = os.getenv("EDGE_DRY_RUN", "false").lower() in ("1", "true", "yes")
    # true 면 이미지마다 키 입력을 받아 한 장씩 처리(게이트 통과 시뮬레이션)
    interactive: bool = os.getenv("EDGE_INTERACTIVE", "true").lower() in ("1", "true", "yes")


config = EdgeConfig()
