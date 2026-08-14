from __future__ import annotations

from typing import Any


def _segments_overlap(left: dict, right: dict, min_gap_seconds: float) -> bool:
    left_start = float(left.get("start_time", 0.0))
    left_end = float(left.get("end_time", 0.0))
    right_start = float(right.get("start_time", 0.0))
    right_end = float(right.get("end_time", 0.0))
    return not (left_end + min_gap_seconds < right_start or right_end + min_gap_seconds < left_start)


def select_highlights(candidates: list[dict], profile: Any, max_count: int = 5) -> list[dict]:
    gap_seconds = float(profile.scene_model.get("minimum_event_gap_seconds", 1.5))
    ranked = sorted(candidates, key=lambda item: float(item.get("score", 0.0)), reverse=True)
    selected: list[dict] = []

    for candidate in ranked:
        if len(selected) >= max_count:
            break
        if any(_segments_overlap(candidate, selected_item, gap_seconds) for selected_item in selected):
            continue
        selected.append(candidate)

    return selected
