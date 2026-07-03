## ADDED Requirements

### Requirement: Per-camera detection parameter overrides
The system SHALL support per-camera overrides for `conf`, `iou`, `infer_every_n`,
and `frame_size` in `SettingMetricTransport.CAMERA_OVERRIDES`. When a camera has
an override, those values MUST take precedence over global defaults. Cameras with
no override SHALL use global defaults (`conf=0.15`, `iou=0.3`, `infer_every_n=2`).

#### Scenario: Camera with override uses its own conf
- **WHEN** camera "Ngã Tư Sở" has `CAMERA_OVERRIDES["Ngã Tư Sở"] = {"conf": 0.20}`
- **THEN** the analyzer for that camera initializes SpeedEstimator with `conf=0.20`

#### Scenario: Camera without override uses global default
- **WHEN** no entry for "Văn Quán" exists in `CAMERA_OVERRIDES`
- **THEN** the analyzer for that camera initializes SpeedEstimator with `conf=0.15`

#### Scenario: Partial override inherits remaining defaults
- **WHEN** `CAMERA_OVERRIDES["Đường Láng"] = {"infer_every_n": 1}` only
- **THEN** `conf=0.15` and `iou=0.3` are used (global defaults), and `infer_every_n=1`

### Requirement: Increased default inference frame resolution
The system SHALL resize frames to `800×600` before inference by default (up from
`600×400`). Cameras MAY override this with their own `frame_size` tuple in
`CAMERA_OVERRIDES`.

#### Scenario: Default resolution applied at inference
- **WHEN** no `frame_size` override is set for a camera
- **THEN** each video frame is resized to `(800, 600)` before passing to YOLO

#### Scenario: Per-camera resolution override
- **WHEN** `CAMERA_OVERRIDES["Ngã Tư Sở"] = {"frame_size": (640, 360)}`
- **THEN** frames for Ngã Tư Sở are resized to `(640, 360)` before inference
