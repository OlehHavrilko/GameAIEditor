from __future__ import annotations

from pydantic import BaseModel, Field


class ScoringWeights(BaseModel):
    intensity: float = 0.0
    kills: float = 0.0
    rarity: float = 0.0
    audio_intensity: float = 0.0
    speech_reaction: float = 0.0
    visual_intensity: float = 0.0
    narrative_value: float = 0.0
    novelty: float = 0.0
    confidence: float = 0.0


class GameProfile(BaseModel):
    game_id: str
    title: str
    platform: list[str] = Field(default_factory=list)
    genre: list[str] = Field(default_factory=list)
    description: str = ""
    interesting_events: list[str] = Field(default_factory=list)
    ignored_events: list[str] = Field(default_factory=list)
    scene_model: dict = Field(default_factory=dict)
    scoring_weights: ScoringWeights
    editing_rules: list[dict] = Field(default_factory=list)
    narrative_signals: dict = Field(default_factory=dict)
    vision: dict = Field(default_factory=dict)
