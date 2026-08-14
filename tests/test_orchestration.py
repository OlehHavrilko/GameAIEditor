from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from game_ai_editor.config.loader import load_game_profile
from game_ai_editor.orchestration.fusion import fuse_events, normalize_events
from game_ai_editor.orchestration.orchestrator import ProductionOrchestrator
from game_ai_editor.orchestration.state import source_identity, source_matches, stage_status
from game_ai_editor.vision.models import VisionResult


PROFILE_PATH = Path(__file__).resolve().parents[1] / "config/games/arma_reforger.json"


def _make_video(path: Path) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 12.0, (320, 240))
    assert writer.isOpened()
    for index in range(36):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.rectangle(frame, (index * 5 % 250, 30), (index * 5 % 250 + 60, 120), (0, 220, 255), -1)
        writer.write(frame)
    writer.release()


class FakeVisionProvider:
    def analyze(self, request) -> VisionResult:
        return VisionResult(
            provider="test",
            model="synthetic",
            scene_id=request.scene_id,
            start_time=request.start_time,
            end_time=request.end_time,
            scene_type="combat",
            highlight=True,
            highlight_score=95.0,
            confidence=0.95,
            player_visible=True,
            enemy_visible=True,
            weapon_visible=True,
            events=[{
                "event_type": "kill",
                "confidence": 0.95,
                "intensity": 0.95,
                "description": "synthetic highlight",
            }],
            frame_count=len(request.frame_paths),
            frame_dimensions=[],
            extraction_time_seconds=0.0,
            inference_time_seconds=0.001,
            total_time_seconds=0.001,
            response_size_bytes=10,
        )


def test_normalization_and_fusion_merge_multiple_signal_sources() -> None:
    events = normalize_events([
        {"id": "vision-1", "event_type": "enemy_contact", "start_time": 10, "end_time": 12, "highlight_score": 80, "confidence": 0.8},
    ], "vision")
    events.extend(normalize_events([
        {"id": "audio-1", "event_type": "firefight", "start": 11, "end": 13, "audio_intensity": 1.0, "confidence": 0.7},
    ], "audio"))
    result = fuse_events(events)
    assert len(result) == 1
    assert result[0]["sources"] == ["audio", "vision"]
    assert result[0]["signal_ids"] == ["audio-1", "vision-1"]


def test_source_identity_and_stage_status(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"source")
    identity = source_identity(video)
    assert source_matches({"source_identity": identity.__dict__}, identity)
    assert stage_status(tmp_path)["metadata"] == "NOT_STARTED"


def test_orchestrator_synthetic_e2e_with_mock_vision(tmp_path: Path, monkeypatch) -> None:
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

    result = ProductionOrchestrator(profile=profile, vision_provider=FakeVisionProvider()).run(
        video, session_dir=session, max_clips=3,
    )
    assert result["status"] == "SUCCESS"
    assert result["selected"]
    assert Path(result["final_path"]).exists()
    assert result["qc"]["passed"] is True
    assert (session / "vision" / "window_000001.json").exists()
    assert (session / "output" / "qc.json").exists()