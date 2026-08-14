from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from game_ai_editor.batch import (
    build_batch_manifest,
    discover_videos,
    next_pending_stage,
    run_batch,
)


def _fake_metadata(path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        duration=12.5,
        model_dump=lambda: {"source_path": str(path), "duration": 12.5, "video_stream": True},
    )


def test_video_discovery_ignores_unsupported_hidden_and_temp_files(tmp_path: Path) -> None:
    (tmp_path / "session_01.mp4").write_bytes(b"video")
    (tmp_path / "session_02.mkv").write_bytes(b"video")
    (tmp_path / "clip.mov").write_bytes(b"video")
    (tmp_path / "clip.webm").write_bytes(b"video")
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")
    (tmp_path / ".hidden.mp4").write_bytes(b"ignore")
    (tmp_path / "~$recording.mp4").write_bytes(b"ignore")
    assert [path.name for path in discover_videos(tmp_path)] == [
        "clip.mov",
        "clip.webm",
        "session_01.mp4",
        "session_02.mkv",
    ]


def test_video_id_and_manifest_resume(monkeypatch, tmp_path: Path) -> None:
    video = tmp_path / "session_01.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr("game_ai_editor.batch.probe_media", _fake_metadata)

    first = build_batch_manifest(tmp_path, work_root=tmp_path / "work", dry_run=True)
    entry = first["videos"][0]
    assert first["video_count"] == 1
    assert first["total_duration"] == 12.5
    assert entry["next_stage"] == "prefilter"
    assert Path(first["manifest_path"]).exists()

    session_dir = Path(entry["session_dir"])
    prefilter_path = session_dir / "prefilter" / "candidates.json"
    prefilter_path.parent.mkdir(parents=True)
    prefilter_path.write_text("{}", encoding="utf-8")

    second = build_batch_manifest(tmp_path, work_root=tmp_path / "work", dry_run=True)
    assert second["batch_id"] == first["batch_id"]
    assert second["videos"][0]["next_stage"] == "vision"
    assert second["videos"][0]["stages"]["prefilter"] == "completed"


def test_stage_progression() -> None:
    assert next_pending_stage({"metadata": "completed", "prefilter": "pending"}) == "prefilter"
    assert next_pending_stage({stage: "completed" for stage in ("metadata", "prefilter", "vision", "refinement", "render")}) is None


def test_empty_folder_dry_run(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("game_ai_editor.batch.probe_media", _fake_metadata)
    result = run_batch(tmp_path, dry_run=True, work_root=tmp_path / "work")
    assert result["video_count"] == 0
    assert result["total_duration"] == 0.0
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["videos"] == []
