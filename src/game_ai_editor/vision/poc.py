from __future__ import annotations

import json
import time
from pathlib import Path

from .models import VisionRequest
from .ollama import OllamaVisionProvider
from .sampler import sample_scene_frames


def run_vision_test(
    video_path: str | Path,
    *,
    start_time: float = 30.0,
    end_time: float = 40.0,
    output_dir: str | Path = "work/vision_test",
    base_url: str = "http://localhost:11434",
    model: str = "qwen3-vl:8b-instruct",
    timeout_seconds: float = 120.0,
    max_frames: int = 5,
    width: int = 512,
    height: int = 288,
) -> dict:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    total_started = time.perf_counter()
    frames, extraction_time = sample_scene_frames(
        video_path,
        start_time,
        end_time,
        max_frames=max_frames,
        output_dir=output_path,
        width=width,
        height=height,
    )
    request_data = VisionRequest(
        scene_id="vision_test_scene",
        video_path=str(video_path),
        frame_paths=[frame.path for frame in frames],
        start_time=start_time,
        end_time=end_time,
    )
    result = OllamaVisionProvider(
        base_url=base_url, model=model, timeout_seconds=timeout_seconds
    ).analyze(request_data)
    result.extraction_time_seconds = round(extraction_time, 4)
    result.total_time_seconds = round(time.perf_counter() - total_started, 4)
    result.frame_dimensions = [
        {"width": frame.width, "height": frame.height} for frame in frames
    ]
    result.frame_count = len(frames)
    result_path = output_path / "result.json"
    result_path.write_text(
        json.dumps(result.model_dump(), indent=2), encoding="utf-8"
    )
    payload = result.model_dump()
    return {
        "result": payload,
        "result_path": str(result_path),
        "frame_paths": [frame.path for frame in frames],
        "frame_count": len(frames),
        "frame_dimensions": result.frame_dimensions,
        "extraction_time_seconds": result.extraction_time_seconds,
        "inference_time_seconds": result.inference_time_seconds,
        "total_time_seconds": result.total_time_seconds,
        "response_size_bytes": result.response_size_bytes,
        "requested_width": width,
        "requested_height": height,
    }
