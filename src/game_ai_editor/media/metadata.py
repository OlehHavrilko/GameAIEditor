from __future__ import annotations

import json
import subprocess
from pathlib import Path

from pydantic import BaseModel


class MediaMetadata(BaseModel):
    source_path: str
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    video_stream: bool = False
    audio_stream: bool = False
    format_name: str | None = None
    bitrate: int | None = None


def _parse_fraction(value: str | None) -> float | None:
    if value in (None, "", "0/0", "N/A"):
        return None
    try:
        numerator, denominator = value.split("/")
        num = float(numerator)
        den = float(denominator)
        if den == 0:
            return None
        return num / den
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return None


def probe_media(path: str | Path) -> MediaMetadata:
    input_path = Path(path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input media not found: {input_path}")

    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(input_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {input_path}: {result.stderr.strip()}")

    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    format_info = payload.get("format", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = format_info.get("duration")
    try:
        duration_value = float(duration) if duration is not None else 0.0
    except (TypeError, ValueError):
        duration_value = 0.0

    fps_value = None
    if video_stream is not None:
        for field in ("avg_frame_rate", "r_frame_rate", "real_frame_rate"):
            fps_value = _parse_fraction(video_stream.get(field))
            if fps_value is not None:
                break

    return MediaMetadata(
        source_path=str(input_path),
        duration=round(duration_value, 3),
        width=int(video_stream.get("width")) if video_stream and video_stream.get("width") is not None else None,
        height=int(video_stream.get("height")) if video_stream and video_stream.get("height") is not None else None,
        fps=round(fps_value, 3) if fps_value is not None else None,
        video_codec=video_stream.get("codec_name") if video_stream else None,
        video_stream=video_stream is not None,
        audio_stream=audio_stream is not None,
        format_name=format_info.get("format_name"),
        bitrate=int(format_info.get("bit_rate")) if format_info.get("bit_rate") is not None else None,
    )
