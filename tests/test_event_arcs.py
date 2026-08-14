from __future__ import annotations

from game_ai_editor.events.arcs import build_event_arcs


def event(event_type: str, start: float, end: float, highlight: float, context: float) -> dict:
    return {
        "event_type": event_type,
        "start": start,
        "end": end,
        "highlight_score": highlight,
        "context_score": context,
    }


def test_long_running_before_kill_is_bounded() -> None:
    arcs = build_event_arcs([
        event("movement", 270, 299, 5, 5),
        event("kill", 300, 301, 95, 30),
    ])
    assert arcs[0]["clip"]["start"] == 296.0
    assert arcs[0]["clip"]["end"] == 304.0


def test_short_approach_before_firefight_is_included() -> None:
    arcs = build_event_arcs([
        event("approach", 98, 100, 15, 80),
        event("firefight", 100, 104, 80, 60),
    ])
    assert arcs[0]["clip"]["start"] == 98.0
    assert arcs[0]["arc"]["action_start"] == 100.0


def test_boring_movement_does_not_become_context() -> None:
    arcs = build_event_arcs([
        event("movement", 270, 299, 5, 5),
        event("kill", 300, 301, 95, 30),
    ], max_pre_context=15)
    assert arcs[0]["clip"]["start"] >= 296.0


def test_multiple_close_kills_form_one_arc() -> None:
    arcs = build_event_arcs([
        event("kill", 100, 101, 90, 30),
        event("kill", 106, 107, 88, 30),
        event("kill", 111, 112, 94, 30),
    ])
    assert len(arcs) == 1
    assert arcs[0]["event_type"] == "multiple_kills"
    assert arcs[0]["arc"]["peak_start"] == 111.0


def test_isolated_kill_has_short_context() -> None:
    arcs = build_event_arcs([event("kill", 300, 301, 95, 30)])
    assert arcs[0]["clip"] == {"start": 296.0, "end": 304.0}


def test_ambush_keeps_long_setup_context() -> None:
    arcs = build_event_arcs([
        event("approach", 288, 296, 15, 82),
        event("ambush", 300, 302, 90, 70),
    ])
    assert arcs[0]["clip"]["start"] == 288.0
    assert arcs[0]["event_type"] == "ambush"


def test_aftermath_is_kept_when_semantically_marked() -> None:
    arcs = build_event_arcs([
        event("kill", 300, 301, 95, 30),
        event("aftermath", 302, 305, 10, 55),
    ])
    assert arcs[0]["arc"]["aftermath_end"] == 305.0
