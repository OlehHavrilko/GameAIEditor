from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .arcs import build_event_arcs, classify_event_quality


_CONTEXT_SCORES = {
    "movement": 5.0,
    "walking": 5.0,
    "running": 5.0,
    "approach": 80.0,
    "preparation": 75.0,
    "enemy_contact": 85.0,
    "ambush": 75.0,
    "firefight": 60.0,
    "shooting": 60.0,
    "hit": 45.0,
    "kill": 30.0,
    "multiple_kills": 30.0,
    "explosion": 35.0,
    "grenade": 35.0,
    "vehicle_combat": 55.0,
    "close_call": 65.0,
    "objective_under_fire": 65.0,
}


class VisionEventAdapterError(ValueError):
    pass


def load_vision_result(path: str | Path) -> dict[str, Any]:
    result_path = Path(path)
    if not result_path.exists():
        raise FileNotFoundError(f"Vision result not found: {result_path}")
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VisionEventAdapterError(f"Invalid Vision result JSON: {result_path}") from exc
    if not isinstance(payload, dict):
        raise VisionEventAdapterError("Vision result must be a JSON object.")
    return payload


def vision_result_to_events(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    required = ["start_time", "end_time", "highlight_score", "confidence", "events"]
    missing = [field for field in required if field not in payload]
    if missing:
        return [], missing
    if not isinstance(payload["events"], list):
        return [], ["events"]

    start = float(payload["start_time"])
    end = float(payload["end_time"])
    overall_score = max(0.0, min(100.0, float(payload["highlight_score"])))
    converted: list[dict[str, Any]] = []
    for index, vision_event in enumerate(payload["events"]):
        if not isinstance(vision_event, dict) or "event_type" not in vision_event:
            continue
        event_type = str(vision_event["event_type"]).casefold()
        intensity = max(0.0, min(1.0, float(vision_event.get("intensity", 0.0))))
        confidence = max(0.0, min(1.0, float(vision_event.get("confidence", payload["confidence"]))))
        event_score = overall_score if len(payload["events"]) == 1 else overall_score * (0.7 + 0.3 * intensity)
        context_score = _CONTEXT_SCORES.get(event_type, 50.0 if event_score >= 40.0 else 20.0)
        converted.append({
            "event_id": f"{payload.get('scene_id', 'vision')}_event_{index:03d}",
            "event_type": event_type,
            "start": start,
            "end": end,
            "highlight_score": round(event_score, 3),
            "context_score": context_score,
            "confidence": confidence,
            "intensity": intensity,
            "quality": classify_event_quality(event_type, event_score),
            "description": str(vision_event.get("description", "")),
        })
    return converted, []


def build_arcs_from_vision_result(
    payload: dict[str, Any],
    *,
    max_pre_context: float = 15.0,
    max_post_context: float = 8.0,
) -> dict[str, Any]:
    events, missing = vision_result_to_events(payload)
    if missing:
        return {
            "events": [],
            "arcs": [],
            "missing_fields": missing,
            "error": "Vision result is missing required fields.",
        }
    return {
        "events": events,
        "arcs": build_event_arcs(
            events,
            max_pre_context=max_pre_context,
            max_post_context=max_post_context,
        ),
        "missing_fields": [],
    }


def run_event_test(vision_result_path: str | Path) -> dict[str, Any]:
    result_path = Path(vision_result_path)
    payload = load_vision_result(result_path)
    output = build_arcs_from_vision_result(payload)
    arcs_path = result_path.parent / "arcs.json"
    arcs_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return {**output, "arcs_path": str(arcs_path)}
