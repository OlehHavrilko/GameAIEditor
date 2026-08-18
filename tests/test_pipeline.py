from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

from game_ai_editor.analysis.motion import analyze_motion
from game_ai_editor.audio.analysis import analyze_audio
from game_ai_editor.config.loader import load_game_profile
from game_ai_editor.events.detector import detect_events
from game_ai_editor.media.metadata import probe_media
from game_ai_editor.runtime import get_python_executable
from game_ai_editor.scoring.score import score_candidates
from game_ai_editor.selection.selector import select_highlights
from game_ai_editor.timeline.planner import build_timeline
from game_ai_editor.transcription.whisper import transcribe_audio

PROFILE_PATH = Path(__file__).resolve().parents[1] / "config/games/arma_reforger.json"


def _make_test_video(path: Path, duration_seconds: float = 3.0) -> None:
    fps = 15.0
    width, height = 320, 240
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"Could not open video writer for {path}")

    total_frames = int(duration_seconds * fps)
    for index in range(total_frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        x = (index * 3) % (width - 80)
        cv2.rectangle(frame, (x, 40), (x + 60, 120), (0, 255, 255), -1)
        if index % 8 == 0:
            cv2.circle(frame, (220, 150), 20, (0, 0, 255), -1)
        writer.write(frame)

    writer.release()


def test_game_profile_loads() -> None:
    profile = load_game_profile(PROFILE_PATH)
    assert profile.game_id == "arma_reforger"
    assert "firefight" in profile.interesting_events
    assert "walking" in profile.ignored_events


def test_python_child_uses_current_interpreter() -> None:
    result = subprocess.run(
        [get_python_executable(), "-c", "import sys; print(sys.executable)"],
        capture_output=True,
        text=True,
        check=True,
    )
    child_executable = Path(result.stdout.strip()).resolve()
    assert child_executable == Path(sys.executable).resolve()


def test_motion_event_detection_and_selection(tmp_path: Path) -> None:
    video_path = tmp_path / "synthetic_test_video.mp4"
    _make_test_video(video_path)

    profile = load_game_profile(PROFILE_PATH)
    metadata = probe_media(video_path)
    motion = analyze_motion(video_path)
    audio = analyze_audio(video_path)
    transcript = transcribe_audio(video_path)

    assert metadata.video_stream is True
    assert motion["samples"]
    events = detect_events(metadata, audio, motion, transcript, profile)
    assert len(events) >= 1

    candidates = score_candidates(events, profile)
    assert len(candidates) == len(events)
    selected = select_highlights(candidates, profile, max_count=3)
    assert len(selected) >= 1

    timeline = build_timeline(selected, float(metadata.duration or 0.0), profile)
    assert len(timeline) == len(selected)
    assert all(segment["start_time"] <= segment["end_time"] for segment in timeline)
