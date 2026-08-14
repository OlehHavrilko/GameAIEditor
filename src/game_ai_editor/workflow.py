from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from game_ai_editor.analysis.motion import analyze_motion
from game_ai_editor.audio.analysis import analyze_audio
from game_ai_editor.config.loader import load_game_profile
from game_ai_editor.editing.ffmpeg_editor import build_preview, render_final
from game_ai_editor.events.detector import detect_events
from game_ai_editor.media.metadata import probe_media
from game_ai_editor.qc.checks import run_qc
from game_ai_editor.scoring.score import score_candidates
from game_ai_editor.selection.selector import select_highlights
from game_ai_editor.timeline.planner import build_timeline
from game_ai_editor.transcription.whisper import transcribe_audio


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def benchmark_motion_video(source_path: str | Path, sample_fps: float = 2.0, motion_threshold: float = 8.0) -> dict:
    result = analyze_motion(source_path, motion_threshold=motion_threshold, sample_fps=sample_fps, benchmark=True)
    return {
        "source_path": str(Path(source_path)),
        "source_fps": result.get("source_fps"),
        "sampled_fps": result.get("sampled_fps"),
        "frame_count": result.get("frame_count"),
        "sampled_frame_count": result.get("sampled_frame_count"),
        "processing_time_seconds": result.get("processing_time_seconds"),
        "effective_processing_fps": result.get("effective_processing_fps"),
        "average_motion": result.get("average_motion"),
        "peak_motion": result.get("peak_motion"),
        "segments_count": len(result.get("segments", [])),
        "backend": result.get("backend"),
        "processing_mode": "sampled",
    }


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"JSON artifact not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def create_session_dir(source_path: str | Path, work_root: str | Path | None = None) -> Path:
    source = Path(source_path)
    root = Path(work_root) if work_root is not None else Path("work")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_name = f"{source.stem.replace(' ', '_')}_{timestamp}"
    session_dir = root / session_name
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def analyze_video(source_path: str | Path, profile_path: str | Path | None = None, session_dir: str | Path | None = None) -> dict:
    input_path = Path(source_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input video not found: {input_path}")

    profile = load_game_profile(profile_path or Path("config/games/arma_reforger.json"))
    working_dir = Path(session_dir) if session_dir is not None else create_session_dir(input_path)
    working_dir.mkdir(parents=True, exist_ok=True)

    metadata = probe_media(input_path)
    audio_summary = analyze_audio(input_path)
    motion_summary = analyze_motion(input_path)
    transcript = transcribe_audio(input_path)
    events = detect_events(metadata, audio_summary, motion_summary, transcript, profile)

    _write_json(working_dir / "metadata.json", metadata.model_dump())
    _write_json(working_dir / "events.json", events)
    _write_json(working_dir / "audio.json", audio_summary)
    _write_json(working_dir / "motion.json", motion_summary)
    _write_json(working_dir / "transcript.json", transcript)

    return {
        "session_dir": str(working_dir),
        "metadata": metadata.model_dump(),
        "audio_summary": audio_summary,
        "motion_summary": motion_summary,
        "transcript": transcript,
        "events": events,
    }


def detect_candidates(session_dir: str | Path, profile_path: str | Path | None = None) -> list[dict]:
    working_dir = Path(session_dir)
    profile = load_game_profile(profile_path or Path("config/games/arma_reforger.json"))
    events = _read_json(working_dir / "events.json")
    candidates = score_candidates(events, profile)
    _write_json(working_dir / "candidates.json", candidates)
    return candidates


def select_highlights_for_session(session_dir: str | Path, profile_path: str | Path | None = None, max_count: int = 5) -> list[dict]:
    working_dir = Path(session_dir)
    profile = load_game_profile(profile_path or Path("config/games/arma_reforger.json"))
    candidates = _read_json(working_dir / "candidates.json")
    selected = select_highlights(candidates, profile, max_count=max_count)
    _write_json(working_dir / "selection.json", selected)
    return selected


def edit_session(session_dir: str | Path) -> dict:
    working_dir = Path(session_dir)
    metadata = _read_json(working_dir / "metadata.json")
    selection = _read_json(working_dir / "selection.json")
    profile = load_game_profile(Path("config/games/arma_reforger.json"))
    duration = float(metadata.get("duration", 0.0))
    timeline = build_timeline(selection, duration, profile)
    _write_json(working_dir / "timeline.json", timeline)

    source_path = metadata.get("source_path")
    if not source_path:
        raise ValueError("Metadata does not include source_path for timeline editing.")

    preview_path = working_dir / "preview.mp4"
    build_preview(source_path, timeline, preview_path)
    return {"timeline": timeline, "preview": str(preview_path)}


def render_session(session_dir: str | Path) -> str:
    working_dir = Path(session_dir)
    preview_path = working_dir / "preview.mp4"
    final_path = working_dir / "final.mp4"
    if not preview_path.exists():
        raise FileNotFoundError(f"Preview file not found: {preview_path}")
    render_final(preview_path, final_path)
    return str(final_path)


def qc_session(session_dir: str | Path) -> dict:
    working_dir = Path(session_dir)
    preview_path = working_dir / "preview.mp4"
    final_path = working_dir / "final.mp4"
    qc_result = run_qc(preview_path, final_path)
    _write_json(working_dir / "qc.json", qc_result)
    return qc_result


def run_all_pipeline(source_path: str | Path, profile_path: str | Path | None = None) -> dict:
    from game_ai_editor.orchestration.orchestrator import ProductionOrchestrator

    orchestrator = ProductionOrchestrator.from_profile_path(
        profile_path or Path("config/games/arma_reforger.json"),
    )
    return orchestrator.run(source_path)
