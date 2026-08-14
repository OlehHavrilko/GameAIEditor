from __future__ import annotations

import subprocess
from pathlib import Path


def run_ffmpeg(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg command failed: {' '.join(command)}\n{result.stderr.strip()}")
    return result


def build_preview(source_path: str | Path, timeline: list[dict], output_path: str | Path) -> Path:
    source = Path(source_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    clips_dir = output.parent / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    if not timeline:
        fallback_duration = 3.0
        timeline = [{"start_time": 0.0, "end_time": fallback_duration}]

    clip_paths: list[Path] = []
    for index, segment in enumerate(timeline):
        start = max(0.0, float(segment.get("start_time", 0.0)))
        end = max(start + 0.5, float(segment.get("end_time", start + 0.5)))
        clip_path = clips_dir / f"clip_{index:02d}.mp4"
        command = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start),
            "-to",
            str(end),
            "-i",
            str(source),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(clip_path),
        ]
        run_ffmpeg(command)
        clip_paths.append(clip_path)

    concat_path = output.parent / "concat.txt"
    with concat_path.open("w", encoding="utf-8") as handle:
        for clip_path in clip_paths:
            relative_clip = clip_path.relative_to(output.parent).as_posix()
            handle.write(f"file '{relative_clip}'\n")

    command = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output),
    ]
    run_ffmpeg(command)
    return output


def render_final(preview_path: str | Path, output_path: str | Path) -> Path:
    preview = Path(preview_path)
    final_output = Path(output_path)
    final_output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(preview),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(final_output),
    ]
    run_ffmpeg(command)
    return final_output
