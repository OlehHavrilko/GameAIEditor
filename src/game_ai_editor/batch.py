from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from game_ai_editor.media.metadata import probe_media
from game_ai_editor.vision.models import VisionRequest
from game_ai_editor.vision.ollama import OllamaVisionProvider
from game_ai_editor.vision.prefilter import run_prefilter
from game_ai_editor.vision.prompts import COARSE_SCAN_PROMPT
from game_ai_editor.vision.sampler import sample_scene_frames
from game_ai_editor.events.arcs import build_event_arcs
from game_ai_editor.events.vision_adapter import vision_result_to_events
from game_ai_editor.orchestration.orchestrator import ProductionOrchestrator
from game_ai_editor.orchestration.state import STAGES as ORCHESTRATOR_STAGES
from game_ai_editor.orchestration.state import stage_status as orchestration_stage_status
from game_ai_editor.orchestration.state import write_json


SUPPORTED_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm"}
IGNORED_PREFIXES = (".", "~$", "~")
IGNORED_SUFFIXES = (".tmp", ".part", ".partial", ".crdownload", ".download")
IGNORED_DIRECTORIES = {"gameaieditor", "finalvids", "output", "work"}
STAGES = ("metadata", "prefilter", "vision", "refinement", "render")


class BatchError(RuntimeError):
    pass


class BatchExecutionNotImplementedError(BatchError):
    pass


def _is_hidden(path: Path) -> bool:
    if path.name.startswith("."):
        return True
    try:
        import ctypes

        attributes = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        return attributes != -1 and bool(attributes & 0x2)
    except (AttributeError, OSError):
        return False


def discover_videos(input_directory: str | Path) -> list[Path]:
    root = Path(input_directory)
    if not root.exists():
        raise FileNotFoundError(f"Batch input directory not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Batch input path is not a directory: {root}")

    discovered: list[Path] = []
    seen_resolved: set[str] = set()
    for path in sorted(root.rglob("*"), key=lambda item: str(item).casefold()):
        if not path.is_file() or path.suffix.casefold() not in SUPPORTED_EXTENSIONS:
            continue
        if any(part.casefold() in IGNORED_DIRECTORIES | {".git"} for part in path.relative_to(root).parts[:-1]):
            continue
        if _is_hidden(path) or path.name.startswith(IGNORED_PREFIXES):
            continue
        if path.suffix.casefold() in IGNORED_SUFFIXES:
            continue
        resolved = str(path.resolve()).casefold()
        if resolved in seen_resolved:
            continue
        seen_resolved.add(resolved)
        discovered.append(path)
    return discovered


def _safe_video_id(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", path.stem).strip("_") or "video"
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"{stem}_{digest}"


def _batch_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _manifest_paths(work_root: Path, input_directory: Path) -> list[Path]:
    manifests: list[Path] = []
    if not work_root.exists():
        return manifests
    for path in work_root.glob("*/batch.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(Path(payload.get("input_directory", "")).resolve()).casefold() == str(input_directory.resolve()).casefold():
            manifests.append(path)
    return sorted(manifests, key=lambda item: item.stat().st_mtime, reverse=True)


def _stage_status(session_dir: Path) -> dict[str, str]:
    artifacts = {
        "metadata": session_dir / "metadata.json",
        "prefilter": session_dir / "prefilter" / "candidates.json",
        "vision": session_dir / "vision" / "results.json",
        "refinement": session_dir / "events.json",
        "render": session_dir / "final.mp4",
    }
    return {stage: ("completed" if path.exists() else "pending") for stage, path in artifacts.items()}


def next_pending_stage(stages: dict[str, str]) -> str | None:
    for stage in STAGES:
        if stages.get(stage) != "completed":
            return stage
    return None


def build_batch_manifest(
    input_directory: str | Path,
    *,
    work_root: str | Path = "work/batch",
    dry_run: bool = True,
) -> dict[str, Any]:
    root = Path(input_directory)
    videos = discover_videos(root)
    work_path = Path(work_root)
    existing = _manifest_paths(work_path, root)
    if existing:
        manifest_path = existing[0]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        batch_id = str(manifest["batch_id"])
        batch_dir = manifest_path.parent
        created_at = manifest.get("created_at", datetime.now(timezone.utc).isoformat())
    else:
        batch_id = _batch_id()
        batch_dir = work_path / batch_id
        created_at = datetime.now(timezone.utc).isoformat()

    video_entries: list[dict[str, Any]] = []
    total_duration = 0.0
    for video_path in videos:
        video_id = _safe_video_id(video_path)
        session_dir = batch_dir / "sessions" / video_id
        session_dir.mkdir(parents=True, exist_ok=True)
        metadata = probe_media(video_path)
        duration = float(metadata.duration or 0.0)
        total_duration += duration
        (session_dir / "metadata.json").write_text(
            json.dumps(metadata.model_dump(), indent=2), encoding="utf-8"
        )
        stages = _stage_status(session_dir)
        video_entries.append({
            "video_id": video_id,
            "filename": video_path.name,
            "path": str(video_path),
            "duration": duration,
            "session_dir": str(session_dir),
            "status": "ready" if next_pending_stage(stages) else "completed",
            "next_stage": next_pending_stage(stages),
            "stages": stages,
        })

    manifest = {
        "batch_id": batch_id,
        "created_at": created_at,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "input_directory": str(root.resolve()),
        "dry_run": dry_run,
        "status": "planned" if dry_run else "not_started",
        "video_count": len(video_entries),
        "total_duration": round(total_duration, 3),
        "videos": video_entries,
    }
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "batch.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {**manifest, "manifest_path": str(batch_dir / "batch.json"), "batch_dir": str(batch_dir)}


def run_batch(
    input_directory: str | Path,
    *,
    dry_run: bool = False,
    work_root: str | Path = "work/batch",
    clips: int = 10,
    window_size: float = 15.0,
    prefilter_threshold: float = 0.4,
    style: str = "tactical",
    max_videos: int | None = None,
    resume: bool = True,
    final_dir: str | Path = "finalvids",
    profile_path: str | Path = "config/games/arma_reforger.json",
) -> dict[str, Any]:
    manifest = build_batch_manifest(input_directory, work_root=work_root, dry_run=dry_run)
    if dry_run:
        return manifest
    if clips < 1:
        raise ValueError("clips must be at least 1")
    if max_videos is not None and max_videos < 1:
        raise ValueError("max_videos must be at least 1")
    return _run_orchestrated_batch(
        manifest,
        clips=clips,
        window_size=window_size,
        prefilter_threshold=prefilter_threshold,
        style=style,
        max_videos=max_videos,
        resume=resume,
        final_dir=final_dir,
        profile_path=profile_path,
    )


def _run_orchestrated_batch(
    manifest: dict[str, Any],
    *,
    clips: int,
    window_size: float,
    prefilter_threshold: float,
    style: str,
    max_videos: int | None,
    resume: bool,
    final_dir: str | Path,
    profile_path: str | Path,
) -> dict[str, Any]:
    """Run every video through the shared production orchestrator."""
    del window_size, prefilter_threshold, style
    profile_path = Path(profile_path)
    selected_videos = manifest["videos"][:max_videos] if max_videos else manifest["videos"]
    summaries: list[dict[str, Any]] = []
    selected_outputs: list[str] = []
    for index, video in enumerate(selected_videos, start=1):
        session_dir = Path(video["session_dir"])
        try:
            orchestrator = ProductionOrchestrator.from_profile_path(profile_path, resume=resume)
            result = orchestrator.run(video["path"], session_dir=session_dir, max_clips=clips)
            status = result.get("status", "FAILED")
            final_path = result.get("final_path")
            if final_path and Path(final_path).exists():
                target = Path(final_dir) / f"{video['video_id']}.mp4"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(final_path, target)
                selected_outputs.append(str(target))
            video["status"] = status
            video["error_type"] = None
            video["error_message"] = None
            video["stage_status"] = orchestration_stage_status(session_dir)
            video["next_stage"] = next((stage for stage in ORCHESTRATOR_STAGES if video["stage_status"].get(stage) != "COMPLETE"), None)
            summaries.append({
                "video": video["filename"],
                "status": status,
                "events": len(result.get("events", [])),
                "arcs": len(result.get("arcs", [])),
                "selected_clips": len(result.get("selected", [])),
                "final_path": final_path,
            })
        except Exception as exc:
            video["status"] = "FAILED"
            video["error_type"] = type(exc).__name__
            video["error_message"] = str(exc)
            video["stage_status"] = orchestration_stage_status(session_dir)
            summaries.append({
                "video": video["filename"],
                "status": "FAILED",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            })
        manifest["videos"] = [entry for entry in manifest["videos"]]
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_json(manifest["manifest_path"], manifest)
        print(f"[{index}/{len(selected_videos)}] {video['filename']} status={video['status']}")

    successful = [item for item in summaries if item.get("status") == "SUCCESS"]
    manifest["status"] = "completed" if summaries and len(successful) == len(summaries) else "partial" if successful else "failed"
    manifest["production_summary"] = {
        "videos_processed": len(selected_videos),
        "successful_videos": len(successful),
        "failed_videos": len(summaries) - len(successful),
        "selected_clips": sum(item.get("selected_clips", 0) for item in summaries),
    }
    write_json(manifest["manifest_path"], manifest)
    return {
        **manifest,
        "video_summaries": summaries,
        "montage_path": selected_outputs[0] if len(selected_outputs) == 1 else None,
        "qc": {"passed": bool(successful), "videos": summaries},
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _run_candidate_vision(
    video: dict[str, Any],
    candidates: list[dict[str, Any]],
    vision_dir: Path,
    *,
    model: str | None = None,
) -> tuple[list[dict[str, Any]], float]:
    source = Path(video["path"])
    provider = OllamaVisionProvider(model=model) if model else OllamaVisionProvider()
    results: list[dict[str, Any]] = []
    started = time.perf_counter()
    availability_error: str | None = None
    try:
        provider.check_available()
    except Exception as exc:
        availability_error = str(exc)
    for index, candidate in enumerate(candidates, start=1):
        result_path = vision_dir / f"window_{index:04d}.json"
        if result_path.exists():
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    results.append(payload)
                    continue
            except json.JSONDecodeError:
                result_path.unlink(missing_ok=True)

        frame_dir = vision_dir / "frames" / f"window_{index:04d}"
        try:
            if availability_error:
                raise RuntimeError(availability_error)
            frames, extraction_time = sample_scene_frames(
                source,
                float(candidate["start"]),
                float(candidate["end"]),
                max_frames=5,
                output_dir=frame_dir,
                width=512,
                height=288,
            )
            request_data = VisionRequest(
                scene_id=f"{video['video_id']}_window_{index:04d}",
                video_path=str(source),
                frame_paths=[frame.path for frame in frames],
                start_time=float(candidate["start"]),
                end_time=float(candidate["end"]),
                prompt=COARSE_SCAN_PROMPT,
            )
            vision_result = provider.analyze(request_data)
            vision_result.extraction_time_seconds = round(extraction_time, 4)
            vision_result.frame_count = len(frames)
            vision_result.frame_dimensions = [
                {"width": frame.width, "height": frame.height} for frame in frames
            ]
            payload = vision_result.model_dump()
            payload["prefilter_score"] = candidate["score"]
            _write_json(result_path, payload)
            results.append(payload)
        except Exception as exc:
            payload = {
                "scene_id": f"{video['video_id']}_window_{index:04d}",
                "start_time": candidate["start"],
                "end_time": candidate["end"],
                "error": str(exc),
                "events": [],
                "highlight_score": 0.0,
                "confidence": 0.0,
            }
            _write_json(result_path, payload)
            results.append(payload)
    return results, time.perf_counter() - started


def _extract_clip(source: Path, start: float, end: float, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(max(0.0, start)), "-to", str(max(start + 0.5, end)),
        "-i", str(source), "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-movflags", "+faststart", str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Clip extraction failed: {result.stderr.strip()}")


def _render_montage(clip_paths: list[Path], output: Path) -> None:
    if not clip_paths:
        raise RuntimeError("No selected clips available for montage rendering.")
    concat = output.parent / "concat.txt"
    concat.write_text(
        "".join(f"file '{path.relative_to(output.parent).as_posix()}'\n" for path in clip_paths),
        encoding="utf-8",
    )
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(concat),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-movflags", "+faststart", str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Montage rendering failed: {result.stderr.strip()}")


def _run_production_batch(
    manifest: dict[str, Any],
    *,
    clips: int,
    window_size: float,
    prefilter_threshold: float,
    style: str,
    max_videos: int | None,
    resume: bool,
    final_dir: str | Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    selected_videos = manifest["videos"][:max_videos] if max_videos else manifest["videos"]
    global_arcs: list[dict[str, Any]] = []
    global_events: list[dict[str, Any]] = []
    video_summaries: list[dict[str, Any]] = []

    for index, video in enumerate(selected_videos, start=1):
        session_dir = Path(video["session_dir"])
        prefilter_path = session_dir / "prefilter" / "candidates.json"
        vision_dir = session_dir / "vision"
        events_path = session_dir / "events.json"
        arcs_path = session_dir / "arcs.json"
        video_started = time.perf_counter()

        if resume and prefilter_path.exists():
            prefilter = json.loads(prefilter_path.read_text(encoding="utf-8"))
        else:
            prefilter = run_prefilter(
                video["path"],
                window_size=window_size,
                threshold=prefilter_threshold,
                output_dir=prefilter_path.parent,
            )

        vision_results, vision_time = _run_candidate_vision(
            video, prefilter["candidates"], vision_dir
        )
        if resume and events_path.exists() and arcs_path.exists():
            events = json.loads(events_path.read_text(encoding="utf-8"))
            arcs = json.loads(arcs_path.read_text(encoding="utf-8"))
        else:
            events = []
            for result in vision_results:
                converted, _ = vision_result_to_events(result)
                events.extend(converted)
            arcs = build_event_arcs(events)
            _write_json(events_path, {"events": events})
            _write_json(arcs_path, {"arcs": arcs})

        for arc in arcs:
            enriched = dict(arc)
            enriched["source"] = video["filename"]
            enriched["source_path"] = video["path"]
            enriched["video_id"] = video["video_id"]
            global_arcs.append(enriched)
        for event in events:
            enriched_event = dict(event)
            enriched_event["source"] = video["filename"]
            enriched_event["source_path"] = video["path"]
            enriched_event["video_id"] = video["video_id"]
            global_events.append(enriched_event)

        video["stages"] = _stage_status(session_dir)
        video["next_stage"] = next_pending_stage(video["stages"])
        video["status"] = "completed" if video["next_stage"] is None else "ready"

        video_summaries.append({
            "video": video["filename"],
            "duration": video["duration"],
            "prefilter_candidates": len(prefilter["candidates"]),
            "vision_results": len(vision_results),
            "events": len(events),
            "arcs": len(arcs),
            "vision_time_seconds": round(vision_time, 3),
            "prefilter_time_seconds": round(float(prefilter.get("processing_time_seconds", 0.0)), 3),
            "processing_time_seconds": round(time.perf_counter() - video_started, 3),
        })
        print(f"[{index}/{len(selected_videos)}] {video['filename']} "
              f"candidates={len(prefilter['candidates'])} arcs={len(arcs)}")

    ranked = sorted(
        global_arcs,
        key=lambda item: (
            float(item.get("highlight_score", 0.0)),
            float(item.get("context_score", 0.0)),
        ),
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    for arc in ranked:
        if len(selected) >= clips:
            break
        same_source_overlap = any(
            arc["video_id"] == item["video_id"]
            and not (
                arc["clip"]["end"] <= item["clip"]["start"]
                or item["clip"]["end"] <= arc["clip"]["start"]
            )
            for item in selected
        )
        if not same_source_overlap:
            selected.append(arc)

    batch_dir = Path(manifest["batch_dir"])
    global_dir = batch_dir / "global"
    output_dir = batch_dir / "output"
    clip_paths: list[Path] = []
    timeline_clips: list[dict[str, Any]] = []
    for order, arc in enumerate(selected, start=1):
        event_type = re.sub(r"[^A-Za-z0-9_-]+", "_", arc["event_type"])
        clip_path = output_dir / "clips" / f"{order:03d}_{event_type}.mp4"
        _extract_clip(
            Path(arc["source_path"]),
            float(arc["clip"]["start"]),
            float(arc["clip"]["end"]),
            clip_path,
        )
        clip_paths.append(clip_path)
        timeline_clips.append({
            "order": order,
            "source": arc["source"],
            "start": arc["clip"]["start"],
            "end": arc["clip"]["end"],
            "duration": round(arc["clip"]["end"] - arc["clip"]["start"], 3),
            "event_type": arc["event_type"],
            "score": arc["highlight_score"],
            "quality": arc.get("quality"),
        })

    global_dir.mkdir(parents=True, exist_ok=True)
    _write_json(global_dir / "events.json", {"events": global_events})
    _write_json(global_dir / "arcs.json", {"arcs": global_arcs})
    _write_json(global_dir / "ranking.json", {"arcs": ranked, "selected": selected})
    _write_json(global_dir / "timeline.json", {"clips": timeline_clips, "style": style})

    montage_path = Path(final_dir) / "montage.mp4"
    render_started = time.perf_counter()
    _render_montage(clip_paths, montage_path)
    render_time = time.perf_counter() - render_started
    montage_metadata = probe_media(montage_path)
    qc = {
        "passed": bool(montage_path.exists() and montage_metadata.video_stream and (montage_metadata.duration or 0) > 0),
        "montage": montage_metadata.model_dump(),
        "timeline_consistent": all(item["end"] > item["start"] for item in timeline_clips),
        "clip_count": len(clip_paths),
        "warnings": [] if clip_paths else ["No clips selected."],
    }
    _write_json(output_dir / "qc.json", qc)
    manifest["status"] = "completed" if qc["passed"] else "failed"
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    manifest["production_summary"] = {
        "videos_processed": len(selected_videos),
        "candidates": sum(item["prefilter_candidates"] for item in video_summaries),
        "vision_events": sum(item["events"] for item in video_summaries),
        "highlight_arcs": len(global_arcs),
        "selected_clips": len(selected),
        "prefilter_time_seconds": round(sum(item["prefilter_time_seconds"] for item in video_summaries), 3),
        "vision_time_seconds": round(sum(item["vision_time_seconds"] for item in video_summaries), 3),
        "render_time_seconds": round(render_time, 3),
        "total_time_seconds": round(time.perf_counter() - started, 3),
    }
    _write_json(Path(manifest["manifest_path"]), manifest)
    return {
        **manifest,
        "video_summaries": video_summaries,
        "selected": selected,
        "timeline": timeline_clips,
        "montage_path": str(montage_path),
        "qc": qc,
    }
