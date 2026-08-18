from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from game_ai_editor.config.loader import load_game_profile
from game_ai_editor.orchestration.fusion import fuse_events, normalize_events
from game_ai_editor.orchestration.orchestrator import ProductionOrchestrator
from game_ai_editor.orchestration.state import (
    configuration_fingerprint,
    source_identity,
    source_matches,
    stage_status,
)
from game_ai_editor.vision.models import VisionResult
from game_ai_editor.vision.ollama import OllamaUnavailableError

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


def test_configuration_fingerprint_changes_with_clip_count() -> None:
    profile = load_game_profile(PROFILE_PATH)
    first = configuration_fingerprint(profile, max_clips=3, target_duration=None)
    second = configuration_fingerprint(profile, max_clips=4, target_duration=None)
    assert first != second


def test_orchestrator_cancellation_stops_before_pipeline_stage(tmp_path: Path) -> None:
    video = tmp_path / "synthetic.mp4"
    video.write_bytes(b"synthetic")
    session = tmp_path / "session"
    profile = load_game_profile(PROFILE_PATH)

    orchestrator = ProductionOrchestrator(
        profile=profile,
        vision_provider=None,
        cancellation_requested=lambda: True,
    )

    try:
        orchestrator.run(video, session_dir=session)
    except RuntimeError as exc:
        assert str(exc) == "JOB_CANCELLED"
    else:
        raise AssertionError("cancellation was ignored")

    payload = json.loads((session / "status.json").read_text(encoding="utf-8"))
    assert payload["error_code"] == "JOB_CANCELLED"


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


class OfflineVisionProvider(FakeVisionProvider):
    def check_available(self) -> None:
        raise OllamaUnavailableError("offline")


def test_orchestrator_degrades_when_vision_is_offline(tmp_path: Path, monkeypatch) -> None:
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

    result = ProductionOrchestrator(profile=profile, vision_provider=OfflineVisionProvider()).run(
        video, session_dir=session, max_clips=3,
    )
    status_payload = json.loads((session / "status.json").read_text(encoding="utf-8"))
    assert result["status"] == "SUCCESS"
    assert status_payload["degraded_mode"] is True
    assert status_payload["degraded_reason"] == "VISION_PROVIDER_OFFLINE"
    assert status_payload["stages"]["vision"]["status"] == "SKIPPED"
    assert stage_status(session)["audio"] == "COMPLETE"
    assert stage_status(session)["transcription"] == "COMPLETE"


def test_orchestrator_resumes_cached_artifacts(tmp_path: Path, monkeypatch) -> None:
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
    first = ProductionOrchestrator(profile=profile, vision_provider=None).run(video, session_dir=session, max_clips=3)
    assert first["status"] == "SUCCESS"

    (session / "ranking.json").write_text("{corrupted", encoding="utf-8")
    score_calls = []
    original_score_candidates = __import__(
        "game_ai_editor.orchestration.orchestrator", fromlist=["score_candidates"]
    ).score_candidates
    monkeypatch.setattr(
        "game_ai_editor.orchestration.orchestrator.score_candidates",
        lambda *args, **kwargs: (score_calls.append(True) or original_score_candidates(*args, **kwargs)),
    )
    monkeypatch.setattr("game_ai_editor.orchestration.orchestrator.probe_media", lambda path: (_ for _ in ()).throw(AssertionError("metadata recomputed")))
    monkeypatch.setattr("game_ai_editor.orchestration.orchestrator.analyze_audio", lambda path: (_ for _ in ()).throw(AssertionError("audio recomputed")))
    monkeypatch.setattr("game_ai_editor.orchestration.orchestrator.analyze_motion", lambda path: (_ for _ in ()).throw(AssertionError("motion recomputed")))
    monkeypatch.setattr("game_ai_editor.orchestration.orchestrator.transcribe_audio", lambda path: (_ for _ in ()).throw(AssertionError("transcript recomputed")))
    second = ProductionOrchestrator(profile=profile, vision_provider=None).run(video, session_dir=session, max_clips=3)

    assert second["status"] == "SUCCESS"
    assert Path(second["final_path"]).exists()
    assert score_calls


def test_no_highlights_invalidates_previous_current_output(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "synthetic.mp4"
    _make_video(video)
    session = tmp_path / "session"
    profile = load_game_profile(PROFILE_PATH)

    monkeypatch.setattr(
        "game_ai_editor.orchestration.orchestrator.run_prefilter",
        lambda *args, **kwargs: {"candidates": [], "total_windows": 1},
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
    first = ProductionOrchestrator(profile=profile, vision_provider=None, resume=False).run(video, session_dir=session)
    assert first["status"] == "SUCCESS"
    final_path = Path(first["final_output_path"])
    preview_path = Path(first["preview_output_path"])
    assert final_path.exists() and preview_path.exists()
    original_final = final_path.read_bytes()
    import game_ai_editor.orchestration.orchestrator as orchestrator_module

    original_render_final = orchestrator_module.render_final
    monkeypatch.setattr(
        "game_ai_editor.orchestration.orchestrator.render_final",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("render failed")),
    )
    try:
        ProductionOrchestrator(profile=profile, vision_provider=None, resume=False).run(video, session_dir=session)
    except RuntimeError as exc:
        assert str(exc) == "render failed"
    else:
        raise AssertionError("render failure was ignored")
    assert final_path.read_bytes() == original_final
    assert not final_path.with_name("final.tmp.mp4").exists()
    monkeypatch.setattr(
        "game_ai_editor.orchestration.orchestrator.render_final",
        original_render_final,
    )

    monkeypatch.setattr(
        "game_ai_editor.orchestration.orchestrator.detect_events",
        lambda *args: [],
    )
    second = ProductionOrchestrator(profile=profile, vision_provider=None, resume=False).run(video, session_dir=session)
    assert second["status"] == "NO_HIGHLIGHTS"
    assert not final_path.exists()
    assert not preview_path.exists()
    status = json.loads((session / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "NO_HIGHLIGHTS"
    assert status["final_output_path"] is None


def test_interrupted_vision_resumes_completed_windows(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "synthetic.mp4"
    _make_video(video)
    session = tmp_path / "session"
    profile = load_game_profile(PROFILE_PATH)
    monkeypatch.setattr(
        "game_ai_editor.orchestration.orchestrator.run_prefilter",
        lambda *args, **kwargs: {
            "candidates": [
                {"start": 0.1, "end": 0.8, "score": 0.95},
                {"start": 0.9, "end": 1.6, "score": 0.9},
                {"start": 1.7, "end": 2.4, "score": 0.85},
            ],
            "total_windows": 3,
        },
    )
    monkeypatch.setattr("game_ai_editor.orchestration.orchestrator.analyze_audio", lambda path: {"has_audio": False, "segments": []})
    monkeypatch.setattr("game_ai_editor.orchestration.orchestrator.analyze_motion", lambda path: {"samples": []})
    monkeypatch.setattr("game_ai_editor.orchestration.orchestrator.transcribe_audio", lambda path: {"has_audio": False, "segments": []})
    monkeypatch.setattr("game_ai_editor.orchestration.orchestrator.detect_events", lambda *args: [])

    class InterruptingProvider(FakeVisionProvider):
        calls = 0

        def analyze(self, request) -> VisionResult:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("JOB_CANCELLED")
            return super().analyze(request)

    provider = InterruptingProvider()
    try:
        ProductionOrchestrator(profile=profile, vision_provider=provider, resume=False).run(video, session_dir=session)
    except RuntimeError as exc:
        assert str(exc) == "JOB_CANCELLED"
    else:
        raise AssertionError("Vision interruption was ignored")
    assert (session / "vision" / "window_000001.json").exists()
    assert not (session / "vision" / "window_000002.json").exists()
    interrupted_status = json.loads((session / "status.json").read_text(encoding="utf-8"))
    assert interrupted_status["status"] == "CANCELLED"

    resumed = ProductionOrchestrator(profile=profile, vision_provider=FakeVisionProvider(), resume=True).run(
        video, session_dir=session,
    )
    assert resumed["status"] == "SUCCESS"