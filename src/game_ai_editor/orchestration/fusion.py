from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from game_ai_editor.events.arcs import classify_event_quality

from .models import NormalizedEvent


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bounds(event: dict[str, Any]) -> tuple[float, float]:
    start = _number(event.get("start_time", event.get("start", 0.0)))
    end = _number(event.get("end_time", event.get("end", start)))
    return start, max(start, end)


def _normalise_event(event: dict[str, Any], source: str, index: int) -> NormalizedEvent:
    start, end = _bounds(event)
    event_type = str(event.get("event_type", "event")).casefold()
    score = _number(event.get("highlight_score", event.get("score", 0.0)))
    confidence = _number(event.get("confidence", 0.0))
    intensity = _number(event.get("intensity", event.get("visual_intensity", 0.0)))
    quality = str(event.get("quality") or classify_event_quality(event_type, score))
    event_id = str(event.get("event_id", event.get("id", f"{source}_event_{index:04d}")))
    features = {
        key: value
        for key, value in event.items()
        if key not in {
            "event_id", "id", "event_type", "start", "end", "start_time", "end_time",
            "highlight_score", "score", "context_score", "confidence", "intensity", "quality",
        }
    }
    return NormalizedEvent(
        event_id=event_id,
        event_type=event_type,
        start_time=start,
        end_time=end,
        highlight_score=score,
        context_score=_number(event.get("context_score", 0.0)),
        confidence=confidence,
        intensity=intensity,
        quality=quality,
        sources=[source],
        signal_ids=[event_id],
        features=features,
    )


def normalize_events(events: Iterable[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    return [_normalise_event(event, source, index).as_dict() for index, event in enumerate(events)]


def _compatible(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_type = str(left.get("event_type", "event"))
    right_type = str(right.get("event_type", "event"))
    if left_type == right_type:
        return True
    compatible_groups = [
        {
            "enemy_contact", "ambush", "approach", "detection", "shooting", "firefight",
            "hit", "kill", "multiple_kills", "explosion", "grenade", "vehicle_combat",
        },
        {"movement", "walking", "running", "preparation"},
    ]
    return any(left_type in group and right_type in group for group in compatible_groups)


def _overlap(left: dict[str, Any], right: dict[str, Any], tolerance: float) -> bool:
    left_start, left_end = _bounds(left)
    right_start, right_end = _bounds(right)
    return left_start <= right_end + tolerance and right_start <= left_end + tolerance


def fuse_events(events: Iterable[dict[str, Any]], overlap_tolerance: float = 1.0) -> list[dict[str, Any]]:
    fused: list[dict[str, Any]] = []
    for candidate in sorted(events, key=lambda item: _bounds(item)[0]):
        match = next(
            (item for item in fused if _overlap(item, candidate, overlap_tolerance) and _compatible(item, candidate)),
            None,
        )
        if match is None:
            fused.append(dict(candidate))
            continue
        start, end = _bounds(match)
        candidate_start, candidate_end = _bounds(candidate)
        match["start_time"] = min(start, candidate_start)
        match["end_time"] = max(end, candidate_end)
        match["highlight_score"] = max(_number(match.get("highlight_score")), _number(candidate.get("highlight_score")))
        match["context_score"] = max(_number(match.get("context_score")), _number(candidate.get("context_score")))
        match["confidence"] = max(_number(match.get("confidence")), _number(candidate.get("confidence")))
        match["intensity"] = max(_number(match.get("intensity")), _number(candidate.get("intensity")))
        match["sources"] = sorted(set(match.get("sources", [])) | set(candidate.get("sources", [])))
        match["signal_ids"] = sorted(set(match.get("signal_ids", [])) | set(candidate.get("signal_ids", [])))
        match["quality"] = classify_event_quality(str(match.get("event_type", "event")), _number(match.get("highlight_score")))
        for key in ("audio_intensity", "visual_intensity", "speech_reaction", "narrative_value", "kill_count"):
            if key in candidate:
                match[key] = max(_number(match.get(key)), _number(candidate.get(key)))
    return fused