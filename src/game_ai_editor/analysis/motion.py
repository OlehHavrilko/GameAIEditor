from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

_SCALE_WIDTH = 320
_SCALE_HEIGHT = 180


def _probe_frame_stats(path: Path) -> tuple[float, int]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video for motion analysis: {path}")
    try:
        source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    finally:
        cap.release()
    return source_fps, total_frames


def _extract_gray_frames(path: Path, processing_fps: float) -> list[np.ndarray]:
    frame_size = _SCALE_WIDTH * _SCALE_HEIGHT
    scale_filter = (
        f"fps={max(processing_fps, 0.1):.8f},"
        f"scale={_SCALE_WIDTH}:{_SCALE_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={_SCALE_WIDTH}:{_SCALE_HEIGHT}:(ow-iw)/2:(oh-ih)/2,format=gray"
    )
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(path),
        "-an", "-sn", "-dn",
        "-vf", scale_filter,
        "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ]
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg motion extraction failed: {process.stderr.decode('utf-8', errors='replace').strip()}")

    raw = process.stdout
    frame_count = len(raw) // frame_size
    return [
        np.frombuffer(raw[index * frame_size:(index + 1) * frame_size], dtype=np.uint8).reshape(_SCALE_HEIGHT, _SCALE_WIDTH)
        for index in range(frame_count)
    ]


def analyze_motion(
    path: str | Path,
    motion_threshold: float = 8.0,
    sample_fps: float = 2.0,
    use_cpu: bool = True,
    benchmark: bool = False,
) -> dict[str, Any]:
    input_path = Path(path)
    source_fps, total_frames = _probe_frame_stats(input_path)
    processing_fps = source_fps if source_fps <= 0 else min(max(float(sample_fps or source_fps), 2.0), source_fps)

    start_time = time.perf_counter()
    frames = _extract_gray_frames(input_path, processing_fps)

    prev_gray: np.ndarray | None = None
    total_motion = 0.0
    samples: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    active_start: float | None = None
    active_end: float | None = None
    active_max = 0.0

    for index, gray in enumerate(frames):
        timestamp = index / processing_fps if processing_fps else 0.0
        score = 0.0 if prev_gray is None else float(np.abs(gray.astype(np.int16) - prev_gray.astype(np.int16)).mean())

        samples.append({"time": round(timestamp, 3), "score": round(score, 6)})
        total_motion += score

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

    if active_start is not None:
        assert active_end is not None
        segments.append(
            {
                "start": round(active_start, 3),
                "end": round(active_end, 3),
                "max_score": round(active_max, 6),
            }
        )

    elapsed = time.perf_counter() - start_time
    sample_count = len(samples)
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
