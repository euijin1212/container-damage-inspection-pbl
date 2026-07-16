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
import sys
from datetime import datetime, timezone

# 어디서 실행하든 같은 폴더 모듈을 찾도록
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from infer import Stage1Detector, EDGE_DAMAGE_SUSPECTED
from ingest_client import post_event
from upload_to_s3 import render_bbox, put_image

# 컨테이너 번호(ISO 6346 흉내) 시뮬레이션용 소유자 코드
_OWNERS = ["MSCU", "MSKU", "TEMU", "TGHU", "CAIU", "HLCU", "OOLU"]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _gen_container_id() -> str:
    return random.choice(_OWNERS) + f"{random.randint(0, 9_999_999):07d}"


def build_payload(event_id: str, captured_at: datetime, result, cfg) -> dict:
    """ingest API 로 보낼 메타데이터(평평한 필드). item 조립은 Lambda 가 한다."""
    return {
        "event_id": event_id,
        "event_date": captured_at.strftime("%Y-%m-%d"),
        "captured_at": captured_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "container_id": _gen_container_id(),
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

        # 정상 → 로컬 로그만 (클라우드 전송 X)
        if result.status != EDGE_DAMAGE_SUSPECTED:
            print(f"  {name} → NORMAL (로컬 로그)")
            _append_log(log_path, {"image": name, "edge_status": result.status})
            continue

        # 손상 의심 → 이벤트 생성
        seq += 1
        captured_at = _now_utc()
        event_id = f"EVT-{captured_at.strftime('%Y%m%d-%H%M%S')}-{seq:04d}"
        payload = build_payload(event_id, captured_at, result, cfg)

        # bbox 이미지 렌더 + 로컬 사본(payload/이미지)
        img_bytes = render_bbox(path, result.detections)
        _save_json(cfg.output_dir, event_id, payload)
        with open(os.path.join(cfg.output_dir, f"{event_id}.jpg"), "wb") as f:
            f.write(img_bytes)

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
