from __future__ import annotations

from pathlib import Path

from game_ai_editor.subtitles import clip_relative_segments, write_srt


def test_clip_relative_segments_shifts_and_clips_to_window() -> None:
    segments = [
        {"start": 8.0, "end": 9.0, "text": "before clip"},
        {"start": 10.5, "end": 11.5, "text": "nice headshot!"},
        {"start": 14.0, "end": 15.0, "text": "spans the boundary"},
        {"start": 20.0, "end": 21.0, "text": "after clip"},
    ]
    relative = clip_relative_segments(segments, clip_start=10.0, clip_end=14.5)
    assert relative == [
        {"start": 0.5, "end": 1.5, "text": "nice headshot!"},
        {"start": 4.0, "end": 4.5, "text": "spans the boundary"},
    ]


def test_clip_relative_segments_drops_blank_text() -> None:
    segments = [{"start": 0.0, "end": 1.0, "text": "   "}]
    assert clip_relative_segments(segments, clip_start=0.0, clip_end=2.0) == []


def test_write_srt_formats_timestamps_and_index(tmp_path: Path) -> None:
    srt_path = write_srt(
        [
            {"start": 0.0, "end": 1.5, "text": "go go go"},
            {"start": 61.25, "end": 62.0, "text": "nice headshot!"},
        ],
        tmp_path / "clip.srt",
    )
    content = srt_path.read_text(encoding="utf-8")
    assert "1\n00:00:00,000 --> 00:00:01,500\ngo go go" in content
    assert "2\n00:01:01,250 --> 00:01:02,000\nnice headshot!" in content
