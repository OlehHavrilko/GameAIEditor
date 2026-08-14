from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from game_ai_editor.media.metadata import probe_media

from .models import VisionRequest, VisionResult
from .ollama import OllamaVisionProvider
from .prompts import COARSE_SCAN_PROMPT
from .sampler import sample_scene_frames


def split_video_windows(duration: float, window_size: float) -> list[dict[str, float]]:
    if duration < 0:
        raise ValueError("duration must not be negative")
    if window_size <= 0:
        raise ValueError("window_size must be greater than zero")
    windows = []
    start = 0.0
    while start < duration:
        end = min(duration, start + window_size)
        windows.append({"start": round(start, 3), "end": round(end, 3)})
        start = end
    return windows


def filter_candidates(windows: list[dict[str, Any]], threshold: float = 40.0) -> list[dict[str, Any]]:
    candidates = [
        window for window in windows
        if float(window.get("highlight_score", 0.0)) >= threshold
    ]
    return sorted(candidates, key=lambda item: float(item.get("highlight_score", 0.0)), reverse=True)


def _candidate_reason(window: dict[str, Any]) -> str:
    description = str(window.get("description", "")).strip()
    if description:
        return description
    events = window.get("events", [])
    return "; ".join(str(event.get("description", "")) for event in events if event.get("description"))


def run_vision_scan(
    video_path: str | Path,
    *,
    window_size: float = 15.0,
    max_frames: int = 5,
    width: int = 512,
    height: int = 288,
    max_windows: int | None = None,
    output_dir: str | Path | None = None,
    base_url: str = "http://localhost:11434",
    model: str = "qwen3-vl:8b-instruct",
    timeout_seconds: float = 120.0,
    use_prefilter: bool = False,
    prefilter_threshold: float = 0.4,
    progress: Callable[[str], None] = print,
) -> dict[str, Any]:
    input_path = Path(video_path)
    metadata = probe_media(input_path)
    duration = float(metadata.duration or 0.0)
    prefilter_report = None
    if use_prefilter:
        from .prefilter import run_prefilter

        prefilter_report = run_prefilter(
            input_path,
            window_size=window_size,
            threshold=prefilter_threshold,
            max_windows=max_windows,
        )
        windows = [
            {"start": item["start"], "end": item["end"]}
            for item in prefilter_report["candidates"]
        ]
    else:
        windows = split_video_windows(duration, window_size)
        if max_windows is not None:
            if max_windows < 1:
                raise ValueError("max_windows must be at least 1")
            windows = windows[:max_windows]

    provider = OllamaVisionProvider(
        base_url=base_url,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    provider.check_available()

    if output_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path("work/vision_scan") / f"{input_path.stem}_{timestamp}"
    else:
        output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    window_results: list[dict[str, Any]] = []
    total_windows = len(windows)
    for index, window in enumerate(windows, start=1):
        window_started = time.perf_counter()
        frame_dir = output_path / "frames" / f"window_{index:03d}"
        try:
            frames, extraction_time = sample_scene_frames(
                input_path,
                window["start"],
                window["end"],
                max_frames=max_frames,
                output_dir=frame_dir,
                width=width,
                height=height,
            )
            request_data = VisionRequest(
                scene_id=f"window_{index:03d}",
                video_path=str(input_path),
                frame_paths=[frame.path for frame in frames],
                start_time=window["start"],
                end_time=window["end"],
                prompt=COARSE_SCAN_PROMPT,
            )
            vision_result = provider.analyze(request_data)
            vision_result.extraction_time_seconds = round(extraction_time, 4)
            vision_result.total_time_seconds = round(time.perf_counter() - window_started, 4)
            vision_result.frame_count = len(frames)
            vision_result.frame_dimensions = [
                {"width": frame.width, "height": frame.height} for frame in frames
            ]
            result = vision_result.model_dump()
            result["start"] = window["start"]
            result["end"] = window["end"]
        except Exception as exc:
            result = {
                "start": window["start"],
                "end": window["end"],
                "error": str(exc),
                "highlight_score": 0.0,
                "highlight": False,
                "confidence": 0.0,
                "scene_type": "error",
                "events": [],
                "extraction_time_seconds": 0.0,
                "inference_time_seconds": 0.0,
                "total_time_seconds": round(time.perf_counter() - window_started, 4),
            }

        window_results.append(result)
        elapsed = time.perf_counter() - started
        average = elapsed / index
        eta = max(0.0, average * (total_windows - index))
        progress(
            f"[{index:02d}/{total_windows:02d}] "
            f"{window['start']:.0f}:{window['end']:.0f} "
            f"score={float(result.get('highlight_score', 0.0)):.0f} "
            f"elapsed={elapsed:.1f}s avg/window={average:.1f}s ETA={eta:.1f}s"
        )

    candidates = []
    for result in filter_candidates(window_results):
        candidates.append({
            "start": result["start"],
            "end": result["end"],
            "highlight_score": result["highlight_score"],
            "reason": _candidate_reason(result),
        })

    total_time = time.perf_counter() - started
    report = {
        "video": str(input_path),
        "duration": duration,
        "window_size": window_size,
        "frames_per_window": max_frames,
        "width": width,
        "height": height,
        "model": model,
        "prefilter_enabled": use_prefilter,
        "prefilter_threshold": prefilter_threshold if use_prefilter else None,
        "prefilter_windows_checked": (
            prefilter_report["total_windows"] if prefilter_report is not None else None
        ),
        "total_windows": len(window_results),
        "total_processing_time_seconds": round(total_time, 4),
        "average_time_per_window_seconds": round(total_time / len(window_results), 4) if window_results else 0.0,
        "windows": window_results,
        "candidates": candidates,
    }
    result_path = output_path / "scan.json"
    result_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["session_dir"] = str(output_path)
    report["scan_path"] = str(result_path)
    return report
