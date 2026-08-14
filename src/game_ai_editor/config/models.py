from __future__ import annotations

from pydantic import BaseModel, Field


class VisionConfig(BaseModel):
    enabled: bool = False
    provider: str = "ollama"
    base_url: str = "http://localhost:11434"
    model: str = "qwen3-vl:8b-instruct"
    api_key: str | None = None
    timeout: float = 120.0
    request_timeout_seconds: float | None = None
    max_scenes_per_video: int = 12
    max_frames_per_scene: int = 5

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
    vision: VisionConfig = Field(default_factory=VisionConfig)
