from __future__ import annotations

from typing import Any


def build_timeline(selection: list[dict], duration: float, profile: Any) -> list[dict]:
    timeline: list[dict] = []
    scene_defaults = profile.scene_model
    for index, segment in enumerate(sorted(selection, key=lambda item: float(item.get("start_time", 0.0)))):
        event_type = str(segment.get("event_type", "default"))
        score = float(segment.get("score", 0.0))

        pre_roll = float(scene_defaults.get("default_pre_roll_seconds", 1.0))
        post_roll = float(scene_defaults.get("default_post_roll_seconds", 1.2))
        if score >= 0.75:
            pre_roll = max(pre_roll, float(scene_defaults.get("high_importance_pre_roll_seconds", 2.5)))
            post_roll = max(post_roll, float(scene_defaults.get("high_importance_post_roll_seconds", 2.0)))
        if event_type in {"multi_kill", "explosion"}:
            pre_roll = max(pre_roll, 1.5)
            post_roll = max(post_roll, 1.8)

        start = max(0.0, float(segment.get("start_time", 0.0)) - pre_roll)
        end = min(float(duration), float(segment.get("end_time", duration)) + post_roll)

        timeline.append(
            {
                "id": f"segment_{index:03d}",
                "event_type": event_type,
                "start_time": round(start, 3),
                "end_time": round(end, 3),
                "pre_roll_seconds": round(pre_roll, 3),
                "post_roll_seconds": round(post_roll, 3),
                "score": round(score, 4),
                "confidence": round(float(segment.get("confidence", 0.0)), 3),
            }
        )

    return timeline
