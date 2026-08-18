from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import cv2


def analyze_motion(
    path: str | Path,
    motion_threshold: float = 8.0,
    sample_fps: float = 2.0,
    use_cpu: bool = True,
    benchmark: bool = False,
) -> dict[str, Any]:
    input_path = Path(path)
    cap = cv2.VideoCapture(str(input_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video for motion analysis: {input_path}")

    source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    processing_fps = source_fps if source_fps <= 0 else min(max(float(sample_fps or source_fps), 2.0), source_fps)
    sample_interval = 1 if source_fps <= 0 or processing_fps >= source_fps else max(1, round(source_fps / processing_fps))

    prev_gray = None
    frame_index = 0
    sample_count = 0
    total_motion = 0.0
    samples: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    active_start = None
    active_end = None
    active_max = 0.0
    start_time = time.perf_counter()

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame is None:
            continue

        if frame_index % sample_interval != 0:
            frame_index += 1
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        score = 0.0 if prev_gray is None else float(cv2.absdiff(prev_gray, gray).mean())
        timestamp = frame_index / source_fps if source_fps else 0.0

        samples.append({"time": round(timestamp, 3), "score": round(score, 6)})
        total_motion += score
        sample_count += 1

        if score > motion_threshold:
            if active_start is None:
                active_start = timestamp
            active_end = timestamp
            active_max = max(active_max, score)
        elif active_start is not None:
            assert active_end is not None
            segments.append(
                {
                    "start": round(active_start, 3),
                    "end": round(active_end, 3),
                    "max_score": round(active_max, 6),
                }
            )
            active_start = None
            active_end = None
            active_max = 0.0

        prev_gray = gray
        frame_index += 1

    if active_start is not None:
        assert active_end is not None
        segments.append(
            {
                "start": round(active_start, 3),
                "end": round(active_end, 3),
                "max_score": round(active_max, 6),
            }
        )

    cap.release()
    elapsed = time.perf_counter() - start_time
    average_motion = total_motion / sample_count if sample_count else 0.0
    peak_motion = max((sample["score"] for sample in samples), default=0.0)

    result = {
        "average_motion": round(float(average_motion), 6),
        "peak_motion": round(float(peak_motion), 6),
        "segments": segments,
        "samples": samples,
        "source_fps": round(source_fps, 3),
        "sampled_fps": round(processing_fps, 3),
        "frame_count": int(total_frames),
        "sampled_frame_count": int(sample_count),
        "processing_time_seconds": round(float(elapsed), 4),
        "effective_processing_fps": round(float(sample_count / elapsed), 3) if elapsed > 0 else 0.0,
        "backend": "cpu" if use_cpu else "auto",
    }
    if benchmark:
        return result
    return {
        "average_motion": result["average_motion"],
        "peak_motion": result["peak_motion"],
        "segments": result["segments"],
        "samples": result["samples"],
        "source_fps": result["source_fps"],
        "sampled_fps": result["sampled_fps"],
        "frame_count": result["frame_count"],
        "sampled_frame_count": result["sampled_frame_count"],
        "processing_time_seconds": result["processing_time_seconds"],
        "effective_processing_fps": result["effective_processing_fps"],
        "backend": result["backend"],
    }
