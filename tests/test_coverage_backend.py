from __future__ import annotations

from game_ai_editor.config.models import GameProfile, ScoringWeights, VisionConfig
from game_ai_editor.selection.selector import select_highlights
from game_ai_editor.vision.factory import create_vision_provider


def _profile() -> GameProfile:
    return GameProfile(
        game_id="test",
        title="Test",
        scoring_weights=ScoringWeights(),
        vision=VisionConfig(),
    )


def test_create_provider_from_dict_ollama():
    provider = create_vision_provider({"provider": "ollama", "base_url": "http://x", "model": "m"})
    assert provider.__class__.__name__ == "OllamaVisionProvider"


def test_create_provider_from_dict_openai_compatible():
    provider = create_vision_provider({"provider": "openrouter", "base_url": "http://x", "model": "m"})
    assert provider.__class__.__name__ == "OpenAICompatibleVisionProvider"


def test_create_provider_from_object_config(monkeypatch):
    monkeypatch.setenv("MY_KEY", "secret")
    config = VisionConfig(provider="custom", base_url="http://x", model="m", api_key="${env:MY_KEY}")
    provider = create_vision_provider(config)
    assert provider.api_key == "secret"


def test_create_provider_unsupported():
    try:
        create_vision_provider({"provider": "bogus"})
    except ValueError as exc:
        assert "Unsupported Vision provider" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_select_highlights_respects_max_count():
    profile = _profile()
    candidates = [
        {"start_time": float(i * 10.0), "end_time": float(i * 10.0) + 1.0, "score": float(i), "event_type": "kill"}
        for i in range(5)
    ]
    selected = select_highlights(candidates, profile, max_count=2)
    assert len(selected) == 2
    assert selected[0]["score"] >= selected[1]["score"]


def test_select_highlights_ignores_rejected():
    profile = _profile()
    candidates = [
        {"start_time": 1.0, "end_time": 2.0, "score": 9.0, "event_type": "reject", "quality": "reject"},
        {"start_time": 3.0, "end_time": 4.0, "score": 1.0, "event_type": "kill"},
    ]
    selected = select_highlights(candidates, profile, max_count=5)
    assert len(selected) == 1
    assert selected[0]["event_type"] == "kill"
