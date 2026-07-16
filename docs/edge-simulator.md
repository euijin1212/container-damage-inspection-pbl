# Edge YOLO Simulator

`edge-yolo/`는 로컬 게이트/카메라 환경을 흉내 내는 엣지 시뮬레이터입니다.
이미지를 로컬 YOLO 모델로 먼저 검사하고, 손상 의심 건만 클라우드 ingest API로 보냅니다.

## Flow

```text
edge-yolo/input_images/*
  -> YOLO stage 1 inference
  -> NORMAL: local log only
  -> DAMAGE_SUSPECTED:
       POST /inspection-events
       <- { upload_url, raw_image_key }
       PUT bbox-rendered JPEG to S3 presigned URL
       S3 ObjectCreated -> container-damage-analyzer
```

The simulator does not need AWS credentials. It only calls API Gateway and uses the
presigned upload URL returned by `inspection-event-ingest`.

## Files

| File | Purpose |
|---|---|
| `config.py` | Loads `.env` and environment variables |
| `infer.py` | Wraps Ultralytics YOLO and returns `NORMAL` or `DAMAGE_SUSPECTED` |
| `ingest_client.py` | Calls `POST /inspection-events` |
| `upload_to_s3.py` | Draws bounding boxes and uploads to the presigned S3 URL |
| `simulator.py` | Main runner |
| `requirements.txt` | Local simulator dependencies |

## Setup

```powershell
python -m venv .venv-edge
.\.venv-edge\Scripts\python.exe -m pip install -r edge-yolo\requirements.txt
```

Put the real stage-1 damage model here:

```text
edge-yolo/weights/stage1_best.pt
```

Or point to it explicitly:

```powershell
$env:EDGE_MODEL_PATH="C:\path\to\stage1_best.pt"
```

Put input images under:

```text
edge-yolo/input_images/
```

## Run

Interactive mode is on by default. For batch execution:

```powershell
$env:EDGE_INTERACTIVE="false"
.\.venv-edge\Scripts\python.exe edge-yolo\simulator.py
```

For local-only verification without API/S3 writes:

```powershell
$env:EDGE_DRY_RUN="true"
$env:EDGE_INTERACTIVE="false"
.\.venv-edge\Scripts\python.exe edge-yolo\simulator.py
```

Outputs are written to:

```text
edge-yolo/output_results/
```

## Configuration

| Variable | Default |
|---|---|
| `INGEST_API_URL` | `https://7tevpqwqmj.execute-api.ap-northeast-2.amazonaws.com` |
| `INGEST_PATH` | `/inspection-events` |
| `GATE_ID` | `GATE-01` |
| `CAMERA_ID` | `CAM-01` |
| `EDGE_MODEL_PATH` | `edge-yolo/weights/stage1_best.pt` |
| `EDGE_MODEL_NAME` | `yolov8s-stage1` |
| `EDGE_CONF` | `0.15` |
| `EDGE_IMGSZ` | `896` |
| `EDGE_INPUT_DIR` | `edge-yolo/input_images` |
| `EDGE_OUTPUT_DIR` | `edge-yolo/output_results` |
| `EDGE_DRY_RUN` | `false` |
| `EDGE_INTERACTIVE` | `true` |

## Verified Result

Verified on 2026-07-16 with a local venv and API Gateway `7tevpqwqmj`.

```text
container-dent.png -> [EVT-20260716-054239-0001] POST 201 · S3 PUT 200 -> raw-images/EVT-20260716-054239-0001.jpg
```

Dashboard API lookup for the same event returned:

```text
review_status=MANUAL_NEEDED
risk_level=MEDIUM
risk_score=51.7
report_status=NOT_CREATED
```

The verification used `yolov8n.pt` only to test the end-to-end pipeline.
For the final demo, use the actual damage detector model at `stage1_best.pt`.
