from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from game_ai_editor.media.metadata import probe_media

from .scan import split_video_windows


class CandidateWindow(BaseModel):
    start: float
    end: float
    score: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)


class PrefilterError(RuntimeError):
    pass


def _read_low_res_video(
    video_path: Path,
    duration: float,
    sample_interval: float,
    max_windows: int | None,
) -> tuple[list[np.ndarray], float, dict[str, Any]]:
    sample_fps = 2.0 / sample_interval
    scan_duration = duration if max_windows is None else min(duration, max_windows * sample_interval)
    base_command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", "0", "-i", str(video_path), "-t", str(scan_duration),
        "-an", "-sn", "-dn",
        "-vf", f"fps={sample_fps:.8f},scale=64:36,format=gray",
        "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ]
    sparse_command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-skip_frame", "nokey",
        "-ss", "0", "-i", str(video_path), "-t", str(scan_duration),
        "-an", "-sn", "-dn",
        "-vf", f"fps={sample_fps:.8f},scale=64:36,format=gray",
        "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ]
    expected_frames = max(1, int(round(scan_duration * sample_fps)))

    def execute(command: list[str]) -> tuple[list[np.ndarray], float, float, float, str]:
        started = time.perf_counter()
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        startup_elapsed = time.perf_counter() - started
        stdout, stderr = process.communicate()
        elapsed = time.perf_counter() - started
        if process.returncode != 0:
            return [], elapsed, startup_elapsed, elapsed - startup_elapsed, stderr.decode("utf-8", errors="replace")
        frame_size = 64 * 36
        if len(stdout) % frame_size != 0:
            return [], elapsed, startup_elapsed, elapsed - startup_elapsed, "incomplete raw frame output"
        frames = [
            np.frombuffer(stdout[offset:offset + frame_size], dtype=np.uint8).reshape(36, 64)
            for offset in range(0, len(stdout), frame_size)
        ]
        return frames, elapsed, startup_elapsed, elapsed - startup_elapsed, ""

    frames, elapsed, startup_elapsed, runtime_elapsed, error_text = execute(sparse_command)
    used_fallback = len(frames) < expected_frames
    commands = [sparse_command]
    if used_fallback:
        frames, elapsed, startup_elapsed, runtime_elapsed, error_text = execute(base_command)
        commands.append(base_command)
    if not frames:
        raise PrefilterError(f"FFmpeg prefilter extraction failed: {error_text.strip()}")

    return frames, elapsed, {
        "command": commands[-1],
        "attempted_commands": commands,
        "startup_time_ms": round(startup_elapsed * 1000.0, 3),
        "runtime_time_ms": round((elapsed - startup_elapsed) * 1000.0, 3),
        "frame_count": len(frames),
        "ffmpeg_calls": len(commands),
        "sparse_keyframe_mode": not used_fallback,
        "fallback_used": used_fallback,
    }


def _read_audio_rms(
    video_path: Path,
    duration: float,
    window_size: float,
    max_windows: int | None,
) -> tuple[list[float], dict[str, Any]]:
    scan_duration = duration if max_windows is None else min(duration, max_windows * window_size)
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", "0", "-i", str(video_path), "-t", str(scan_duration),
        "-vn", "-sn", "-dn", "-ac", "1", "-ar", "8000",
        "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1",
    ]
    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    startup_elapsed = time.perf_counter() - started
    stdout, _ = process.communicate()
    elapsed = time.perf_counter() - started
    if process.returncode != 0 or not stdout:
        return [], {
            "command": command,
            "startup_time_ms": round(startup_elapsed * 1000.0, 3),
            "runtime_time_ms": round((elapsed - startup_elapsed) * 1000.0, 3),
            "ffmpeg_calls": 1,
            "available": False,
        }

    samples = np.frombuffer(stdout, dtype=np.int16).astype(np.float32) / 32768.0
    values: list[float] = []
    sample_rate = 8000
    for index in range(max(1, int(np.ceil(scan_duration / window_size)))):
        start = int(index * window_size * sample_rate)
        end = min(len(samples), int((index + 1) * window_size * sample_rate))
        chunk = samples[start:end]
        values.append(float(np.sqrt(np.mean(np.square(chunk)))) if len(chunk) else 0.0)
    return values, {
        "command": command,
        "startup_time_ms": round(startup_elapsed * 1000.0, 3),
        "runtime_time_ms": round((elapsed - startup_elapsed) * 1000.0, 3),
        "ffmpeg_calls": 1,
        "available": True,
    }


def analyze_prefilter(
    video_path: str | Path,
    *,
    window_size: float = 15.0,
    threshold: float = 0.4,
    max_windows: int | None = None,
) -> dict[str, Any]:
    input_path = Path(video_path)
    metadata = probe_media(input_path)
    duration = float(metadata.duration or 0.0)
    windows = split_video_windows(duration, window_size)
    if max_windows is not None:
        if max_windows < 1:
            raise ValueError("max_windows must be at least 1")
        windows = windows[:max_windows]

    started = time.perf_counter()
    frames, extraction_time, video_metrics = _read_low_res_video(
        input_path, duration, window_size, max_windows
    )
    audio_values, audio_metrics = _read_audio_rms(
        input_path, duration, window_size, max_windows
    )
    visual_values: list[float] = []
    visual_times: list[float] = []
    for index in range(len(windows)):
        first = frames[index * 2] if index * 2 < len(frames) else None
        second = frames[index * 2 + 1] if index * 2 + 1 < len(frames) else None
        visual_started = time.perf_counter()
        if first is None or second is None:
            visual_values.append(0.0)
        else:
            visual_values.append(float(np.mean(np.abs(second.astype(np.float32) - first.astype(np.float32))) / 255.0))
        visual_times.append(time.perf_counter() - visual_started)

    max_audio = max(audio_values, default=0.0)
    window_results: list[dict[str, Any]] = []
    window_diagnostics: list[dict[str, Any]] = []
    for index, window in enumerate(windows):
        window_started = time.perf_counter()
        visual_score = min(1.0, visual_values[index] * 2.5 if index < len(visual_values) else 0.0)
        audio_started = time.perf_counter()
        audio_score = (
            min(1.0, audio_values[index] / max_audio)
            if max_audio > 0 and index < len(audio_values)
            else 0.0
        )
        audio_lookup_time = time.perf_counter() - audio_started
        score = min(1.0, (visual_score * 0.75) + (audio_score * 0.25))
        scene_change_started = time.perf_counter()
        reasons: list[str] = []
        if visual_score >= 0.4:
            reasons.append("high_motion")
        if visual_score >= 0.75:
            reasons.append("scene_change")
        if audio_score >= 0.75:
            reasons.append("audio_activity")
        scene_change_time = time.perf_counter() - scene_change_started
        window_diagnostics.append({
            "window_index": index + 1,
            "start": window["start"],
            "end": window["end"],
            "ffmpeg_calls_for_window": 0,
            "decoded_frames_for_window": 2 if index * 2 + 1 < len(frames) else 0,
            "video_seek_decode_shared": True,
            "visual_activity_time_ms": round(visual_times[index] * 1000.0, 3),
            "scene_change_time_ms": round(scene_change_time * 1000.0, 3),
            "audio_lookup_time_ms": round(audio_lookup_time * 1000.0, 3),
            "compute_time_ms": round((time.perf_counter() - window_started) * 1000.0, 3),
        })
        window_results.append(
            CandidateWindow(
                start=window["start"],
                end=window["end"],
                score=round(score, 4),
                reasons=reasons,
            ).model_dump()
        )

    candidates = sorted(
        [item for item in window_results if item["score"] >= threshold],
        key=lambda item: item["score"],
        reverse=True,
    )
    return {
        "video": str(input_path),
        "duration": duration,
        "window_size": window_size,
        "threshold": threshold,
        "total_windows": len(window_results),
        "processing_time_seconds": round(time.perf_counter() - started, 4),
        "extraction_time_seconds": round(extraction_time, 4),
        "ffmpeg_diagnostics": {
            "video": video_metrics,
            "audio": audio_metrics,
            "video_calls_total": video_metrics["ffmpeg_calls"],
            "audio_calls_total": audio_metrics["ffmpeg_calls"],
            "video_decoded_frames_total": video_metrics["frame_count"],
            "video_seek_decode_shared": True,
        },
        "window_diagnostics": window_diagnostics,
        "windows": window_results,
        "candidates": candidates,
    }


def run_prefilter(
    video_path: str | Path,
    *,
    window_size: float = 15.0,
    threshold: float = 0.4,
    max_windows: int | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    input_path = Path(video_path)
    report = analyze_prefilter(
        input_path,
        window_size=window_size,
        threshold=threshold,
        max_windows=max_windows,
    )
    if output_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path("work/prefilter") / f"{input_path.stem}_{timestamp}"
    else:
        output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    result_path = output_path / "candidates.json"
    result_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["session_dir"] = str(output_path)
    report["result_path"] = str(result_path)
    return report
