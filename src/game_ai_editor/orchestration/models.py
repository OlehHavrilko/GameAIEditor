from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class StageStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


@dataclass(frozen=True)
class SourceIdentity:
    path: str
    filename: str
    size: int
    mtime_ns: int
    sha256: str | None = None


@dataclass
class NormalizedEvent:
    event_id: str
    event_type: str
    start_time: float
    end_time: float
    highlight_score: float = 0.0
    context_score: float = 0.0
    confidence: float = 0.0
    intensity: float = 0.0
    quality: str = "context_only"
    sources: list[str] = field(default_factory=list)
    signal_ids: list[str] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "start_time": round(max(0.0, self.start_time), 3),
            "end_time": round(max(self.start_time, self.end_time), 3),
            "highlight_score": round(max(0.0, min(100.0, self.highlight_score)), 3),
            "context_score": round(max(0.0, min(100.0, self.context_score)), 3),
            "confidence": round(max(0.0, min(1.0, self.confidence)), 3),
            "intensity": round(max(0.0, min(1.0, self.intensity)), 3),
            "quality": self.quality,
            "sources": sorted(set(self.sources)),
            "signal_ids": sorted(set(self.signal_ids)),
        }
        payload.update(self.features)
        return payload


@dataclass(frozen=True)
class RenderJob:
    source_path: str
    timeline: list[dict[str, Any]]
    output_dir: str
    preview_path: str
    final_path: str
    codec: str = "libx264"
    audio_codec: str = "aac"


@dataclass
class StageState:
    status: StageStatus = StageStatus.NOT_STARTED
    current_stage: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    started_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None