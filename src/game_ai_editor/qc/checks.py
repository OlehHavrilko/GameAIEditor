from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from game_ai_editor.media.metadata import probe_media


def run_qc(
    preview_path: str | Path,
    final_path: str | Path,
    *,
    source_path: str | Path | None = None,
    timeline: list[dict[str, Any]] | None = None,
    expected_audio: bool = False,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    for label, target in [("preview", preview_path), ("final", final_path)]:
        file_path = Path(target)
        exists = file_path.exists()
        info = None
        probe_error = None
        if exists:
            try:
                info = probe_media(file_path).model_dump()
            except Exception as exc:  # noqa: BLE001 - best-effort probe
                probe_error = str(exc)
        result: dict[str, Any] = {
            "label": label,
            "path": str(file_path),
            "exists": exists,
            "size_bytes": file_path.stat().st_size if exists else 0,
            "decodable": info is not None,
            "probe_error": probe_error,
            "duration": info.get("duration") if info else None,
            "width": info.get("width") if info else None,
            "height": info.get("height") if info else None,
            "fps": info.get("fps") if info else None,
            "video_codec": info.get("video_codec") if info else None,
            "video_stream": info.get("video_stream", False) if info else False,
            "audio_stream": info.get("audio_stream", False) if info else False,
        }
        checks.append(result)
        if not exists:
            errors.append(f"{label}: output file is missing")
        elif int(result["size_bytes"]) <= 0:
            errors.append(f"{label}: output file is empty")
        elif info is None:
            errors.append(f"{label}: output is not decodable by ffprobe")
        else:
            for field in ("video_stream", "video_codec", "width", "height", "fps"):
                if not result[field]:
                    errors.append(f"{label}: missing valid {field}")
            if not result["duration"] or float(result["duration"]) <= 0:
                errors.append(f"{label}: duration is not positive")
            if expected_audio and not result["audio_stream"]:
                errors.append(f"{label}: expected audio stream is missing")
            elif not result["audio_stream"]:
                warnings.append(f"{label}: audio stream is missing")

    timeline_bounds = True
    timeline_duration = 0.0
    if source_path is not None and timeline is not None:
        source_info = probe_media(source_path).model_dump()
        source_duration = float(source_info.get("duration") or 0.0)
        for item in timeline:
            start = float(item.get("start_time", -1.0))
            end = float(item.get("end_time", 0.0))
            valid = 0.0 <= start < end <= source_duration
            timeline_bounds = timeline_bounds and valid
            if valid:
                timeline_duration += end - start
        if not timeline_bounds:
            errors.append("timeline: one or more segments are outside source bounds")

    preview_check, final_check = checks
    if preview_check.get("decodable") and final_check.get("decodable"):
        for field in ("width", "height", "video_codec"):
            if preview_check.get(field) != final_check.get(field):
                errors.append(f"preview/final: inconsistent {field}")
        preview_duration = float(preview_check.get("duration") or 0.0)
        final_duration = float(final_check.get("duration") or 0.0)
        if not math.isclose(preview_duration, final_duration, abs_tol=1.0):
            errors.append("preview/final: durations differ by more than 1 second")
        if timeline_duration and not math.isclose(final_duration, timeline_duration, rel_tol=0.08, abs_tol=1.0):
            warnings.append("final: duration differs from timeline total")

    passed = not errors

    return {
        "passed": passed,
        "checks": checks,
        "timeline_bounds": timeline_bounds,
        "errors": errors,
        "warnings": warnings,
    }
