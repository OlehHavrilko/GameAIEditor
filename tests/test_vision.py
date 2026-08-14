from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from game_ai_editor.cli import main
from game_ai_editor.vision.models import VisionRequest
from game_ai_editor.vision.ollama import OllamaVisionProvider
from game_ai_editor.vision.poc import run_vision_test
from game_ai_editor.vision.prefilter import analyze_prefilter
from game_ai_editor.vision.scan import filter_candidates, run_vision_scan, split_video_windows


class FakeHTTPResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def test_ollama_provider_sends_all_frames_in_one_request(tmp_path: Path) -> None:
    frame_paths = []
    for index in range(3):
        path = tmp_path / f"frame_{index}.jpg"
        Image.new("RGB", (64, 36), color=(index * 40, 20, 10)).save(path)
        frame_paths.append(str(path))

    response_payload = {
        "message": {
            "content": json.dumps(
                {
                    "scene_type": "firefight",
                    "highlight": True,
                    "highlight_score": 87,
                    "confidence": 0.91,
                    "events": [
                        {
                            "event_type": "enemy_contact",
                            "confidence": 0.91,
                            "intensity": 0.88,
                            "description": "Enemy contact visible.",
                        }
                    ],
                    "entities": ["enemy infantry", "rifle"],
                    "description": "A firefight is developing.",
                }
            )
        }
    }
    request_calls = []

    def fake_urlopen(http_request, timeout):
        request_calls.append((http_request, timeout))
        return FakeHTTPResponse(json.dumps(response_payload).encode("utf-8"))

    with patch("game_ai_editor.vision.ollama.request.urlopen", side_effect=fake_urlopen):
        result = OllamaVisionProvider(timeout_seconds=15).analyze(
            VisionRequest(
                scene_id="scene_1",
                video_path="input/test.mp4",
                frame_paths=frame_paths,
                start_time=30,
                end_time=40,
            )
        )

    assert result.highlight is True
    assert len(request_calls) == 1
    sent_payload = json.loads(request_calls[0][0].data.decode("utf-8"))
    assert sent_payload["stream"] is False
    assert len(sent_payload["messages"][0]["images"]) == 3


def test_vision_test_writes_structured_result_without_network(tmp_path: Path) -> None:
    frame_paths = []
    for index in range(2):
        path = tmp_path / f"source_{index}.jpg"
        Image.new("RGB", (80, 45), color=(index * 30, 20, 10)).save(path)
        frame_paths.append(path)

    fake_result = {
        "provider": "ollama",
        "model": "qwen3-vl:8b-instruct",
        "scene_id": "vision_test_scene",
        "start_time": 30.0,
        "end_time": 40.0,
        "scene_type": "other",
        "highlight": False,
        "highlight_score": 5,
        "confidence": 0.8,
        "events": [],
        "entities": [],
        "description": "No action.",
        "frame_count": 2,
        "frame_dimensions": [],
        "extraction_time_seconds": 0.01,
        "inference_time_seconds": 0.02,
        "total_time_seconds": 0.03,
        "response_size_bytes": 10,
    }

    class FakeResult:
        extraction_time_seconds = 0.01
        inference_time_seconds = 0.02
        total_time_seconds = 0.03
        frame_dimensions = []
        frame_count = 2
        response_size_bytes = 10

        def model_dump(self):
            return fake_result

    fake_frames = [
        type("Frame", (), {"path": str(frame_paths[0]), "width": 80, "height": 45})(),
        type("Frame", (), {"path": str(frame_paths[1]), "width": 80, "height": 45})(),
    ]
    with patch(
        "game_ai_editor.vision.poc.sample_scene_frames",
        return_value=(fake_frames, 0.01),
    ), patch(
        "game_ai_editor.vision.poc.OllamaVisionProvider.analyze",
        return_value=FakeResult(),
    ):
        result = run_vision_test("input/test.mp4", output_dir=tmp_path / "output")

    result_path = tmp_path / "output" / "result.json"
    assert result["frame_count"] == 2
    assert result_path.exists()
    assert json.loads(result_path.read_text(encoding="utf-8"))["scene_type"] == "other"


def test_vision_cli_smoke(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "game_ai_editor.cli.run_vision_test",
        lambda *args, **kwargs: {
            "frame_count": 1,
            "result_path": str(tmp_path / "result.json"),
        },
    )
    assert main(["vision-test", "input/test.mp4"]) == 0
    assert "frame_count" in capsys.readouterr().out


def test_split_windows_and_candidate_sorting() -> None:
    assert split_video_windows(32.0, 15.0) == [
        {"start": 0.0, "end": 15.0},
        {"start": 15.0, "end": 30.0},
        {"start": 30.0, "end": 32.0},
    ]
    windows = [
        {"start": 0, "end": 15, "highlight_score": 42},
        {"start": 15, "end": 30, "highlight_score": 80},
        {"start": 30, "end": 32, "highlight_score": 12},
    ]
    assert [item["highlight_score"] for item in filter_candidates(windows)] == [80, 42]


def test_scan_continues_after_window_error(monkeypatch, tmp_path: Path) -> None:
    class FakeMetadata:
        duration = 32.0

    class FakeFrame:
        def __init__(self, path: str):
            self.path = path
            self.width = 512
            self.height = 288

    class FakeProvider:
        def check_available(self):
            return None

        def analyze(self, request):
            if request.scene_id == "window_002":
                raise RuntimeError("mock inference failure")
            return type(
                "FakeResult",
                (),
                {
                    "highlight_score": 65.0,
                    "model_dump": lambda self: {
                        "provider": "ollama",
                        "model": "qwen3-vl:8b-instruct",
                        "scene_id": request.scene_id,
                        "start_time": request.start_time,
                        "end_time": request.end_time,
                        "scene_type": "firefight",
                        "highlight": True,
                        "highlight_score": 65.0,
                        "confidence": 0.8,
                        "player_visible": True,
                        "enemy_visible": True,
                        "weapon_visible": True,
                        "muzzle_flash": False,
                        "explosion_visible": False,
                        "multiple_enemies": False,
                        "vehicle_visible": False,
                        "events": [],
                        "entities": [],
                        "description": "Combat.",
                        "frame_count": 1,
                        "frame_dimensions": [{"width": 512, "height": 288}],
                        "extraction_time_seconds": 0.1,
                        "inference_time_seconds": 0.2,
                        "total_time_seconds": 0.3,
                        "response_size_bytes": 10,
                    },
                    "total_time_seconds": 0.3,
                    "frame_count": 1,
                    "frame_dimensions": [{"width": 512, "height": 288}],
                    "extraction_time_seconds": 0.1,
                },
            )()

    monkeypatch.setattr("game_ai_editor.vision.scan.probe_media", lambda path: FakeMetadata())
    monkeypatch.setattr("game_ai_editor.vision.scan.OllamaVisionProvider", lambda **kwargs: FakeProvider())
    monkeypatch.setattr(
        "game_ai_editor.vision.scan.sample_scene_frames",
        lambda *args, **kwargs: ([FakeFrame("frame.jpg")], 0.1),
    )

    report = run_vision_scan(
        "input/test.mp4",
        window_size=15,
        max_windows=3,
        output_dir=tmp_path / "scan",
        progress=lambda _: None,
    )
    assert report["total_windows"] == 3
    assert report["windows"][1]["error"] == "mock inference failure"
    assert len(report["candidates"]) == 2
    assert (tmp_path / "scan" / "scan.json").exists()


def test_prefilter_normalizes_scores_and_keeps_conservative_candidates(monkeypatch) -> None:
    class FakeMetadata:
        duration = 32.0

    calm = np.zeros((36, 64), dtype="uint8")
    active = np.full((36, 64), 255, dtype="uint8")
    monkeypatch.setattr("game_ai_editor.vision.prefilter.probe_media", lambda path: FakeMetadata())
    monkeypatch.setattr(
        "game_ai_editor.vision.prefilter._read_low_res_video",
        lambda *args, **kwargs: (
            [calm, active, calm, calm, calm, active],
            0.1,
            {"command": [], "startup_time_ms": 1, "runtime_time_ms": 2, "frame_count": 6, "ffmpeg_calls": 1},
        ),
    )
    monkeypatch.setattr(
        "game_ai_editor.vision.prefilter._read_audio_rms",
        lambda *args, **kwargs: (
            [0.1, 0.2, 0.1],
            {"command": [], "startup_time_ms": 1, "runtime_time_ms": 2, "ffmpeg_calls": 1, "available": True},
        ),
    )

    report = analyze_prefilter("input/test.mp4", window_size=15, threshold=0.4)
    assert all(0.0 <= item["score"] <= 1.0 for item in report["windows"])
    assert report["candidates"]
    assert report["candidates"][0]["score"] >= 0.4
    assert report["candidates"][0]["score"] >= report["candidates"][-1]["score"]


def test_prefilter_empty_candidates_and_last_partial_window(monkeypatch) -> None:
    class FakeMetadata:
        duration = 7.0

    frame = np.zeros((36, 64), dtype="uint8")
    monkeypatch.setattr("game_ai_editor.vision.prefilter.probe_media", lambda path: FakeMetadata())
    monkeypatch.setattr(
        "game_ai_editor.vision.prefilter._read_low_res_video",
        lambda *args, **kwargs: (
            [frame, frame],
            0.01,
            {"command": [], "startup_time_ms": 1, "runtime_time_ms": 2, "frame_count": 2, "ffmpeg_calls": 1},
        ),
    )
    monkeypatch.setattr(
        "game_ai_editor.vision.prefilter._read_audio_rms",
        lambda *args, **kwargs: (
            [0.0],
            {"command": [], "startup_time_ms": 1, "runtime_time_ms": 2, "ffmpeg_calls": 1, "available": False},
        ),
    )

    report = analyze_prefilter("input/test.mp4", window_size=15, threshold=0.4)
    assert report["windows"] == [{"start": 0.0, "end": 7.0, "score": 0.0, "reasons": []}]
    assert report["candidates"] == []
