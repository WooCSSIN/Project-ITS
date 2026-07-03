## 1. Config — Per-camera detection parameters

- [x] 1.1 Add `DEFAULT_CONF = 0.15`, `DEFAULT_IOU = 0.3`, `DEFAULT_INFER_EVERY_N = 2`, `DEFAULT_FRAME_SIZE = (800, 600)` to `SettingMetricTransport` in `backend/app/core/config.py`
- [x] 1.2 Add `CAMERA_OVERRIDES: Dict[str, dict] = {}` to `SettingMetricTransport` with commented-out examples for each road
- [x] 1.3 Update `HOMOGRAPHY_MATRICES` source points to match new `DEFAULT_FRAME_SIZE = (800, 600)` — or verify that homography is computed at original pixel coords (not at resized frame coords) so no change needed

## 2. Analyzer — Use per-camera config

- [x] 2.1 In `AnalyzeOnRoadBase.__init__`, look up `settings_metric_transport.CAMERA_OVERRIDES.get(road_name, {})` and apply overrides for `conf`, `iou`, `infer_every_n`, and `frame_size` with fallback to the new defaults
- [x] 2.2 Store resolved `self._frame_size: tuple` on the instance (e.g., `(800, 600)`)
- [x] 2.3 Update `SpeedEstimator` init call to use resolved `conf` and `iou` values
- [x] 2.4 Update `self.infer_every_n_frames` and `self._base_infer_every_n` to use resolved `infer_every_n` value

## 3. Analyzer — Adaptive frame resolution

- [x] 3.1 Add `self._cpu_downscaled: bool = False` flag in `AnalyzeOnRoadBase.__init__`
- [x] 3.2 In `process_on_single_video` loop, before `cv2.resize`, compute effective frame size: use `(600, 400)` when `psutil.cpu_percent(interval=None) > 80`, else use `self._frame_size`
- [x] 3.3 Log a WARNING once per CPU-high transition using `self._cpu_downscaled` flag: `"CPU high ({cpu:.0f}%), downscaling frame to 600×400 for {self.name}"`
- [x] 3.4 Reset `self._cpu_downscaled = False` when CPU drops back below 70%

## 4. Multiprocessing — Pass per-camera params

- [x] 4.1 In `AnalyzeOnRoadForMultiprocessing._create_process_for_road`, read per-camera overrides from `CAMERA_OVERRIDES` and pass resolved `conf`, `iou`, `infer_every_n`, `frame_size` as args to `_run_analyze_process`
- [x] 4.2 Update `_run_analyze_process` static method signature to accept and forward these params to `AnalyzeOnRoad.__init__`
- [x] 4.3 Update `AnalyzeOnRoad.__init__` signature to accept optional `conf`, `iou`, `infer_every_n`, `frame_size` params and pass to `super().__init__`

## 5. Verification

- [x] 5.1 Run existing tests: `pytest backend/tests/ -x -q` — confirm no regressions
- [ ] 5.2 Start a single-camera test (`python analyze_on_road_base.py`) with `show=True` and verify bounding boxes appear on small vehicles that were previously missed
- [ ] 5.3 Monitor CPU usage over 60 seconds — confirm average increase is ≤ 20% vs baseline
- [ ] 5.4 Verify adaptive downscale triggers when CPU is artificially loaded and log appears exactly once per transition
