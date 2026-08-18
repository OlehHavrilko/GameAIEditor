from __future__ import annotations

from typing import Any


def _segments_overlap(left: dict[str, Any], right: dict[str, Any], min_gap_seconds: float) -> bool:
    left_start = float(left.get("start_time", 0.0))
    left_end = float(left.get("end_time", 0.0))
    right_start = float(right.get("start_time", 0.0))
    right_end = float(right.get("end_time", 0.0))
    return not (left_end + min_gap_seconds < right_start or right_end + min_gap_seconds < left_start)


def select_highlights(
    candidates: list[dict[str, Any]],
    profile: Any,
    max_count: int = 5,
    target_duration: float | None = None,
) -> list[dict[str, Any]]:
    gap_seconds = float(profile.scene_model.get("minimum_event_gap_seconds", 1.5))
    ignored = {str(value).casefold() for value in profile.ignored_events}
    ranked = sorted(
        (
            candidate
            for candidate in candidates
            if str(candidate.get("quality", "")).casefold() != "reject"
            and not (
                str(candidate.get("event_type", "")).casefold() in ignored
                and float(candidate.get("context_score", 0.0)) < 40.0
            )
        ),
        key=lambda item: float(item.get("score", 0.0)),
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    total_duration = 0.0

    for candidate in ranked:
        if len(selected) >= max_count:
            break
        if any(_segments_overlap(candidate, selected_item, gap_seconds) for selected_item in selected):
            continue
        candidate_duration = max(
            0.0,
            float(candidate.get("end_time", 0.0)) - float(candidate.get("start_time", 0.0)),
        )
        if target_duration is not None and selected and total_duration + candidate_duration > target_duration:
            continue
        selected.append(candidate)
        total_duration += candidate_duration

    return selected
