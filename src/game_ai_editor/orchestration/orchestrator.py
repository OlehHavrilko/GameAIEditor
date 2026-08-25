from __future__ import annotations

import json
import os
import shutil
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from game_ai_editor.analysis.motion import analyze_motion
from game_ai_editor.audio.analysis import analyze_audio
from game_ai_editor.config.loader import load_game_profile
from game_ai_editor.editing.ffmpeg_editor import ASPECT_RATIO_PRESETS, build_preview, render_final
from game_ai_editor.events.arcs import build_event_arcs
from game_ai_editor.events.detector import detect_events
from game_ai_editor.events.vision_adapter import vision_result_to_events
from game_ai_editor.media.metadata import MediaMetadata, probe_media
from game_ai_editor.qc.checks import run_qc
from game_ai_editor.scoring.score import score_candidates
from game_ai_editor.selection.selector import select_highlights
from game_ai_editor.storage import (
    ensure_project_output_dir,
    project_id_from_source,
)
from game_ai_editor.timeline.planner import build_timeline
from game_ai_editor.transcription.whisper import transcribe_audio
from game_ai_editor.vision.base import VisionProvider
from game_ai_editor.vision.factory import create_vision_provider
from game_ai_editor.vision.models import VisionRequest
from game_ai_editor.vision.ollama import (
    OllamaModelError,
    OllamaUnavailableError,
    OllamaVisionError,
)
from game_ai_editor.vision.prefilter import run_prefilter
from game_ai_editor.vision.prompts import COARSE_SCAN_PROMPT
from game_ai_editor.vision.sampler import sample_scene_frames

from .fusion import fuse_events, normalize_events
from .models import StageStatus
from .state import (
    STAGES,
    configuration_fingerprint,
    initial_stage_statuses,
    source_identity,
    source_matches,
    utc_now,
    write_json,
)

ProgressCallback = Callable[[str, str, dict[str, Any]], None]
CancellationCallback = Callable[[], bool]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_artifact(path: Path, key: str | None = None) -> Any:
    payload = _read_json(path)
    if key is None:
        if not isinstance(payload, dict):
            raise TypeError(f"Artifact must contain an object: {path}")
        return payload
    value = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(value, list):
        raise TypeError(f"Artifact is missing a valid '{key}' field: {path}")
    return value


def _load_prefilter(path: Path) -> dict[str, Any]:
    payload = _load_artifact(path)
    if not isinstance(payload.get("candidates"), list):
        raise TypeError(f"Prefilter artifact is missing candidates: {path}")
    return cast("dict[str, Any]", payload)


def _load_qc(path: Path) -> dict[str, Any]:
    payload = _load_artifact(path)
    if not isinstance(payload.get("passed"), bool) or not isinstance(payload.get("checks"), list):
        raise TypeError(f"QC artifact has an invalid contract: {path}")
    return cast("dict[str, Any]", payload)


class ProductionOrchestrator:
    def __init__(
        self,
        *,
        profile: Any,
        vision_provider: VisionProvider | None = None,
        progress: ProgressCallback | None = None,
        cancellation_requested: CancellationCallback | None = None,
        resume: bool = True,
    ) -> None:
        self.profile = profile
        self.vision_provider = vision_provider
        self.progress = progress
        self.cancellation_requested = cancellation_requested
        self.resume = resume
        self._status_lock = threading.Lock()

    @classmethod
    def from_profile_path(
        cls,
        profile_path: str | Path,
        *,
        progress: ProgressCallback | None = None,
        resume: bool = True,
    ) -> ProductionOrchestrator:
        profile = load_game_profile(profile_path)
        provider = create_vision_provider(profile.vision) if profile.vision.enabled else None
        return cls(profile=profile, vision_provider=provider, progress=progress, resume=resume)

    def _emit(self, stage: str, status: str, **details: Any) -> None:
        if self.progress:
            self.progress(stage, status, details)

    def _check_cancelled(self) -> None:
        if self.cancellation_requested and self.cancellation_requested():
            raise RuntimeError("JOB_CANCELLED")

    def _status(self, session_dir: Path, **values: Any) -> None:
        path = session_dir / "status.json"
        with self._status_lock:
            payload = _read_json(path) if path.exists() else {}
            payload.update(values)
            payload["updated_at"] = utc_now()
            write_json(path, payload)

    def _set_stage_state(self, session_dir: Path, stage: str, status: StageStatus | str, **details: Any) -> None:
        path = session_dir / "status.json"
        with self._status_lock:
            payload = _read_json(path) if path.exists() else {}
            stages = payload.setdefault("stages", {name: {"status": str(StageStatus.NOT_STARTED)} for name in STAGES})
            stage_payload = stages.setdefault(stage, {"status": str(StageStatus.NOT_STARTED)})
            now = utc_now()
            if str(status) == str(StageStatus.RUNNING) and not stage_payload.get("started_at"):
                stage_payload["started_at"] = now
            stage_payload.update(details)
            stage_payload["status"] = str(status)
            stage_payload["updated_at"] = now
            if str(status) in {str(StageStatus.COMPLETE), str(StageStatus.FAILED), str(StageStatus.SKIPPED)}:
                stage_payload["completed_at"] = now
            payload["stages"] = stages
            payload["updated_at"] = now
            payload["current_stage"] = stage
            completed = sum(
                str(item.get("status")) in {str(StageStatus.COMPLETE), str(StageStatus.SKIPPED)}
                for item in stages.values()
            )
            payload["overall_progress"] = round(100.0 * completed / max(1, len(STAGES)), 1)
            write_json(path, payload)

    def _stage(self, session_dir: Path, stage: str, action: Callable[[], Any]) -> Any:
        self._emit(stage, "START")
        self._set_stage_state(session_dir, stage, StageStatus.RUNNING)
        self._status(session_dir, status="RUNNING", current_stage=stage, stage=stage, started_at=utc_now())
        try:
            self._check_cancelled()
            result = action()
        except Exception as exc:
            error_code = self._error_code(exc)
            interrupted = error_code == "JOB_CANCELLED"
            self._set_stage_state(
                session_dir,
                stage,
                StageStatus.PARTIAL if interrupted else StageStatus.FAILED,
                error_code=error_code,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            self._status(
                session_dir,
                status="CANCELLED" if interrupted else "FAILED",
                current_stage=stage,
                error_code=error_code,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            self._emit(stage, "FAILED", error_type=type(exc).__name__, error_message=str(exc))
            raise
        self._set_stage_state(session_dir, stage, StageStatus.COMPLETE)
        self._status(session_dir, status="RUNNING", current_stage=stage, completed_stage=stage)
        self._emit(stage, "COMPLETE")
        return result

    def _stage_cached(
        self,
        session_dir: Path,
        stage: str,
        artifact: Path,
        loader: Callable[[Path], Any],
        action: Callable[[], Any],
    ) -> Any:
        if self.resume and artifact.exists():
            try:
                result = loader(artifact)
                self._set_stage_state(session_dir, stage, StageStatus.COMPLETE, resumed=True)
                self._emit(stage, "RESUMED", artifact=str(artifact))
                return result
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
        return self._stage(session_dir, stage, action)

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if str(exc) == "JOB_CANCELLED":
            return "JOB_CANCELLED"
        if isinstance(exc, OllamaModelError):
            return "VISION_MODEL_MISSING"
        if isinstance(exc, OllamaUnavailableError):
            return "VISION_PROVIDER_OFFLINE"
        if isinstance(exc, TimeoutError):
            return "VISION_TIMEOUT"
        if isinstance(exc, FileNotFoundError):
            return "INVALID_VIDEO"
        code = type(exc).__name__.upper()
        if "FFMPEG" in code:
            return "FFMPEG_ERROR"
        return code

    def _degrade_vision(self, session_dir: Path, exc: Exception) -> None:
        error_code = self._error_code(exc)
        self._set_stage_state(
            session_dir,
            "vision",
            StageStatus.SKIPPED,
            error_code=error_code,
            error_type=type(exc).__name__,
            error_message=str(exc),
            mode="DEGRADED",
        )
        self._status(
            session_dir,
            status="RUNNING",
            degraded_mode=True,
            degraded_reason=error_code,
            vision={
                "enabled": True,
                "mode": "DEGRADED",
                "status": error_code,
                "provider": type(self.vision_provider).__name__ if self.vision_provider else None,
            },
        )
        self._emit("vision", "DEGRADED", error_code=error_code, error_message=str(exc))

    def _session_dir(self, video: Path, session_dir: str | Path | None) -> Path:
        if session_dir is not None:
            target = Path(session_dir)
        else:
            target = Path("work") / "sessions" / project_id_from_source(video)
        target.mkdir(parents=True, exist_ok=True)
        return target

    @staticmethod
    def _invalidate_public_outputs(output_dir: Path, session: Path) -> None:
        current = [output_dir / "final.mp4", output_dir / "preview.mp4"]
        existing = [path for path in current if path.exists()]
        if not existing:
            return
        archive_dir = output_dir / "runs" / session.name
        if archive_dir.exists():
            archive_dir = output_dir / "runs" / f"{session.name}_{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
        archive_dir.mkdir(parents=True, exist_ok=True)
        for path in existing:
            shutil.move(str(path), str(archive_dir / path.name))

    def _vision_events(self, source: Path, candidates: list[dict[str, Any]], session_dir: Path) -> list[dict[str, Any]]:
        if self.vision_provider is None or not candidates:
            return []
        vision_dir = session_dir / "vision"
        events: list[dict[str, Any]] = []
        max_candidates = self.profile.vision.max_scenes_per_video
        for index, candidate in enumerate(candidates[:max_candidates], start=1):
            self._check_cancelled()
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
                self._check_cancelled()
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
        aspect_ratio: str | None = None,
    ) -> dict[str, Any]:
        source = Path(video).resolve()
        if not source.exists():
            raise FileNotFoundError(f"Input video not found: {source}")
        if max_clips < 1:
            raise ValueError("max_clips must be at least 1")
        if aspect_ratio is not None and aspect_ratio not in ASPECT_RATIO_PRESETS:
            raise ValueError(f"Unsupported aspect_ratio {aspect_ratio!r}; expected one of {sorted(ASPECT_RATIO_PRESETS)}")
        session = self._session_dir(source, session_dir)
        project_id = project_id_from_source(source)
        public_output_dir = ensure_project_output_dir(project_id)
        preview_output_path = public_output_dir / "preview.mp4"
        final_output_path = public_output_dir / "final.mp4"
        identity = source_identity(source)
        fingerprint = configuration_fingerprint(
            self.profile, max_clips=max_clips, target_duration=target_duration, aspect_ratio=aspect_ratio
        )
        existing_status = session / "status.json"
        if self.resume and existing_status.exists():
            existing = _read_json(existing_status)
            if existing.get("source_identity") and not source_matches(existing, identity):
                raise RuntimeError("Session source identity does not match the input video.")
            if existing.get("configuration_fingerprint") and existing.get("configuration_fingerprint") != fingerprint:
                raise RuntimeError("Session configuration fingerprint does not match the current analysis settings.")
        existing_payload = _read_json(existing_status) if existing_status.exists() else {}
        self._status(
            session,
            status="RUNNING",
            current_stage="metadata",
            source_identity=identity.__dict__,
            configuration_fingerprint=fingerprint,
            started_at=utc_now(),
            project_id=project_id,
            final_output_path=str(final_output_path),
            preview_output_path=str(preview_output_path),
            output_directory=str(public_output_dir),
            aspect_ratio=aspect_ratio,
            stages=existing_payload.get("stages") or {stage: {"status": status} for stage, status in initial_stage_statuses().items()},
            vision={
                "enabled": self.vision_provider is not None,
                "mode": "FULL" if self.vision_provider is not None else "DISABLED",
                "status": "READY" if self.vision_provider is not None else "DISABLED",
                "provider": type(self.vision_provider).__name__ if self.vision_provider else None,
            },
        )

        metadata = self._stage_cached(
            session,
            "metadata",
            session / "metadata.json",
            lambda path: MediaMetadata.model_validate(_read_json(path)),
            lambda: probe_media(source),
        )
        write_json(session / "metadata.json", {**metadata.model_dump(), "source_identity": identity.__dict__})
        duration = float(metadata.duration or 0.0)

        if self.vision_provider is not None:
            prefilter = self._stage_cached(
                session,
                "prefilter",
                session / "prefilter" / "candidates.json",
                _load_prefilter,
                lambda: run_prefilter(source, output_dir=session / "prefilter"),
            )
            write_json(session / "prefilter" / "candidates.json", prefilter)
        else:
            # Prefilter output only feeds vision-window selection (see the
            # vision_enabled branch below) - skip the extra ffmpeg decode+RMS
            # pass entirely when there is no vision provider to consume it.
            prefilter = {"candidates": [], "windows": []}
            self._set_stage_state(session, "prefilter", StageStatus.SKIPPED, mode="DISABLED", error_code="VISION_DISABLED")

        with ThreadPoolExecutor(max_workers=3) as executor:
            audio_future = executor.submit(
                self._stage_cached, session, "audio", session / "signals" / "audio.json", _load_artifact, lambda: analyze_audio(source)
            )
            motion_future = executor.submit(
                self._stage_cached, session, "motion", session / "signals" / "motion.json", _load_artifact, lambda: analyze_motion(source)
            )
            transcript_future = executor.submit(
                self._stage_cached,
                session,
                "transcription",
                session / "signals" / "transcript.json",
                _load_artifact,
                lambda: transcribe_audio(source),
            )
            audio = audio_future.result()
            motion = motion_future.result()
            transcript = transcript_future.result()
        legacy_events = detect_events(metadata, audio, motion, transcript, self.profile)
        write_json(session / "signals" / "audio.json", audio)
        write_json(session / "signals" / "motion.json", motion)
        write_json(session / "signals" / "transcript.json", transcript)
        normalized_legacy = normalize_events(legacy_events, "legacy")

        vision_events: list[dict[str, Any]] = []
        cached_events_path = session / "events.json"
        cached_events = None
        if self.resume and cached_events_path.exists():
            try:
                cached_events = _read_json(cached_events_path)
            except (OSError, json.JSONDecodeError):
                cached_events = None
        if isinstance(cached_events, dict) and isinstance(cached_events.get("events"), list):
            fused = self._stage_cached(
                session,
                "events",
                cached_events_path,
                lambda path: _load_artifact(path, "events"),
                list,
            )
            self._set_stage_state(session, "vision", StageStatus.COMPLETE if cached_events.get("vision_count", 0) else StageStatus.SKIPPED, resumed=True)
            vision_enabled = False
        else:
            fused = None
            vision_enabled = self.vision_provider is not None
        if vision_enabled:
            checker = getattr(self.vision_provider, "check_available", None)
            if callable(checker):
                try:
                    checker()
                except (OllamaVisionError, OSError, RuntimeError) as exc:
                    self._degrade_vision(session, exc if isinstance(exc, Exception) else RuntimeError(str(exc)))
                    vision_enabled = False
        else:
            self._set_stage_state(session, "vision", StageStatus.SKIPPED, mode="DISABLED", error_code="VISION_DISABLED")

        if vision_enabled and prefilter.get("candidates"):
            try:
                vision_events = self._stage(
                    session,
                    "vision",
                    lambda: self._vision_events(source, prefilter["candidates"], session),
                )
            except (OllamaVisionError, OSError, RuntimeError) as exc:
                if self._error_code(exc) == "JOB_CANCELLED":
                    self._set_stage_state(session, "vision", StageStatus.PARTIAL, error_code="JOB_CANCELLED")
                    self._status(session, status="CANCELLED", current_stage="vision", error_code="JOB_CANCELLED")
                    raise
                self._degrade_vision(session, exc if isinstance(exc, Exception) else RuntimeError(str(exc)))
                vision_events = []
        elif vision_enabled:
            self._set_stage_state(session, "vision", StageStatus.SKIPPED, mode="NO_CANDIDATES", error_code="NO_PREFILTER_CANDIDATES")
            self._emit("vision", "COMPLETE", windows=0, skipped="no_prefilter_candidates")
        if fused is None:
            fused = self._stage(session, "events", lambda: fuse_events(normalized_legacy + vision_events))
            write_json(session / "events.json", {"events": fused, "legacy_count": len(normalized_legacy), "vision_count": len(vision_events)})

        arcs = self._stage_cached(
            session,
            "arcs",
            session / "arcs.json",
            lambda path: _load_artifact(path, "arcs"),
            lambda: build_event_arcs(fused),
        )
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
        scored = self._stage_cached(
            session,
            "scoring",
            session / "ranking.json",
            lambda path: _load_artifact(path, "candidates"),
            lambda: score_candidates(arc_candidates, self.profile),
        )
        write_json(session / "ranking.json", {"candidates": scored})
        selected = self._stage_cached(
            session,
            "selection",
            session / "selection.json",
            lambda path: _load_artifact(path, "selection"),
            lambda: select_highlights(scored, self.profile, max_count=max_clips),
        )
        if target_duration is not None:
            selected = self._limit_duration(selected, target_duration)
        write_json(session / "selection.json", {"selection": selected, "status": "NO_HIGHLIGHTS" if not selected else "READY"})
        if not selected:
            self._invalidate_public_outputs(public_output_dir, session)
            result = {
                "status": "NO_HIGHLIGHTS",
                "session_dir": str(session),
                "metadata": metadata.model_dump(),
                "selected": [],
                "final_output_path": None,
                "preview_output_path": None,
                "output_directory": str(public_output_dir),
            }
            self._set_stage_state(session, "timeline", StageStatus.SKIPPED, error_code="NO_HIGHLIGHTS")
            self._set_stage_state(session, "render", StageStatus.SKIPPED, error_code="NO_HIGHLIGHTS")
            self._set_stage_state(session, "qc", StageStatus.SKIPPED, error_code="NO_HIGHLIGHTS")
            self._status(
                session,
                status="NO_HIGHLIGHTS",
                current_stage="selection",
                completed_at=utc_now(),
                final_output_path=None,
                preview_output_path=None,
                output_directory=str(public_output_dir),
            )
            return result

        timeline = self._stage_cached(
            session,
            "timeline",
            session / "timeline.json",
            lambda path: _load_artifact(path, "timeline"),
            lambda: build_timeline(selected, duration, self.profile),
        )
        write_json(session / "timeline.json", {"timeline": timeline})
        output_dir = session / "output"
        public_preview_path = preview_output_path
        public_final_path = final_output_path

        rendered_new = not (self.resume and public_preview_path.exists() and public_final_path.exists())
        temporary_paths: tuple[Path, Path] | None = None

        def render_action() -> tuple[Path, Path]:
            temporary_preview = public_preview_path.with_name("preview.tmp.mp4")
            temporary_final = public_final_path.with_name("final.tmp.mp4")
            temporary_preview.unlink(missing_ok=True)
            temporary_final.unlink(missing_ok=True)
            try:
                build_preview(source, timeline, temporary_preview, aspect_ratio=aspect_ratio)
                render_final(temporary_preview, temporary_final)
            except Exception:
                temporary_preview.unlink(missing_ok=True)
                temporary_final.unlink(missing_ok=True)
                raise
            return temporary_preview, temporary_final

        if rendered_new:
            temporary_paths = self._stage(session, "render", render_action)
            qc = self._stage(
                session,
                "qc",
                lambda: run_qc(
                    temporary_paths[0],
                    temporary_paths[1],
                    source_path=source,
                    timeline=timeline,
                    expected_audio=bool(metadata.audio_stream),
                ),
            )
            if qc.get("passed"):
                os.replace(temporary_paths[0], public_preview_path)
                os.replace(temporary_paths[1], public_final_path)
            else:
                temporary_paths[0].unlink(missing_ok=True)
                temporary_paths[1].unlink(missing_ok=True)
            final = public_final_path
        else:
            final = public_final_path
            qc = self._stage_cached(
                session,
                "qc",
                output_dir / "qc.json",
                _load_qc,
                lambda: run_qc(
                    public_preview_path,
                    final,
                    source_path=source,
                    timeline=timeline,
                    expected_audio=bool(metadata.audio_stream),
                ),
            )
        write_json(output_dir / "qc.json", qc)
        self._status(
            session,
            status="SUCCESS" if qc.get("passed") else "QC_FAILED",
            current_stage="qc",
            completed_at=utc_now(),
            final_output_path=str(public_final_path),
            preview_output_path=str(public_preview_path),
            output_dir=str(public_output_dir),
            output_directory=str(public_output_dir),
        )
        status = "SUCCESS" if qc.get("passed") else "QC_FAILED"
        return {
            "status": status,
            "session_dir": str(session),
            "metadata": metadata.model_dump(),
            "events": fused,
            "arcs": arcs,
            "selected": selected,
            "timeline": timeline,
            "final_path": str(final),
            "final_output_path": str(final),
            "preview_output_path": str(public_preview_path),
            "output_dir": str(public_output_dir),
            "qc": qc,
        }

    def rerender_selection(
        self,
        video: str | Path,
        session_dir: str | Path,
        selected: list[dict[str, Any]],
        *,
        aspect_ratio: str | None = None,
    ) -> dict[str, Any]:
        source = Path(video).resolve()
        session = Path(session_dir)
        if aspect_ratio is None:
            status_path = session / "status.json"
            if status_path.exists():
                aspect_ratio = _read_json(status_path).get("aspect_ratio")
        project_id = project_id_from_source(source)
        public_output_dir = ensure_project_output_dir(project_id)
        public_preview_path = public_output_dir / "preview.mp4"
        public_final_path = public_output_dir / "final.mp4"
        metadata = MediaMetadata.model_validate(_read_json(session / "metadata.json"))
        write_json(session / "selection.json", {"selection": selected, "status": "NO_HIGHLIGHTS" if not selected else "READY"})
        timeline_path = session / "timeline.json"
        output_dir = session / "output"
        for artifact in (timeline_path, output_dir / "preview.mp4", output_dir / "montage.mp4", output_dir / "qc.json"):
            artifact.unlink(missing_ok=True)
        if not selected:
            self._invalidate_public_outputs(public_output_dir, session)
            self._status(
                session,
                status="NO_HIGHLIGHTS",
                current_stage="selection",
                completed_at=utc_now(),
                final_output_path=None,
                preview_output_path=None,
                output_dir=str(public_output_dir),
                output_directory=str(public_output_dir),
            )
            return {
                "status": "NO_HIGHLIGHTS",
                "session_dir": str(session),
                "selected": [],
                "final_output_path": None,
                "preview_output_path": None,
                "output_directory": str(public_output_dir),
            }
        timeline = build_timeline(selected, float(metadata.duration or 0.0), self.profile)
        write_json(timeline_path, {"timeline": timeline})
        output_dir.mkdir(parents=True, exist_ok=True)
        temporary_preview = public_preview_path.with_name("preview.tmp.mp4")
        temporary_final = public_final_path.with_name("final.tmp.mp4")
        temporary_preview.unlink(missing_ok=True)
        temporary_final.unlink(missing_ok=True)
        try:
            preview = build_preview(source, timeline, temporary_preview, aspect_ratio=aspect_ratio)
            final = render_final(preview, temporary_final)
            qc = run_qc(
                temporary_preview,
                final,
                source_path=source,
                timeline=timeline,
                expected_audio=bool(metadata.audio_stream),
            )
            if qc.get("passed"):
                os.replace(temporary_preview, public_preview_path)
                os.replace(temporary_final, public_final_path)
        except Exception:
            temporary_preview.unlink(missing_ok=True)
            temporary_final.unlink(missing_ok=True)
            raise
        finally:
            temporary_preview.unlink(missing_ok=True)
            temporary_final.unlink(missing_ok=True)
        write_json(output_dir / "qc.json", qc)
        self._status(
            session,
            status="SUCCESS" if qc.get("passed") else "QC_FAILED",
            current_stage="qc",
            completed_at=utc_now(),
            final_output_path=str(public_final_path),
            preview_output_path=str(public_preview_path),
            output_dir=str(public_output_dir),
            output_directory=str(public_output_dir),
        )
        return {
            "status": "SUCCESS" if qc.get("passed") else "QC_FAILED",
            "session_dir": str(session),
            "selected": selected,
            "timeline": timeline,
            "final_path": str(final),
            "final_output_path": str(final),
            "preview_output_path": str(public_preview_path),
            "output_dir": str(public_output_dir),
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