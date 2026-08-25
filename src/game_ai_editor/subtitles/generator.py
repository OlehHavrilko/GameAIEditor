from __future__ import annotations

from pathlib import Path
from typing import Any


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = round(max(0.0, seconds) * 1000)
    hours, remainder_ms = divmod(total_ms, 3_600_000)
    minutes, remainder_ms = divmod(remainder_ms, 60_000)
    secs, millis = divmod(remainder_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def clip_relative_segments(
    transcript_segments: list[dict[str, Any]], clip_start: float, clip_end: float
) -> list[dict[str, Any]]:
    """Select transcript segments overlapping [clip_start, clip_end) and re-time
    them relative to the clip, since each rendered clip is its own MP4 starting
    at time zero once cut out of the source video."""
    relative: list[dict[str, Any]] = []
    for segment in transcript_segments:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        seg_start = float(segment.get("start", 0.0))
        seg_end = float(segment.get("end", seg_start))
        overlap_start = max(seg_start, clip_start)
        overlap_end = min(seg_end, clip_end)
        if overlap_end <= overlap_start:
            continue
        relative.append(
            {
                "start": round(overlap_start - clip_start, 3),
                "end": round(overlap_end - clip_start, 3),
                "text": text,
            }
        )
    return relative


def write_srt(segments: list[dict[str, Any]], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for index, segment in enumerate(segments, start=1):
        lines.append(str(index))
        lines.append(f"{_format_srt_timestamp(segment['start'])} --> {_format_srt_timestamp(segment['end'])}")
        lines.append(segment["text"])
        lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")
    return output
