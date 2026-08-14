from __future__ import annotations

from pathlib import Path

from game_ai_editor.media.metadata import probe_media


def run_qc(
    preview_path: str | Path,
    final_path: str | Path,
    *,
    source_path: str | Path | None = None,
    timeline: list[dict] | None = None,
) -> dict:
    checks: list[dict] = []
    for label, target in [("preview", preview_path), ("final", final_path)]:
        file_path = Path(target)
        exists = file_path.exists()
        info = None
        if exists:
            try:
                info = probe_media(file_path).model_dump()
            except Exception:
                info = {"source_path": str(file_path), "duration": None}
        result = {
            "label": label,
            "path": str(file_path),
            "exists": exists,
            "duration": info.get("duration") if info else None,
            "width": info.get("width") if info else None,
            "height": info.get("height") if info else None,
            "audio_stream": info.get("audio_stream") if info else False,
        }
        checks.append(result)

    timeline_bounds = True
    if source_path is not None and timeline is not None:
        source_info = probe_media(source_path).model_dump()
        source_duration = float(source_info.get("duration") or 0.0)
        timeline_bounds = all(
            0.0 <= float(item.get("start_time", -1.0)) < float(item.get("end_time", 0.0)) <= source_duration
            for item in timeline
        )

    passed = timeline_bounds and all(
        check["exists"] and (check["duration"] is None or float(check["duration"]) > 0.0)
        for check in checks
    )

    return {
        "passed": passed,
        "checks": checks,
        "timeline_bounds": timeline_bounds,
        "warnings": [] if passed else ["Render output, timeline, or source bounds are invalid."],
    }
