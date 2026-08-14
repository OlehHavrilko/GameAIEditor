from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ArcStages(BaseModel):
    model_config = ConfigDict(extra="forbid")
    setup_start: float
    contact_start: float | None = None
    action_start: float | None = None
    peak_start: float
    peak_end: float
    aftermath_end: float


class ClipBounds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: float
    end: float


class EventArc(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str
    event_type: str
    highlight_score: float = Field(ge=0.0, le=100.0)
    context_score: float = Field(ge=0.0, le=100.0)
    quality: str
    arc: ArcStages
    clip: ClipBounds


_BORING_TYPES = {
    "movement",
    "walking",
    "running",
    "normal_driving",
    "waiting",
    "empty",
}
_CONTACT_TYPES = {"enemy_contact", "ambush", "contact", "detection"}
_ACTION_TYPES = {"firefight", "shooting", "hit", "suppression", "action", "intense_action"}
_AFTERMATH_TYPES = {"aftermath", "reaction", "reload", "resolution", "retreat"}


def _score(event: dict[str, Any], name: str) -> float:
    try:
        return max(0.0, min(100.0, float(event.get(name, 0.0))))
    except (TypeError, ValueError):
        return 0.0


def _time(event: dict[str, Any], name: str) -> float:
    try:
        return float(event.get(name, 0.0))
    except (TypeError, ValueError):
        return 0.0


def _event_end(event: dict[str, Any]) -> float:
    return max(_time(event, "end"), _time(event, "start"))


def _is_meaningful_context(event: dict[str, Any]) -> bool:
    event_type = str(event.get("event_type", "")).casefold()
    return (
        _score(event, "context_score") >= 40.0
        or event_type not in _BORING_TYPES
        and _score(event, "highlight_score") >= 25.0
    )


def _group_events(events: list[dict[str, Any]], grouping_gap: float) -> list[list[dict[str, Any]]]:
    meaningful = [
        event for event in events
        if str(event.get("event_type", "")).casefold() not in _BORING_TYPES
        and str(event.get("event_type", "")).casefold() not in _AFTERMATH_TYPES
        and (
            _score(event, "highlight_score") >= 40.0
            or str(event.get("event_type", "")).casefold() in _CONTACT_TYPES
            or str(event.get("event_type", "")).casefold() in _ACTION_TYPES
        )
    ]
    ordered = sorted(meaningful, key=lambda item: _time(item, "start"))
    groups: list[list[dict[str, Any]]] = []
    for event in ordered:
        if not groups or _time(event, "start") - _event_end(groups[-1][-1]) > grouping_gap:
            groups.append([event])
        else:
            groups[-1].append(event)
    return groups


def _default_pre_context(event_type: str) -> float:
    return 12.0 if event_type == "ambush" else 4.0


def _default_post_context(event_type: str) -> float:
    return 3.0 if event_type in {"kill", "multiple_kills", "ambush"} else 1.5


def classify_event_quality(event_type: str, highlight_score: float) -> str:
    normalized_type = event_type.casefold()
    if normalized_type in _BORING_TYPES and highlight_score < 20.0:
        return "reject"
    if highlight_score < 40.0:
        return "context_only"
    if highlight_score >= 80.0 or normalized_type in {
        "kill",
        "multiple_kills",
        "explosion",
        "vehicle_explosion",
        "ambush",
    }:
        return "major_highlight"
    return "highlight"


def _build_arc(
    group: list[dict[str, Any]],
    all_events: list[dict[str, Any]],
    *,
    max_pre_context: float,
    max_post_context: float,
    arc_index: int,
) -> EventArc:
    peak_event = max(group, key=lambda item: _score(item, "highlight_score"))
    peak_start = _time(peak_event, "start")
    peak_end = _event_end(peak_event)
    group_start = min(_time(event, "start") for event in group)
    group_end = max(_event_end(event) for event in group)

    kill_events = [
        event for event in group
        if str(event.get("event_type", "")).casefold() in {"kill", "headshot"}
    ]
    if len(kill_events) >= 2:
        event_type = "multiple_kills"
    else:
        event_type = str(peak_event.get("event_type", "event"))

    prior = [
        event for event in all_events
        if _time(event, "start") < group_start
        and group_start - _event_end(event) <= max_pre_context
        and _is_meaningful_context(event)
    ]
    setup_start = group_start - min(max_pre_context, _default_pre_context(event_type))
    if event_type == "ambush":
        setup_start = group_start - max_pre_context
    if prior:
        setup_start = min(_time(event, "start") for event in prior)

    contact_events = [
        event for event in group
        if str(event.get("event_type", "")).casefold() in _CONTACT_TYPES
    ]
    action_events = [
        event for event in group
        if str(event.get("event_type", "")).casefold() in _ACTION_TYPES
    ]
    contact_start = min((_time(event, "start") for event in contact_events), default=None)
    action_start = min((_time(event, "start") for event in action_events), default=None)

    following = [
        event for event in all_events
        if _time(event, "start") >= group_end
        and _time(event, "start") - group_end <= max_post_context
        and str(event.get("event_type", "")).casefold() in _AFTERMATH_TYPES
    ]
    aftermath_end = group_end + min(max_post_context, _default_post_context(event_type))
    if following:
        aftermath_end = min(max_post_context + group_end, max(_event_end(event) for event in following))

    return EventArc(
        event_id=f"arc_{arc_index:03d}",
        event_type=event_type,
        highlight_score=max(_score(event, "highlight_score") for event in group),
        context_score=max(_score(event, "context_score") for event in group),
        quality=classify_event_quality(
            event_type,
            max(_score(event, "highlight_score") for event in group),
        ),
        arc=ArcStages(
            setup_start=round(max(0.0, setup_start), 3),
            contact_start=round(contact_start, 3) if contact_start is not None else None,
            action_start=round(action_start, 3) if action_start is not None else None,
            peak_start=round(peak_start, 3),
            peak_end=round(peak_end, 3),
            aftermath_end=round(aftermath_end, 3),
        ),
        clip=ClipBounds(
            start=round(max(0.0, setup_start), 3),
            end=round(aftermath_end, 3),
        ),
    )


def build_event_arcs(
    events: list[dict[str, Any]],
    *,
    max_pre_context: float = 15.0,
    max_post_context: float = 8.0,
    grouping_gap: float = 6.0,
) -> list[dict[str, Any]]:
    if max_pre_context < 0 or max_post_context < 0:
        raise ValueError("Context limits must not be negative")
    groups = _group_events(events, grouping_gap)
    arcs = [
        _build_arc(
            group,
            events,
            max_pre_context=max_pre_context,
            max_post_context=max_post_context,
            arc_index=index,
        ).model_dump()
        for index, group in enumerate(groups)
    ]
    return sorted(arcs, key=lambda item: item["clip"]["start"])
