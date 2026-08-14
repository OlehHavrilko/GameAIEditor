from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from game_ai_editor.analysis.motion import analyze_motion
from game_ai_editor.audio.analysis import analyze_audio
from game_ai_editor.config.loader import load_game_profile
from game_ai_editor.editing.ffmpeg_editor import build_preview, render_final
from game_ai_editor.events.arcs import build_event_arcs
from game_ai_editor.events.detector import detect_events
from game_ai_editor.events.vision_adapter import vision_result_to_events
from game_ai_editor.media.metadata import probe_media
from game_ai_editor.qc.checks import run_qc
from game_ai_editor.scoring.score import score_candidates
from game_ai_editor.selection.selector import select_highlights
from game_ai_editor.timeline.planner import build_timeline
from game_ai_editor.transcription.whisper import transcribe_audio
from game_ai_editor.vision.base import VisionProvider
from game_ai_editor.vision.factory import create_vision_provider
from game_ai_editor.vision.models import VisionRequest
from game_ai_editor.vision.prefilter import run_prefilter
from game_ai_editor.vision.prompts import COARSE_SCAN_PROMPT
from game_ai_editor.vision.sampler import sample_scene_frames

from .fusion import fuse_events, normalize_events
from .models import StageStatus
from .state import STAGES, source_identity, source_matches, utc_now, write_json


ProgressCallback = Callable[[str, str, dict[str, Any]], None]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class ProductionOrchestrator:
    def __init__(
        self,
        *,
        profile: Any,
        vision_provider: VisionProvider | None = None,
        progress: ProgressCallback | None = None,
        resume: bool = True,
    ) -> None:
        self.profile = profile
        self.vision_provider = vision_provider
        self.progress = progress
        self.resume = resume

    @classmethod
    def from_profile_path(
        cls,
        profile_path: str | Path,
        *,
        progress: ProgressCallback | None = None,
        resume: bool = True,
    ) -> "ProductionOrchestrator":
        profile = load_game_profile(profile_path)
        provider = create_vision_provider(profile.vision) if profile.vision.enabled else None
        return cls(profile=profile, vision_provider=provider, progress=progress, resume=resume)

    def _emit(self, stage: str, status: str, **details: Any) -> None:
        if self.progress:
            self.progress(stage, status, details)

    def _status(self, session_dir: Path, **values: Any) -> None:
        path = session_dir / "status.json"
        payload = _read_json(path) if path.exists() else {}
        payload.update(values)
        payload["updated_at"] = utc_now()
        write_json(path, payload)

    def _stage(self, session_dir: Path, stage: str, action: Callable[[], Any]) -> Any:
        self._emit(stage, "START")
        self._status(session_dir, status="RUNNING", current_stage=stage, stage=stage, started_at=utc_now())
        try:
            result = action()
        except Exception as exc:
            self._status(
                session_dir,
                status="FAILED",
                current_stage=stage,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            self._emit(stage, "FAILED", error_type=type(exc).__name__, error_message=str(exc))
            raise
        self._status(session_dir, status="RUNNING", current_stage=stage, completed_stage=stage)
        self._emit(stage, "COMPLETE")
        return result

    def _session_dir(self, video: Path, session_dir: str | Path | None) -> Path:
        if session_dir is not None:
            target = Path(session_dir)
        else:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target = Path("work") / f"{video.stem.replace(' ', '_')}_{stamp}"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _vision_events(self, source: Path, candidates: list[dict[str, Any]], session_dir: Path) -> list[dict[str, Any]]:
        if self.vision_provider is None or not candidates:
            return []
        vision_dir = session_dir / "vision"
        events: list[dict[str, Any]] = []
        max_candidates = self.profile.vision.max_scenes_per_video
        for index, candidate in enumerate(candidates[:max_candidates], start=1):
            result_path = vision_dir / f"window_{index:06d}.json"
            if self.resume and result_path.exists():
                payload = _read_json(result_path)
            else:
                start = float(candidate["start"])
                end = float(candidate["end"])
                frames, extraction_time = sample_scene_frames(
                    source,
                    start,
                    end,
                    max_frames=self.profile.vision.max_frames_per_scene,
                    output_dir=vision_dir / "frames" / f"window_{index:06d}",
                    width=512,
                    height=288,
                )
                request = VisionRequest(
                    scene_id=f"{source.stem}_window_{index:06d}",
                    video_path=str(source),
                    frame_paths=[frame.path for frame in frames],
                    start_time=start,
                    end_time=end,
                    prompt=COARSE_SCAN_PROMPT,
                    context={"prefilter_score": candidate.get("score", 0.0)},
                )
                result = self.vision_provider.analyze(request)
                result.extraction_time_seconds = round(extraction_time, 4)
                result.frame_count = len(frames)
                payload = result.model_dump()
                payload["prefilter_score"] = candidate.get("score", 0.0)
                write_json(result_path, payload)
            converted, missing = vision_result_to_events(payload)
            if missing:
                continue
            events.extend(normalize_events(converted, "vision"))
            self._emit("vision", "PROGRESS", window=index, total=min(len(candidates), max_candidates))
        return events

    def run(
        self,
        video: str | Path,
        *,
        session_dir: str | Path | None = None,
        max_clips: int = 5,
        target_duration: float | None = None,
    ) -> dict[str, Any]:
        source = Path(video).resolve()
        if not source.exists():
            raise FileNotFoundError(f"Input video not found: {source}")
        if max_clips < 1:
            raise ValueError("max_clips must be at least 1")
        session = self._session_dir(source, session_dir)
        identity = source_identity(source)
        existing_status = session / "status.json"
        if self.resume and existing_status.exists():
            existing = _read_json(existing_status)
            if existing.get("source_identity") and not source_matches(existing, identity):
                raise RuntimeError("Session source identity does not match the input video.")
        self._status(session, status="RUNNING", current_stage="metadata", source_identity=identity.__dict__, started_at=utc_now())

        metadata = self._stage(session, "metadata", lambda: probe_media(source))
        write_json(session / "metadata.json", {**metadata.model_dump(), "source_identity": identity.__dict__})
        duration = float(metadata.duration or 0.0)

        prefilter = self._stage(
            session,
            "prefilter",
            lambda: run_prefilter(source, output_dir=session / "prefilter"),
        )
        write_json(session / "prefilter" / "candidates.json", prefilter)

        audio = self._stage(session, "audio", lambda: analyze_audio(source))
        motion = self._stage(session, "motion", lambda: analyze_motion(source))
        transcript = self._stage(session, "transcription", lambda: transcribe_audio(source))
        legacy_events = detect_events(metadata, audio, motion, transcript, self.profile)
        write_json(session / "signals" / "audio.json", audio)
        write_json(session / "signals" / "motion.json", motion)
        write_json(session / "signals" / "transcript.json", transcript)
        normalized_legacy = normalize_events(legacy_events, "legacy")

        vision_events: list[dict[str, Any]] = []
        if self.vision_provider is not None and prefilter.get("candidates"):
            vision_events = self._stage(
                session,
                "vision",
                lambda: self._vision_events(source, prefilter["candidates"], session),
            )
        elif self.vision_provider is not None:
            self._emit("vision", "COMPLETE", windows=0, skipped="no_prefilter_candidates")
        fused = fuse_events(normalized_legacy + vision_events)
        write_json(session / "events.json", {"events": fused, "legacy_count": len(normalized_legacy), "vision_count": len(vision_events)})

        arcs = build_event_arcs(fused)
        write_json(session / "arcs.json", {"arcs": arcs})
        arc_candidates: list[dict[str, Any]] = []
        for arc in arcs:
            candidate = dict(arc)
            candidate["start_time"] = arc["clip"]["start"]
            candidate["end_time"] = arc["clip"]["end"]
            candidate["confidence"] = max(
                (float(event.get("confidence", 0.0)) for event in fused
                 if float(event.get("start_time", 0.0)) <= arc["arc"]["peak_end"]
                 and float(event.get("end_time", 0.0)) >= arc["arc"]["peak_start"]),
                default=0.0,
            )
            candidate["intensity"] = float(candidate["highlight_score"]) / 100.0
            candidate["visual_intensity"] = candidate["intensity"]
            candidate["narrative_value"] = float(candidate["context_score"]) / 100.0
            candidate["audio_intensity"] = max((float(event.get("audio_intensity", 0.0)) for event in fused), default=0.0)
            candidate["speech_reaction"] = max((float(event.get("speech_reaction", 0.0)) for event in fused), default=0.0)
            candidate["kill_count"] = 1 if candidate["event_type"] in {"kill", "multiple_kills", "headshot"} else 0
            arc_candidates.append(candidate)
        scored = score_candidates(arc_candidates, self.profile)
        write_json(session / "ranking.json", {"candidates": scored})
        selected = select_highlights(scored, self.profile, max_count=max_clips)
        if target_duration is not None:
            selected = self._limit_duration(selected, target_duration)
        write_json(session / "selection.json", {"selection": selected, "status": "NO_HIGHLIGHTS" if not selected else "READY"})
        if not selected:
            result = {"status": "NO_HIGHLIGHTS", "session_dir": str(session), "metadata": metadata.model_dump(), "selected": []}
            self._status(session, status="NO_HIGHLIGHTS", current_stage="selection", completed_at=utc_now())
            return result

        timeline = build_timeline(selected, duration, self.profile)
        write_json(session / "timeline.json", {"timeline": timeline})
        output_dir = session / "output"
        preview = build_preview(source, timeline, output_dir / "preview.mp4")
        final = render_final(preview, output_dir / "montage.mp4")
        qc = run_qc(preview, final, source_path=source, timeline=timeline)
        write_json(output_dir / "qc.json", qc)
        status = "SUCCESS" if qc.get("passed") else "QC_FAILED"
        self._status(session, status=status, current_stage="qc", completed_at=utc_now())
        return {
            "status": status,
            "session_dir": str(session),
            "metadata": metadata.model_dump(),
            "events": fused,
            "arcs": arcs,
            "selected": selected,
            "timeline": timeline,
            "final_path": str(final),
            "qc": qc,
        }

    @staticmethod
    def _limit_duration(selection: list[dict[str, Any]], target_duration: float) -> list[dict[str, Any]]:
        if target_duration <= 0:
            return []
        result: list[dict[str, Any]] = []
        total = 0.0
        for item in selection:
            length = max(0.0, float(item.get("end_time", 0.0)) - float(item.get("start_time", 0.0)))
            if result and total + length > target_duration:
                continue
            result.append(item)
            total += length
        return result