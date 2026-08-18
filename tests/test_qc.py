from pathlib import Path
from types import SimpleNamespace

from game_ai_editor.qc.checks import run_qc


def _metadata(path: Path, *, duration: float = 2.0, audio: bool = False):
    payload = {
        "source_path": str(path),
        "duration": duration,
        "width": 320,
        "height": 240,
        "fps": 15.0,
        "video_codec": "h264",
        "video_stream": True,
        "audio_stream": audio,
    }
    return SimpleNamespace(
        duration=duration,
        width=320,
        height=240,
        fps=15.0,
        video_codec="h264",
        video_stream=True,
        audio_stream=audio,
        model_dump=lambda: payload,
    )


def test_qc_rejects_missing_and_undecodable_outputs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "game_ai_editor.qc.checks.probe_media",
        lambda path: (_ for _ in ()).throw(RuntimeError("ffprobe failed")),
    )
    result = run_qc(tmp_path / "preview.mp4", tmp_path / "final.mp4")
    assert result["passed"] is False
    assert result["errors"]


def test_qc_accepts_video_only_outputs_with_audio_warning(monkeypatch, tmp_path: Path) -> None:
    preview = tmp_path / "preview.mp4"
    final = tmp_path / "final.mp4"
    preview.write_bytes(b"preview")
    final.write_bytes(b"final")
    monkeypatch.setattr("game_ai_editor.qc.checks.probe_media", lambda path: _metadata(Path(path)))
    result = run_qc(preview, final, timeline=[{"start_time": 0.0, "end_time": 2.0}])
    assert result["passed"] is True
    assert result["warnings"]


def test_qc_rejects_invalid_timeline_bounds(monkeypatch, tmp_path: Path) -> None:
    preview = tmp_path / "preview.mp4"
    final = tmp_path / "final.mp4"
    preview.write_bytes(b"preview")
    final.write_bytes(b"final")
    monkeypatch.setattr("game_ai_editor.qc.checks.probe_media", lambda path: _metadata(Path(path)))
    result = run_qc(
        preview,
        final,
        source_path=tmp_path / "source.mp4",
        timeline=[{"start_time": -1.0, "end_time": 2.0}],
    )
    assert result["passed"] is False
    assert any("timeline" in error for error in result["errors"])
