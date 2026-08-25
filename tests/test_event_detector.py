from __future__ import annotations

from pathlib import Path

from game_ai_editor.config.loader import load_game_profile
from game_ai_editor.events.detector import detect_events
from game_ai_editor.media.metadata import MediaMetadata

PROFILE_PATH = Path(__file__).resolve().parents[1] / "config/games/arma_reforger.json"


def _metadata(duration: float = 20.0) -> MediaMetadata:
    return MediaMetadata(source_path="synthetic.mp4", duration=duration, video_stream=True, audio_stream=True)


def _motion_spike(time: float, score: float = 0.9, peak: float = 1.0) -> dict:
    samples = [{"time": round(t, 1), "score": 0.05} for t in [time - 0.5, time - 0.2]]
    samples.append({"time": round(time, 1), "score": score})
    samples += [{"time": round(t, 1), "score": 0.05} for t in [time + 0.2, time + 0.5]]
    return {"samples": samples, "peak_motion": peak}


def _audio_quiet() -> dict:
    return {"segments": [{"time": 0.0, "intensity": 0.02}]}


def _transcript(text: str, start: float, end: float) -> dict:
    return {"segments": [{"start": start, "end": end, "text": text}]}


def test_headshot_keyword_overrides_generic_kill_classification() -> None:
    profile = load_game_profile(PROFILE_PATH)
    events = detect_events(
        _metadata(),
        _audio_quiet(),
        _motion_spike(10.0),
        _transcript("nice headshot!", 9.8, 10.5),
        profile,
    )
    assert events
    assert events[0]["event_type"] == "headshot"


def test_squad_coordination_keyword_is_detected() -> None:
    profile = load_game_profile(PROFILE_PATH)
    events = detect_events(
        _metadata(),
        _audio_quiet(),
        _motion_spike(10.0, score=0.6),
        _transcript("cover me, go go go", 9.5, 11.0),
        profile,
    )
    assert events
    assert events[0]["event_type"] == "squad_coordination"


def test_repeated_kill_mentions_become_multi_kill() -> None:
    profile = load_game_profile(PROFILE_PATH)
    events = detect_events(
        _metadata(),
        _audio_quiet(),
        _motion_spike(10.0),
        _transcript("kill one, another kill, that's a kill too", 9.5, 11.0),
        profile,
    )
    assert events
    assert events[0]["event_type"] == "multi_kill"
    assert events[0]["kill_count"] >= 2


def test_no_transcript_falls_back_to_motion_heuristic() -> None:
    profile = load_game_profile(PROFILE_PATH)
    events = detect_events(
        _metadata(),
        _audio_quiet(),
        _motion_spike(10.0),
        {"segments": []},
        profile,
    )
    assert events
    assert events[0]["event_type"] == "kill"
