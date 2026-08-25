from __future__ import annotations

import json
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from game_ai_editor.editing.ffmpeg_editor import ASPECT_RATIO_PRESETS, build_preview


def _make_source_video(path: Path, duration_seconds: float = 3.0) -> None:
    fps = 15.0
    width, height = 640, 360
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    assert writer.isOpened()
    for index in range(int(duration_seconds * fps)):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        cv2.rectangle(frame, (index * 4 % (width - 60), 40), (index * 4 % (width - 60) + 60, 120), (0, 200, 255), -1)
        writer.write(frame)
    writer.release()


def _probe_dimensions(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(result.stdout)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def _timeline_for(duration: float) -> list[dict]:
    return [{"start_time": 0.0, "end_time": duration}]


def test_build_preview_without_aspect_ratio_keeps_source_dimensions(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    _make_source_video(source)
    output = tmp_path / "preview.mp4"

    build_preview(source, _timeline_for(3.0), output)

    assert _probe_dimensions(output) == (640, 360)


@pytest.mark.parametrize("aspect_ratio", sorted(ASPECT_RATIO_PRESETS))
def test_build_preview_applies_aspect_ratio_preset(tmp_path: Path, aspect_ratio: str) -> None:
    source = tmp_path / "source.mp4"
    _make_source_video(source)
    output = tmp_path / "preview.mp4"

    build_preview(source, _timeline_for(3.0), output, aspect_ratio=aspect_ratio)

    assert _probe_dimensions(output) == ASPECT_RATIO_PRESETS[aspect_ratio]


def test_build_preview_rejects_unknown_aspect_ratio(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    _make_source_video(source)
    output = tmp_path / "preview.mp4"

    with pytest.raises(ValueError):
        build_preview(source, _timeline_for(3.0), output, aspect_ratio="4:3")


def test_build_preview_burns_subtitles_and_writes_relative_srt(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    _make_source_video(source)
    output = tmp_path / "preview.mp4"
    transcript_segments = [{"start": 0.5, "end": 1.5, "text": "nice headshot!"}]

    build_preview(source, _timeline_for(3.0), output, transcript_segments=transcript_segments)

    assert output.exists()
    srt_path = output.parent / "clips" / "clip_00.srt"
    assert srt_path.exists()
    assert "nice headshot!" in srt_path.read_text(encoding="utf-8")


def test_build_preview_skips_srt_when_no_segments_overlap_clip(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    _make_source_video(source)
    output = tmp_path / "preview.mp4"
    transcript_segments = [{"start": 50.0, "end": 51.0, "text": "way outside the clip"}]

    build_preview(source, _timeline_for(3.0), output, transcript_segments=transcript_segments)

    assert output.exists()
    assert not (output.parent / "clips" / "clip_00.srt").exists()
