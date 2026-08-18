from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from game_ai_editor.config.loader import load_game_profile
from game_ai_editor.orchestration.orchestrator import ProductionOrchestrator

PROFILE_PATH = Path(__file__).resolve().parents[1] / "config/games/arma_reforger.json"


def _make_video(path: Path) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 12.0, (320, 240))
    assert writer.isOpened()
    for index in range(36):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.rectangle(frame, (index * 5 % 250, 30), (index * 5 % 250 + 60, 120), (0, 220, 255), -1)
        writer.write(frame)
    writer.release()


@pytest.mark.parametrize("completed_stage", ["metadata", "prefilter", "audio", "motion", "transcription"])
def test_resume_partial_session(tmp_path: Path, monkeypatch, completed_stage: str) -> None:
    video = tmp_path / "synthetic.mp4"
    _make_video(video)
    session = tmp_path / "session"
    profile = load_game_profile(PROFILE_PATH)

    monkeypatch.setattr(
        "game_ai_editor.orchestration.orchestrator.run_prefilter",
        lambda *args, **kwargs: {"candidates": [{"start": 0.5, "end": 2.5, "score": 0.95}], "total_windows": 1},
    )
    monkeypatch.setattr(
        "game_ai_editor.orchestration.orchestrator.analyze_audio",
        lambda path: {"has_audio": False, "segments": [], "average_intensity": 0.0, "peak_intensity": 0.0},
    )
    monkeypatch.setattr(
        "game_ai_editor.orchestration.orchestrator.analyze_motion",
        lambda path: {"samples": [], "peak_motion": 1.0, "average_motion": 0.0},
    )
    monkeypatch.setattr(
        "game_ai_editor.orchestration.orchestrator.transcribe_audio",
        lambda path: {"has_audio": False, "segments": [], "text": "", "speech_reaction": 0.0},
    )
    monkeypatch.setattr(
        "game_ai_editor.orchestration.orchestrator.detect_events",
        lambda *args: [{
            "id": "legacy-1", "event_type": "enemy_contact", "start_time": 0.5, "end_time": 1.0,
            "highlight_score": 70.0, "context_score": 80.0, "confidence": 0.7, "intensity": 0.7,
        }],
    )

    orchestrator = ProductionOrchestrator(profile=profile, vision_provider=None)
    orchestrator.run(video, session_dir=session, max_clips=3)

    payload = json.loads((session / "status.json").read_text(encoding="utf-8"))
    assert payload["status"] in {"SUCCESS", "QC_FAILED"}
    assert payload["stages"][completed_stage]["status"] == "COMPLETE"
