from __future__ import annotations

from typing import Any


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def score_event(event: dict[str, Any], profile: Any) -> float:
    weights = profile.scoring_weights.model_dump()
    intensity = _as_float(event.get("intensity", 0.0))
    kills = _as_float(event.get("kill_count", 0.0))
    rarity = _as_float(event.get("rarity", 0.0))
    audio_intensity = _as_float(event.get("audio_intensity", 0.0))
    speech_reaction = _as_float(event.get("speech_reaction", 0.0))
    visual_intensity = _as_float(event.get("visual_intensity", 0.0))
    narrative_value = _as_float(event.get("narrative_value", 0.0))
    novelty = _as_float(event.get("novelty", 0.0))
    confidence = _as_float(event.get("confidence", 0.0))

    score = (
        weights["intensity"] * intensity
        + weights["kills"] * min(1.0, kills)
        + weights["rarity"] * rarity
        + weights["audio_intensity"] * audio_intensity
        + weights["speech_reaction"] * speech_reaction
        + weights["visual_intensity"] * visual_intensity
        + weights["narrative_value"] * narrative_value
        + weights["novelty"] * novelty
        + weights["confidence"] * confidence
    )
    return round(float(score), 4)


def score_candidates(events: list[dict[str, Any]], profile: Any) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for event in events:
        candidate = dict(event)
        candidate["score"] = score_event(candidate, profile)
        scored.append(candidate)
    return sorted(scored, key=lambda item: float(item.get("score", 0.0)), reverse=True)
