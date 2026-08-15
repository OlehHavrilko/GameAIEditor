from __future__ import annotations

import json
from pathlib import Path

from game_ai_editor.orchestration.session import AnalysisQueue


def test_analysis_queue_persists_and_restores_sessions(tmp_path: Path) -> None:
    queue = AnalysisQueue(tmp_path / "project")
    session = queue.add(tmp_path / "clip.mp4", tmp_path / "session")
    queue.mark_running(session.session_id, "vision")
    queue.mark_failed(session.session_id, "VISION_PROVIDER_OFFLINE", "offline")

    restored = AnalysisQueue(tmp_path / "project")
    sessions = restored.load()

    assert len(sessions) == 1
    assert sessions[0].session_id == session.session_id
    assert sessions[0].status == "FAILED"
    assert sessions[0].errors[0]["code"] == "VISION_PROVIDER_OFFLINE"
    payload = json.loads((tmp_path / "project" / "queue.json").read_text(encoding="utf-8"))
    assert payload["version"] == 1


def test_analysis_queue_deduplicates_source(tmp_path: Path) -> None:
    queue = AnalysisQueue(tmp_path / "project")
    first = queue.add(tmp_path / "clip.mp4", tmp_path / "session")
    second = queue.add(tmp_path / "clip.mp4", tmp_path / "other-session")

    assert first.session_id == second.session_id
    assert len(queue.sessions) == 1


def test_analysis_queue_controls_are_persistent(tmp_path: Path) -> None:
    queue = AnalysisQueue(tmp_path / "project")
    session = queue.add(tmp_path / "clip.mp4", tmp_path / "session")
    queue.pause(session.session_id)
    assert queue.get(session.session_id).status == "PAUSED"
    queue.resume(session.session_id)
    queue.cancel(session.session_id)
    assert queue.get(session.session_id).status == "CANCELLED"
    queue.retry(session.session_id)
    assert queue.get(session.session_id).status == "QUEUED"


def test_analysis_queue_recovers_stale_running_sessions(tmp_path: Path) -> None:
    queue = AnalysisQueue(tmp_path / "project")
    session = queue.add(tmp_path / "clip.mp4", tmp_path / "session")
    queue.mark_running(session.session_id, "vision")

    restored = AnalysisQueue(tmp_path / "project")
    restored.load()

    recovered = restored.get(session.session_id)
    assert recovered is not None
    assert recovered.status == "RECOVERABLE"
    assert recovered.job is not None
    assert recovered.job.status == "RECOVERABLE"