from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from game_ai_editor.batch import (
    build_batch_manifest,
    discover_videos,
    next_pending_stage,
    run_batch,
)
from game_ai_editor.storage import ensure_project_output_dir, project_id_from_source


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

    # video_id is a hash of the video's absolute path, but session_dir is canonical
    # (work/sessions/<video_id>, not scoped under tmp_path/work_root). pytest reuses
    # physical tmp_path roots after a handful of runs, so without cleanup this test
    # can collide with its own leftovers from an earlier invocation.
    session_dir: Path | None = None
    try:
        first = build_batch_manifest(tmp_path, work_root=tmp_path / "work", dry_run=True)
        entry = first["videos"][0]
        session_dir = Path(entry["session_dir"])
        assert first["video_count"] == 1
        assert first["total_duration"] == 12.5
        assert entry["next_stage"] == "prefilter"
        assert Path(first["manifest_path"]).exists()

        prefilter_path = session_dir / "prefilter" / "candidates.json"
        prefilter_path.parent.mkdir(parents=True)
        prefilter_path.write_text("{}", encoding="utf-8")

        second = build_batch_manifest(tmp_path, work_root=tmp_path / "work", dry_run=True)
        assert second["batch_id"] == first["batch_id"]
        assert second["videos"][0]["next_stage"] == "vision"
        assert second["videos"][0]["stages"]["prefilter"] == "completed"
    finally:
        if session_dir is not None:
            shutil.rmtree(session_dir, ignore_errors=True)


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


def test_batch_uses_canonical_sessions_and_outputs_for_mixed_results(monkeypatch, tmp_path: Path) -> None:
    for name in ("video1.mp4", "video2.mp4", "video3.mp4"):
        (tmp_path / name).write_bytes(name.encode())
    monkeypatch.setattr("game_ai_editor.batch.probe_media", _fake_metadata)

    class FakeOrchestrator:
        @classmethod
        def from_profile_path(cls, profile_path, resume=True):
            return cls()

        def run(self, source, *, session_dir, max_clips):
            project_id = project_id_from_source(source)
            output_dir = ensure_project_output_dir(project_id)
            source_name = Path(source).stem
            if source_name == "video2":
                return {
                    "status": "NO_HIGHLIGHTS",
                    "session_dir": str(session_dir),
                    "selected": [],
                    "final_output_path": None,
                    "preview_output_path": None,
                    "output_directory": str(output_dir),
                }
            final_path = output_dir / "final.mp4"
            preview_path = output_dir / "preview.mp4"
            final_path.write_bytes(b"final")
            preview_path.write_bytes(b"preview")
            return {
                "status": "SUCCESS",
                "session_dir": str(session_dir),
                "selected": [{"event_type": "kill"}],
                "final_path": str(final_path),
                "final_output_path": str(final_path),
                "preview_output_path": str(preview_path),
                "output_directory": str(output_dir),
            }

    monkeypatch.setattr("game_ai_editor.batch.ProductionOrchestrator", FakeOrchestrator)
    result = run_batch(tmp_path, work_root=tmp_path / "batch-work", final_dir=tmp_path / "legacy")

    assert result["production_summary"]["successful_videos"] == 2
    assert result["production_summary"]["failed_videos"] == 1
    assert result["montage_path"] is None
    for name in ("video1.mp4", "video3.mp4"):
        output_dir = ensure_project_output_dir(project_id_from_source(tmp_path / name))
        assert (output_dir / "final.mp4").exists()
        assert (output_dir / "preview.mp4").exists()
    video2_output = ensure_project_output_dir(project_id_from_source(tmp_path / "video2.mp4"))
    assert not (video2_output / "final.mp4").exists()
    assert not (tmp_path / "legacy").exists()
    for video in result["videos"]:
        assert Path(video["session_dir"]).as_posix().replace("\\", "/").startswith("work/sessions/")
