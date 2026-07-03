## ADDED Requirements

### Requirement: Adaptive frame resolution under CPU load
The system SHALL automatically reduce inference frame resolution to `600×400`
when host CPU usage exceeds 80% (measured by `psutil.cpu_percent`). When CPU
drops back below 70%, the system SHALL restore the configured resolution. This
check MUST occur once per frame before resize, using the cached non-blocking
`psutil` value already used by `_get_adaptive_skip_factor`.

#### Scenario: Resolution downscaled under high CPU
- **WHEN** `psutil.cpu_percent()` returns a value > 80
- **THEN** the frame is resized to `(600, 400)` regardless of configured `frame_size`

#### Scenario: Resolution restored after CPU normalises
- **WHEN** `psutil.cpu_percent()` returns a value <= 70 on the next frame
- **THEN** the frame is resized to the camera's configured `frame_size`

#### Scenario: Downscale logged once per transition
- **WHEN** CPU crosses the 80% threshold for the first time
- **THEN** a WARNING log is emitted: "CPU high ({cpu}%), downscaling frame to 600×400 for {road_name}"
- **THEN** subsequent frames at high CPU do NOT emit repeated warnings (only once per transition)

### Requirement: Adaptive skip factor unchanged by resolution change
The system SHALL continue applying `_get_adaptive_skip_factor` independently of
the resolution adaptation. Frame skip and frame resolution are orthogonal controls.

#### Scenario: Both adaptations can apply simultaneously
- **WHEN** CPU > 85%
- **THEN** frame skip factor is increased (existing behavior) AND resolution is downscaled to 600×400
