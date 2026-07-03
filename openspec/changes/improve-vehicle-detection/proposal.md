## Why

YOLO vehicle detection in the ITS system currently misses small or distant vehicles inside the ROI polygon, causing under-counting across all 5 cameras — especially on Văn Quán, Nguyễn Văn Trỗi, and Đường Láng where the ROI covers perspective-distorted road sections. The root cause is a combination of a high confidence threshold (`conf=0.2`), aggressive frame skipping (`infer_every_n=3`), and a fixed low-resolution resize (`600×400`) that makes distant vehicles appear too small for the model to detect reliably.

## What Changes

- Lower per-camera confidence threshold from `conf=0.2` to `conf=0.15` to catch more true positives
- Reduce default frame skip from `infer_every_n=3` to `infer_every_n=2` for more stable tracking
- Increase inference frame resolution from `600×400` to `800×600` for distant vehicle detection
- Add per-camera override config so each road can tune `conf`, `iou`, and `infer_every_n` independently
- Add adaptive resolution scaling: when CPU load > 80%, downscale back to `600×400` automatically

## Capabilities

### New Capabilities
- `per-camera-detection-config`: Each camera (road) can have its own `conf`, `iou`, `infer_every_n`, and `frame_size` overrides in `config.py`, falling back to global defaults.
- `adaptive-frame-resolution`: Frame size is dynamically reduced under high CPU load to maintain responsiveness while preserving improved detection in normal conditions.

### Modified Capabilities
- (none — no existing spec-level behavior changes, only implementation tuning)

## Impact

- **`backend/app/core/config.py`** — Add `CAMERA_OVERRIDES` dict with per-road detection params
- **`backend/app/services/road_services/analyze_on_road_base.py`** — Use per-camera config in `__init__`, apply adaptive resolution in `process_on_single_video`
- **`backend/app/services/road_services/analyze_on_road_for_multi_processing.py`** — Pass per-camera params when spawning each subprocess
- No API changes, no database changes, no frontend changes
- CPU impact estimated at +15–20% in normal conditions (within constraint), drops back to baseline under load via adaptive scaling
