"""simulator.py — 로컬 엣지 시뮬레이터 (ingest API 방식).

흐름 (docs/architecture.md, lambda/inspection-event-ingest):
    input_images/ 순회 → 1단계 YOLO 추론
      → NORMAL           : 로컬 로그만
      → DAMAGE_SUSPECTED : POST /inspection-events (메타 JSON)
                             → ingest Lambda 가 DynamoDB PENDING PutItem + presigned URL 응답
                           → 그 URL 로 bbox 이미지 S3 직접 PUT

시뮬레이터는 AWS 자격증명이 필요 없다(권한은 ingest Lambda 가 가짐).
report 등 나머지 필드는 ingest Lambda 가 item 조립 시 채운다.

실행:
    cd edge-yolo
    python simulator.py
    # 엔드포인트 없이 로직만 보려면:  EDGE_DRY_RUN=true python simulator.py
"""

from __future__ import annotations

import glob
import json
import os
import random
import re
import sys
from datetime import datetime, timezone
from typing import Optional, Tuple

# 어디서 실행하든 같은 폴더 모듈을 찾도록
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from infer import Stage1Detector, EDGE_DAMAGE_SUSPECTED, Detection, EdgeResult
from ingest_client import post_event
from upload_to_s3 import render_bbox, put_image

# 컨테이너 번호(ISO 6346 흉내) 시뮬레이션용 소유자 코드
_OWNERS = ["MSCU", "MSKU", "TEMU", "TGHU", "CAIU", "HLCU", "OOLU"]
# 파일명에서 event_id / 촬영시각 추출: EVT-YYYYMMDD-HHMMSS-XXXX
_EVT_RE = re.compile(
    r"^(EVT-(\d{8})-(\d{6})-(\d{4}))(?:\.[^.]+)?$",
    re.IGNORECASE,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _gen_container_id() -> str:
    return random.choice(_OWNERS) + f"{random.randint(0, 9_999_999):07d}"


def parse_event_from_filename(name: str) -> Optional[Tuple[str, datetime]]:
    """input_images 파일명이 EVT-... 형이면 (event_id, captured_at) 반환."""
    stem = os.path.splitext(os.path.basename(name))[0]
    m = _EVT_RE.match(stem) or _EVT_RE.match(os.path.basename(name))
    if not m:
        return None
    event_id, ymd, hms, _seq = m.group(1), m.group(2), m.group(3), m.group(4)
    try:
        captured_at = datetime.strptime(ymd + hms, "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None
    return event_id, captured_at


def build_payload(
    event_id: str,
    captured_at: datetime,
    result,
    cfg,
    *,
    container_id: Optional[str] = None,
) -> dict:
    """ingest API 로 보낼 메타데이터(평평한 필드). item 조립은 Lambda 가 한다."""
    return {
        "event_id": event_id,
        "event_date": captured_at.strftime("%Y-%m-%d"),
        "captured_at": captured_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "container_id": container_id or _gen_container_id(),
        "gate_id": cfg.gate_id,
        "camera_id": cfg.camera_id,
        "edge_status": result.status,
        "edge_model": cfg.edge_model_name,
        "edge_confidence": result.confidence,
        "edge_detections": [
            {"damage_class": d.damage_class, "confidence": d.confidence, "bbox": d.bbox}
            for d in result.detections
        ],
        "image_content_type": "image/jpeg",
    }


def _append_log(path: str, entry: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _save_json(out_dir: str, event_id: str, obj: dict) -> None:
    with open(os.path.join(out_dir, f"{event_id}.json"), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def run() -> None:
    cfg = config
    os.makedirs(cfg.output_dir, exist_ok=True)

    if not os.path.exists(cfg.model_path):
        print(f"!! 1단계 모델 없음: {cfg.model_path}")
        print("   edge-yolo/weights/stage1_best.pt 를 두거나 EDGE_MODEL_PATH 를 지정하세요.")
        return

    detector = Stage1Detector(cfg.model_path, cfg.edge_conf, cfg.edge_imgsz, cfg.edge_iou)

    imgs = sorted(
        {
            p
            for ext in ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG")
            for p in glob.glob(os.path.join(cfg.input_dir, ext))
            # 백업 폴더·숨김 경로 제외
            if "_prev_run" not in os.path.normpath(p).split(os.sep)
        }
    )
    print(
        f"[SIM] 입력 {len(imgs)}장 | 모델 {os.path.basename(cfg.model_path)} "
        f"| dry_run={cfg.dry_run} | interactive={cfg.interactive}"
    )
    print(f"[SIM] ingest: {cfg.ingest_api_url}{cfg.ingest_path}")
    if cfg.interactive:
        print("[SIM] 각 이미지마다 Enter=처리, s=건너뛰기, q=종료")

    log_path = os.path.join(cfg.output_dir, "edge_log.jsonl")
    seq = 0
    for i, path in enumerate(imgs, 1):
        name = os.path.basename(path)

        # 게이트 통과 시뮬레이션: 키 입력으로 한 장씩
        if cfg.interactive:
            cmd = input(f"\n[{i}/{len(imgs)}] {name}  (Enter=처리 / s=건너뛰기 / q=종료) > ").strip().lower()
            if cmd == "q":
                print("[SIM] 사용자 종료")
                break
            if cmd == "s":
                print("  건너뜀")
                continue

        result = detector.infer(path)
        named = parse_event_from_filename(name)

        # 정상 → 로컬 로그만 (단, EVT- 파일명은 메타에 맞춰 전송)
        if result.status != EDGE_DAMAGE_SUSPECTED:
            if not named:
                print(f"  {name} → NORMAL (로컬 로그)")
                _append_log(log_path, {"image": name, "edge_status": result.status})
                continue
            # 파일명 기반 이벤트: 탐지 없어도 이미지 중앙 bbox 로 전송
            import cv2

            img0 = cv2.imread(path)
            h, w = (img0.shape[:2] if img0 is not None else (640, 640))
            pad_x, pad_y = int(w * 0.15), int(h * 0.15)
            result = EdgeResult(
                EDGE_DAMAGE_SUSPECTED,
                0.5,
                [
                    Detection(
                        damage_class="damage",
                        confidence=0.5,
                        bbox={
                            "x_min": pad_x,
                            "y_min": pad_y,
                            "x_max": w - pad_x,
                            "y_max": h - pad_y,
                        },
                    )
                ],
            )
            print(f"  {name} → NORMAL→강제전송 (파일명 event_id 사용)")

        # 손상 의심 → 이벤트 생성 (파일명 EVT-... 우선)
        seq += 1
        if named:
            event_id, captured_at = named
        else:
            captured_at = _now_utc()
            event_id = f"EVT-{captured_at.strftime('%Y%m%d-%H%M%S')}-{seq:04d}"
        payload = build_payload(event_id, captured_at, result, cfg)

        # bbox 렌더 후 S3 업로드만 (로컬 이미지/_prev_run/input 메타 생성 안 함)
        img_bytes = render_bbox(path, result.detections)
        _save_json(cfg.output_dir, event_id, payload)
        if cfg.dry_run:
            print(f"  {name} → DAMAGE_SUSPECTED [{event_id}] (dry-run: API 호출 skip)")
            _append_log(log_path, {"image": name, "edge_status": result.status, "event_id": event_id})
            continue

        # 1) 메타데이터 POST → presigned URL 응답
        status, data = post_event(cfg.ingest_api_url, payload, cfg.ingest_path)
        if status == 201:
            # 2) 이미지 S3 직접 PUT
            put_status = put_image(data["upload_url"], img_bytes, payload["image_content_type"])
            print(f"  {name} → [{data.get('event_id', event_id)}] POST 201 · S3 PUT {put_status} → {data.get('raw_image_key')}")
        elif status == 409:
            print(f"  {name} → [{event_id}] 409 이미 존재 — 업로드 skip")
        else:
            print(f"  {name} → 오류 {status}: {data}")

        _append_log(
            log_path,
            {"image": name, "edge_status": result.status, "event_id": event_id, "http": status},
        )

    print(f"[SIM] 완료 (이벤트 {seq}건) → 로그: {log_path}")


if __name__ == "__main__":
    run()
