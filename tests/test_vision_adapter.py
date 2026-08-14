from __future__ import annotations

import json
from pathlib import Path

from game_ai_editor.events.vision_adapter import (
    build_arcs_from_vision_result,
    run_event_test,
    vision_result_to_events,
)


def vision_payload(events: list[dict], score: float = 90.0) -> dict:
    return {
        "provider": "ollama",
        "model": "qwen3-vl:8b-instruct",
        "scene_id": "scene_001",
        "start_time": 120.0,
        "end_time": 125.0,
        "highlight_score": score,
        "confidence": 0.9,
        "events": events,
    }


def test_vision_event_converts_to_major_highlight_arc() -> None:
    result = build_arcs_from_vision_result(
        vision_payload([{
            "event_type": "kill",
            "confidence": 0.95,
            "intensity": 1.0,
            "description": "Enemy eliminated.",
        }])
    )
    assert result["events"][0]["quality"] == "major_highlight"
    assert len(result["arcs"]) == 1
    assert result["arcs"][0]["event_type"] == "kill"
    assert result["arcs"][0]["clip"]["start"] == 116.0


def test_quality_classification_reject_context_and_highlight() -> None:
    movement, _ = vision_result_to_events(vision_payload([{
        "event_type": "movement", "confidence": 0.9, "intensity": 0.1,
    }], score=5))
    approach, _ = vision_result_to_events(vision_payload([{
        "event_type": "approach", "confidence": 0.9, "intensity": 0.2,
    }], score=15))
    firefight, _ = vision_result_to_events(vision_payload([{
        "event_type": "firefight", "confidence": 0.9, "intensity": 0.7,
    }], score=70))
    assert movement[0]["quality"] == "reject"
    assert approach[0]["quality"] == "context_only"
    assert firefight[0]["quality"] == "highlight"


def test_multiple_vision_kills_form_one_arc() -> None:
    result = build_arcs_from_vision_result(
        vision_payload([
            {"event_type": "kill", "confidence": 0.9, "intensity": 1.0},
            {"event_type": "kill", "confidence": 0.9, "intensity": 0.95},
        ])
    )
    assert len(result["arcs"]) == 1
    assert result["arcs"][0]["event_type"] == "multiple_kills"
    assert result["arcs"][0]["quality"] == "major_highlight"


def test_missing_vision_fields_are_reported() -> None:
    result = build_arcs_from_vision_result({"scene_id": "incomplete"})
    assert result["arcs"] == []
    assert "start_time" in result["missing_fields"]
    assert result["error"]


def test_event_test_writes_arcs_json(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps(vision_payload([{
            "event_type": "explosion",
            "confidence": 0.9,
            "intensity": 0.9,
        }])),
        encoding="utf-8",
    )
    output = run_event_test(result_path)
    assert output["arcs_path"] == str(tmp_path / "arcs.json")
    assert len(output["arcs"]) == 1
    assert (tmp_path / "arcs.json").exists()
