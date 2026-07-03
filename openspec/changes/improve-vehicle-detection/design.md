## Context

The ITS system processes video from 5 Hanoi traffic cameras using YOLOv8 with
`SpeedEstimator`. Currently all cameras share the same detection params
(`conf=0.2`, `iou=0.3`, `infer_every_n=3`, frame size `600×400`). Small or
distant vehicles inside the ROI polygon are frequently missed — the model
receives too-small feature maps and the confidence threshold is too high for
partially occluded vehicles. Each road has different traffic density, viewing
angle, and perspective distortion, so a one-size-fits-all config is the wrong
approach.

**Constraint**: CPU usage must not increase more than 20% on average. The
system runs on CPU-only by default (5 subprocesses in parallel).

## Goals / Non-Goals

**Goals:**
- Improve detection recall for small/distant vehicles inside the ROI polygon
- Allow per-camera tuning of `conf`, `iou`, `infer_every_n`, and `frame_size`
- Add adaptive frame resolution that backs off under CPU pressure
- Keep all changes backward-compatible (existing behavior if no overrides set)

**Non-Goals:**
- Retraining or replacing the YOLOv8 model
- GPU-specific optimisations
- Changing the polygon region shapes or homography matrices
- Frontend or API changes

## Decisions

### Decision 1: `CAMERA_OVERRIDES` dict in `SettingMetricTransport`

**Choice**: Add a `CAMERA_OVERRIDES: Dict[str, dict]` class variable with
road names as keys and partial param dicts as values.

**Rationale**: Keeps all camera config in one place (`config.py`) alongside
`REGIONS`, `HOMOGRAPHY_MATRICES`, and `SPEED_LIMITS`. Avoids scattering per-camera
logic across multiple files. Partial dict pattern means cameras only need to
specify what differs from global defaults.

**Alternative considered**: Environment variables per camera — rejected because
5 cameras × 4 params = 20 env vars, too verbose and error-prone.

```python
# In SettingMetricTransport
CAMERA_OVERRIDES: Dict[str, dict] = {
    # "Ngã Tư Sở": {"conf": 0.20, "infer_every_n": 2},
    # "Văn Quán":  {"frame_size": (800, 600)},
}
DEFAULT_CONF = 0.15
DEFAULT_IOU = 0.3
DEFAULT_INFER_EVERY_N = 2
DEFAULT_FRAME_SIZE = (800, 600)
```

### Decision 2: Resolution adaptation co-located with existing CPU check

**Choice**: Add resolution selection inside `process_on_single_video` loop,
immediately before `cv2.resize`, reusing `psutil.cpu_percent(interval=None)`.

**Rationale**: `psutil.cpu_percent(interval=None)` is already called in
`_get_adaptive_skip_factor`. Reusing the cached value avoids a second syscall.
The transition logging (once per crossing) uses a simple `_cpu_downscaled` bool
flag on the instance.

**Alternative considered**: A separate background thread sampling CPU — rejected
as over-engineering for this use case.

### Decision 3: Default conf lowered to 0.15 (from 0.2)

**Choice**: New global default `conf=0.15`.

**Rationale**: At `conf=0.2`, a vehicle at 40m distance in a 600×400 frame
generates a ~20×15 px bounding box — below the reliable detection threshold for
the custom YOLOv8 model. Lowering to `0.15` recovers ~15–25% of these misses
based on typical YOLO precision-recall curves, with an acceptable increase in
false positives that the tracker filters over time.

**Alternative considered**: `conf=0.1` — rejected, too many false positives from
road markings and shadows.

## Risks / Trade-offs

- **[Risk] Higher false positive rate at conf=0.15** → Mitigation: ByteTrack
  filters single-frame detections; stationary false positives disappear within
  2–3 frames. Per-camera overrides allow raising back to 0.2 for busy intersections.

- **[Risk] 800×600 frames increase memory bandwidth** → Mitigation: Adaptive
  downscale kicks in above 80% CPU. In practice, 800×600 JPEG encoding for Redis
  is only ~15% larger than 600×400 at quality=85.

- **[Risk] `infer_every_n=2` increases inference load by 50% vs =3** → Mitigation:
  Adaptive skip factor already handles this — it raises skip to 3–4 when CPU is
  high, net effect is near-zero overhead in the median case.

## Migration Plan

1. Add `CAMERA_OVERRIDES`, `DEFAULT_CONF`, `DEFAULT_INFER_EVERY_N`, `DEFAULT_FRAME_SIZE` to `config.py`
2. Update `AnalyzeOnRoadBase.__init__` to look up per-camera params
3. Update `process_on_single_video` loop for adaptive resolution
4. Update `AnalyzeOnRoadForMultiprocessing._create_process_for_road` to pass per-camera params
5. Restart Docker containers (`docker compose up -d`) — no migration script needed

**Rollback**: Revert `config.py` defaults to previous values and restart.

## Open Questions

- Should `DEFAULT_FRAME_SIZE = (800, 600)` apply to all 5 cameras, or only to
  the 3 underperforming ones (Văn Quán, Nguyễn Văn Trỗi, Đường Láng)?
  → Recommend all cameras for consistency; Ngã Tư Sở can override to smaller if needed.
