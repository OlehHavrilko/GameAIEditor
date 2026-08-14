from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VisionRequest(BaseModel):
    scene_id: str
    video_path: str
    frame_paths: list[str]
    start_time: float
    end_time: float
    prompt_version: str = "arma-reforger-v1"
    prompt: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class VisionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str
    confidence: float = Field(ge=0.0, le=1.0)
    intensity: float = Field(ge=0.0, le=1.0)
    description: str = ""


class VisionAnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_type: str = "other"
    highlight: bool = False
    highlight_score: float = Field(default=0.0, ge=0.0, le=100.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    player_visible: bool = False
    enemy_visible: bool = False
    weapon_visible: bool = False
    muzzle_flash: bool = False
    explosion_visible: bool = False
    multiple_enemies: bool = False
    vehicle_visible: bool = False
    events: list[VisionEvent] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    description: str = ""


class VisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    model: str
    scene_id: str
    start_time: float
    end_time: float
    scene_type: str
    highlight: bool
    highlight_score: float = Field(ge=0.0, le=100.0)
    confidence: float = Field(ge=0.0, le=1.0)
    player_visible: bool = False
    enemy_visible: bool = False
    weapon_visible: bool = False
    muzzle_flash: bool = False
    explosion_visible: bool = False
    multiple_enemies: bool = False
    vehicle_visible: bool = False
    events: list[VisionEvent] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    description: str = ""
    frame_count: int = Field(ge=0)
    frame_dimensions: list[dict[str, int]] = Field(default_factory=list)
    extraction_time_seconds: float = Field(ge=0.0)
    inference_time_seconds: float = Field(ge=0.0)
    total_time_seconds: float = Field(ge=0.0)
    response_size_bytes: int = Field(ge=0)

    @classmethod
    def from_model_payload(
        cls,
        payload: dict[str, Any],
        request: VisionRequest,
        *,
        provider: str = "ollama",
        model: str = "qwen3-vl:8b-instruct",
        frame_dimensions: list[dict[str, int]],
        extraction_time_seconds: float,
        inference_time_seconds: float,
        total_time_seconds: float,
        response_size_bytes: int,
    ) -> "VisionResult":
        analysis = VisionAnalysisPayload.model_validate(payload)
        return cls(
            provider=provider,
            model=model,
            scene_id=request.scene_id,
            start_time=request.start_time,
            end_time=request.end_time,
            frame_count=len(request.frame_paths),
            frame_dimensions=frame_dimensions,
            extraction_time_seconds=extraction_time_seconds,
            inference_time_seconds=inference_time_seconds,
            total_time_seconds=total_time_seconds,
            response_size_bytes=response_size_bytes,
            **analysis.model_dump(),
        )
