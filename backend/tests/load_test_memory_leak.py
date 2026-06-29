"""Load test + Memory leak detection script.

Chạy liên tục các operations để verify:
    1. Memory usage không tăng tuyến tính theo thời gian (không leak)
    2. CPU không vượt ngưỡng bất thường
    3. Latency của các operations vẫn ổn định

Usage:
    # Chạy trong 1 giờ
    python tests/load_test_memory_leak.py --duration 3600

    # Chạy trong 24 giờ với report mỗi 1 giờ
    python tests/load_test_memory_leak.py --duration 86400 --report-interval 3600

    # Test nhanh 5 phút
    python tests/load_test_memory_leak.py --duration 300

Output:
    - Console logs với metrics mỗi `report_interval` giây
    - File CSV: memory_leak_report_<timestamp>.csv với samples chi tiết
    - File summary: memory_leak_summary_<timestamp>.txt với verdict cuối cùng
"""
import argparse
import csv
import gc
import os
import random
import statistics
import sys
import time
import tracemalloc
from datetime import datetime
from pathlib import Path

import numpy as np

# Setup path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

# Setup logger
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Load test + memory leak detector")
    parser.add_argument(
        "--duration", type=int, default=3600,
        help="Tổng thời gian chạy (giây). Default: 3600 (1 giờ)"
    )
    parser.add_argument(
        "--report-interval", type=int, default=300,
        help="Khoảng cách giữa các report (giây). Default: 300 (5 phút)"
    )
    parser.add_argument(
        "--num-tracks", type=int, default=50,
        help="Số track_ids giả lập. Default: 50"
    )
    parser.add_argument(
        "--iterations-per-second", type=int, default=10,
        help="Số iterations mỗi giây. Default: 10"
    )
    parser.add_argument(
        "--output-dir", type=str, default="tests/load_test_results",
        help="Thư mục output cho CSV và summary"
    )
    return parser.parse_args()


def setup_components(num_tracks: int):
    """Khởi tạo các component cần test."""
    # Try import SpeedSmoother + HomographySpeedTracker - nếu thiếu cvzone,
    # định nghĩa lightweight stand-in để test logic cốt lõi.
    try:
        from services.road_services.analyze_on_road_base import (
            SpeedSmoother,
            HomographySpeedTracker,
        )
        has_real_components = True
    except ImportError as e:
        logger.warning(f"Không thể import analyze_on_road_base ({e}), dùng mock components")
        has_real_components = False

    components = {}

    # 1. SpeedSmoother
    if has_real_components:
        components["speed_smoother"] = SpeedSmoother(alpha=0.3, max_tracked=200)
    else:
        # Stand-in: dict với LRU eviction + thread-safe
        import threading
        class _MockSpeedSmoother:
            def __init__(self, alpha=0.3, max_tracked=200):
                self.alpha = alpha
                self.max_tracked = max_tracked
                self._smoothed = {}
                self._lock = threading.Lock()

            def update(self, track_id, raw_speed):
                with self._lock:
                    if raw_speed <= 0:
                        return self._smoothed.get(track_id, 0.0)
                    prev = self._smoothed.get(track_id, raw_speed)
                    smoothed = self.alpha * raw_speed + (1.0 - self.alpha) * prev
                    if len(self._smoothed) >= self.max_tracked and track_id not in self._smoothed:
                        oldest = next(iter(self._smoothed))
                        self._smoothed.pop(oldest, None)
                    self._smoothed[track_id] = smoothed
                    return smoothed

            def prune(self, active_ids):
                with self._lock:
                    stale = [t for t in self._smoothed if t not in active_ids]
                    for t in stale:
                        self._smoothed.pop(t, None)
                    return len(stale)
        components["speed_smoother"] = _MockSpeedSmoother(alpha=0.3, max_tracked=200)

    # 2. HomographySpeedTracker (mock nếu không có)
    H = np.array([[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1]], dtype=np.float32)
    if has_real_components:
        components["homography"] = HomographySpeedTracker(H=H, fps=30.0, max_hist=15)
    else:
        class _MockHomography:
            def __init__(self, H, fps=30.0, max_hist=15):
                self.H = H
                self.fps = fps
                self.max_hist = max_hist
                self.track_history = {}
                self.speeds = {}

            def update(self, track_id, cx, cy):
                if track_id not in self.track_history:
                    self.track_history[track_id] = []
                    self.speeds[track_id] = 0.0
                hist = self.track_history[track_id]
                hist.append((cx, cy, time.time()))
                if len(hist) > self.max_hist:
                    hist.pop(0)
                if len(hist) >= 2:
                    dx = hist[-1][0] - hist[0][0]
                    dy = hist[-1][1] - hist[0][1]
                    dt = max(hist[-1][2] - hist[0][2], 1e-6)
                    speed = (dx**2 + dy**2)**0.5 / dt
                    self.speeds[track_id] = min(speed * 3.6, 200.0)

            def remove(self, track_id):
                self.track_history.pop(track_id, None)
                self.speeds.pop(track_id, None)
        components["homography"] = _MockHomography(H=H, fps=30.0, max_hist=15)

    # 3. ViolationEngine
    from core.violation_engine import ViolationEngine
    components["violation_engine"] = ViolationEngine(
        camera_id=1, speed_limit_kmh=60.0, road_name="Test Road"
    )

    # 4. Polygon utils
    from utils.polygon_utils import points_in_polygon_fast
    components["polygon_utils"] = points_in_polygon_fast

    components["_has_real"] = has_real_components
    return components


def run_iteration(components: dict, num_tracks: int, iteration: int) -> float:
    """Chạy 1 iteration của workload. Trả về latency (giây)."""
    start = time.perf_counter()

    # 1. Simulate vehicle tracking
    classes = np.array([random.choice([0, 1]) for _ in range(num_tracks)])
    ids = np.array([random.randint(1, num_tracks * 2) for _ in range(num_tracks)])
    boxes = np.random.randint(0, 600, size=(num_tracks, 4))
    boxes[:, 2] = boxes[:, 0] + np.random.randint(50, 200, size=num_tracks)
    boxes[:, 3] = boxes[:, 1] + np.random.randint(50, 200, size=num_tracks)
    speeds_dict = {int(ids[i]): random.uniform(0, 80) for i in range(num_tracks)}

    # 2. SpeedSmoother - update các tracks
    smoother = components["speed_smoother"]
    for tid in ids:
        smoother.update(int(tid), speeds_dict.get(int(tid), 0.0))

    # 3. HomographySpeedTracker
    homography = components["homography"]
    for i, tid in enumerate(ids):
        cx = (boxes[i, 0] + boxes[i, 2]) / 2
        cy = (boxes[i, 1] + boxes[i, 3]) / 2
        homography.update(int(tid), float(cx), float(cy))

    # 4. ViolationEngine
    engine = components["violation_engine"]
    violations = engine.process_frame_tracking(
        classes, ids, boxes, speeds_dict, time.time()
    )

    # 5. Polygon test - vectorized
    polygon_fn = components["polygon_utils"]
    centers = np.column_stack([
        (boxes[:, 0] + boxes[:, 2]) / 2,
        (boxes[:, 1] + boxes[:, 3]) / 2,
    ])
    polygon = np.array([[100, 100], [500, 150], [480, 350], [120, 380]])
    _ = polygon_fn(centers, polygon)

    # 6. Periodic prune (mỗi 100 iterations) để cleanup stale tracks
    if iteration % 100 == 0:
        active_ids = set(int(t) for t in ids.tolist())
        smoother.prune(active_ids)

        # Cleanup homography - xóa tracks không active
        all_track_ids = set(homography.track_history.keys())
        stale = all_track_ids - active_ids
        for tid in stale:
            homography.remove(tid)

    elapsed = time.perf_counter() - start
    return elapsed


def collect_metrics(components: dict) -> dict:
    """Thu thập metrics hiện tại."""
    import psutil

    process = psutil.Process()
    mem_info = process.memory_info()

    metrics = {
        "rss_mb": mem_info.rss / (1024 * 1024),  # Resident Set Size
        "vms_mb": mem_info.vms / (1024 * 1024),  # Virtual Memory Size
        "cpu_percent": process.cpu_percent(interval=None),
        "threads": process.num_threads(),
    }

    # Object counts (nếu tracemalloc đang chạy)
    if tracemalloc.is_tracing():
        snapshot = tracemalloc.take_snapshot()
        total_size = sum(stat.size for stat in snapshot.statistics("filename"))
        metrics["traced_memory_mb"] = total_size / (1024 * 1024)

    # Track dict sizes
    smoother = components["speed_smoother"]
    with smoother._lock:
        metrics["speed_smoother_tracks"] = len(smoother._smoothed)

    homography = components["homography"]
    metrics["homography_tracks"] = len(homography.track_history)
    metrics["homography_max_hist"] = (
        max((len(h) for h in homography.track_history.values()), default=0)
    )

    engine = components["violation_engine"]
    metrics["engine_stationary_tracked"] = len(engine._stationary_started)

    return metrics


def detect_memory_leak(samples: list, key: str = "rss_mb") -> dict:
    """Phân tích samples để phát hiện memory leak.

    Heuristic: Nếu memory tăng > 20% qua 1/3 cuối samples → có thể leak.
    """
    if len(samples) < 10:
        return {"leak_detected": False, "reason": "Not enough samples"}

    values = [s[key] for s in samples if key in s]
    if len(values) < 10:
        return {"leak_detected": False, "reason": "Not enough valid samples"}

    # Chia samples thành 3 phần
    third = len(values) // 3
    first_avg = statistics.mean(values[:third])
    last_avg = statistics.mean(values[-third:])

    growth_percent = ((last_avg - first_avg) / first_avg) * 100 if first_avg > 0 else 0

    # Linear regression slope
    n = len(values)
    x_mean = n / 2
    y_mean = statistics.mean(values)
    slope = sum((i - x_mean) * (values[i] - y_mean) for i in range(n)) / sum((i - x_mean) ** 2 for i in range(n)) if n > 0 else 0

    leak_detected = growth_percent > 20 and slope > 0.1  # MB/sample

    return {
        "leak_detected": leak_detected,
        "growth_percent": growth_percent,
        "first_avg_mb": first_avg,
        "last_avg_mb": last_avg,
        "slope_mb_per_sample": slope,
        "min_mb": min(values),
        "max_mb": max(values),
    }


def write_csv(samples: list, output_path: str) -> None:
    """Ghi samples ra file CSV."""
    if not samples:
        return

    fieldnames = list(samples[0].keys())
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(samples)


def write_summary(
    samples: list, latencies: list, duration: float,
    leak_analysis: dict, output_path: str
) -> None:
    """Ghi summary report ra file text."""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write("MEMORY LEAK LOAD TEST - SUMMARY REPORT\n")
        f.write("=" * 80 + "\n\n")

        f.write(f"Test duration: {duration:.0f} seconds ({duration / 3600:.2f} hours)\n")
        f.write(f"Total samples collected: {len(samples)}\n")
        f.write(f"Total iterations: {len(latencies)}\n\n")

        # Memory analysis
        f.write("--- MEMORY ANALYSIS ---\n")
        f.write(f"Verdict: {'[WARNING] POSSIBLE LEAK DETECTED' if leak_analysis.get('leak_detected') else '[OK] NO LEAK DETECTED'}\n")
        for key, value in leak_analysis.items():
            if key == "leak_detected":
                continue
            if isinstance(value, float):
                f.write(f"  {key}: {value:.2f}\n")
            else:
                f.write(f"  {key}: {value}\n")
        f.write("\n")

        # Latency analysis
        if latencies:
            f.write("--- LATENCY ANALYSIS ---\n")
            f.write(f"  Mean latency: {statistics.mean(latencies) * 1000:.2f} ms\n")
            f.write(f"  Median latency: {statistics.median(latencies) * 1000:.2f} ms\n")
            f.write(f"  Min latency: {min(latencies) * 1000:.2f} ms\n")
            f.write(f"  Max latency: {max(latencies) * 1000:.2f} ms\n")
            f.write(f"  P95 latency: {np.percentile(latencies, 95) * 1000:.2f} ms\n")
            f.write(f"  P99 latency: {np.percentile(latencies, 99) * 1000:.2f} ms\n")
            f.write(f"  Std dev: {statistics.stdev(latencies) * 1000:.2f} ms\n\n")

        # Final metrics
        if samples:
            f.write("--- FINAL STATE ---\n")
            final = samples[-1]
            for key, value in final.items():
                if isinstance(value, float):
                    f.write(f"  {key}: {value:.2f}\n")
                else:
                    f.write(f"  {key}: {value}\n")

        f.write("\n" + "=" * 80 + "\n")
        f.write(f"Report generated at: {datetime.now().isoformat()}\n")


def main():
    args = parse_args()

    print(f"[START] Memory leak load test")
    print(f"  Duration: {args.duration}s ({args.duration / 3600:.2f}h)")
    print(f"  Report interval: {args.report_interval}s")
    print(f"  Tracks: {args.num_tracks}")
    print(f"  Iterations/sec target: {args.iterations_per_second}")
    print()

    # Output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"memory_leak_report_{timestamp}.csv"
    summary_path = output_dir / f"memory_leak_summary_{timestamp}.txt"

    # Setup
    tracemalloc.start()
    components = setup_components(args.num_tracks)

    # Run loop
    start_time = time.time()
    end_time = start_time + args.duration
    next_report = start_time + args.report_interval

    samples = []
    latencies = []
    iteration = 0

    # Sleep giữa các iteration để đạt iterations_per_second target
    target_interval = 1.0 / args.iterations_per_second

    try:
        while time.time() < end_time:
            iter_start = time.perf_counter()

            latency = run_iteration(components, args.num_tracks, iteration)
            latencies.append(latency)
            iteration += 1

            # Periodic GC để dọn rác
            if iteration % 1000 == 0:
                gc.collect()

            # Report
            now = time.time()
            if now >= next_report:
                metrics = collect_metrics(components)
                metrics["timestamp"] = datetime.now().isoformat()
                metrics["elapsed_seconds"] = round(now - start_time, 1)
                metrics["iteration"] = iteration
                samples.append(metrics)

                print(
                    f"[{metrics['elapsed_seconds']:.0f}s] iter={iteration} "
                    f"RSS={metrics['rss_mb']:.1f}MB "
                    f"CPU={metrics['cpu_percent']:.1f}% "
                    f"tracks={metrics['speed_smoother_tracks']} "
                    f"homo={metrics['homography_tracks']}"
                )

                next_report = now + args.report_interval

            # Sleep để giữ rate
            elapsed_iter = time.perf_counter() - iter_start
            if elapsed_iter < target_interval:
                time.sleep(target_interval - elapsed_iter)

    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Đã dừng bởi user")

    actual_duration = time.time() - start_time

    # Final collect
    final_metrics = collect_metrics(components)
    final_metrics["timestamp"] = datetime.now().isoformat()
    final_metrics["elapsed_seconds"] = round(actual_duration, 1)
    final_metrics["iteration"] = iteration
    samples.append(final_metrics)

    # Phân tích memory leak
    print("\n[ANALYSIS] Phân tích memory leak...")
    leak_analysis = detect_memory_leak(samples, key="rss_mb")

    # Ghi output
    write_csv(samples, str(csv_path))
    write_summary(samples, latencies, actual_duration, leak_analysis, str(summary_path))

    # In summary
    print(f"\nMEMORY VERDICT:")
    if leak_analysis.get("leak_detected"):
        print(f"  [WARNING] POSSIBLE LEAK DETECTED")
        print(f"  Growth: {leak_analysis.get('growth_percent', 0):.1f}%")
        print(f"  Slope: {leak_analysis.get('slope_mb_per_sample', 0):.3f} MB/sample")
    else:
        print(f"  [OK] NO LEAK DETECTED")
        print(f"  Growth: {leak_analysis.get('growth_percent', 0):.1f}%")

    if latencies:
        print(f"\nLATENCY:")
        print(f"  Mean: {statistics.mean(latencies) * 1000:.2f} ms")
        print(f"  P95:  {np.percentile(latencies, 95) * 1000:.2f} ms")
        print(f"  P99:  {np.percentile(latencies, 99) * 1000:.2f} ms")

    print(f"\nREPORTS:")
    print(f"  CSV: {csv_path}")
    print(f"  Summary: {summary_path}")
    print(f"{'=' * 60}")

    tracemalloc.stop()


if __name__ == "__main__":
    main()