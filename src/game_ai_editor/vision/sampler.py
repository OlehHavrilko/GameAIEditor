from __future__ import annotations

import subprocess
import time
from pathlib import Path

from PIL import Image  # type: ignore[import-not-found]
from pydantic import BaseModel, Field


class FrameSample(BaseModel):
    path: str
    index: int
    timestamp: float
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    size_bytes: int = Field(ge=0)


class FrameExtractionError(RuntimeError):
    pass


def sample_scene_frames(
    video_path: str | Path,
    start_time: float,
    end_time: float,
    max_frames: int = 5,
    output_dir: str | Path = "work/vision_test",
    width: int = 512,
    height: int = 288,
    jpeg_quality: int = 2,
) -> tuple[list[FrameSample], float]:
    input_path = Path(video_path)
    destination = Path(output_dir)
    if not input_path.exists():
        raise FileNotFoundError(f"Input video not found: {input_path}")
    if end_time <= start_time:
        raise ValueError("end_time must be greater than start_time")
    if max_frames < 1:
        raise ValueError("max_frames must be at least 1")
    if width < 1 or height < 1:
        raise ValueError("width and height must be at least 1")
    if not 2 <= jpeg_quality <= 31:
        raise ValueError("jpeg_quality must be between 2 and 31")

    destination.mkdir(parents=True, exist_ok=True)
    for old_frame in destination.glob("frame_*.jpg"):
        old_frame.unlink()

    duration = end_time - start_time
    fps = max_frames / duration
    pattern = destination / "frame_%02d.jpg"
    command = [
        "ffmpeg", "-y", "-ss", str(start_time), "-i", str(input_path),
        "-an", "-sn", "-dn",
        "-t", str(duration), "-vf", f"fps={fps:.6f},scale={width}:{height}",
        "-frames:v", str(max_frames), "-q:v", str(jpeg_quality), str(pattern),
    ]
    started = time.perf_counter()
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise FrameExtractionError(f"FFmpeg frame extraction failed: {result.stderr.strip()}")

    frame_paths = sorted(destination.glob("frame_*.jpg"))
    if not frame_paths:
        raise FrameExtractionError("FFmpeg completed without producing any frames.")

    samples: list[FrameSample] = []
    for index, frame_path in enumerate(frame_paths):
        try:
            with Image.open(frame_path) as image:
                width, height = image.size
        except Exception as exc:
            raise FrameExtractionError(f"Could not read extracted frame: {frame_path}") from exc
        samples.append(
            FrameSample(
                path=str(frame_path),
                index=index,
                timestamp=round(start_time + (index * duration / len(frame_paths)), 3),
                width=width,
                height=height,
                size_bytes=frame_path.stat().st_size,
            )
        )
    return samples, elapsed
