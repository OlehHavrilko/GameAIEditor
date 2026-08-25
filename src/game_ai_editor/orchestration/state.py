from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import SourceIdentity, StageStatus

STAGES = (
    "metadata",
    "prefilter",
    "audio",
    "motion",
    "transcription",
    "vision",
    "events",
    "arcs",
    "scoring",
    "selection",
    "timeline",
    "render",
    "qc",
)


def source_identity(path: str | Path, include_hash: bool = False) -> SourceIdentity:
    source = Path(path).resolve()
    stat = source.stat()
    digest = None
    if include_hash:
        hasher = hashlib.sha256()
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
    return SourceIdentity(str(source), source.name, stat.st_size, stat.st_mtime_ns, digest)


def source_matches(payload: dict[str, Any], identity: SourceIdentity, *, require_hash: bool = False) -> bool:
    stored = payload.get("source_identity", {})
    fast_match = (
        stored.get("filename") == identity.filename
        and int(stored.get("size", -1)) == identity.size
        and int(stored.get("mtime_ns", -1)) == identity.mtime_ns
        and str(Path(stored.get("path", "")).resolve()) == identity.path
    )
    if not fast_match:
        return False
    stored_hash = stored.get("sha256")
    if require_hash or stored_hash is not None:
        return bool(stored_hash and identity.sha256 and stored_hash == identity.sha256)
    return True


def _valid_json(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return True


def _serialize_for_fingerprint(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, dict):
        return {key: _serialize_for_fingerprint(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_serialize_for_fingerprint(item) for item in value]
    if hasattr(value, "__dict__"):
        return {key: _serialize_for_fingerprint(item) for key, item in sorted(vars(value).items())}
    return value


def configuration_fingerprint(
    profile: Any,
    *,
    max_clips: int,
    target_duration: float | None,
    aspect_ratio: str | None = None,
    burn_subtitles: bool = False,
) -> str:
    payload = {
        "profile": _serialize_for_fingerprint(profile),
        "max_clips": max_clips,
        "target_duration": target_duration,
        "aspect_ratio": aspect_ratio,
        "burn_subtitles": burn_subtitles,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def initial_stage_statuses() -> dict[str, str]:
    return {stage: str(StageStatus.NOT_STARTED) for stage in STAGES}


def _status_file_stages(root: Path) -> dict[str, str]:
    status_path = root / "status.json"
    if not status_path.exists():
        return {}
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    stages = payload.get("stages", {})
    if not isinstance(stages, dict):
        return {}
    return {
        stage: str((details or {}).get("status", StageStatus.NOT_STARTED))
        for stage, details in stages.items()
        if isinstance(details, dict)
    }


def stage_status(session_dir: str | Path, expected_windows: int | None = None) -> dict[str, str]:
    root = Path(session_dir)
    statuses: dict[str, str] = initial_stage_statuses()
    statuses.update(_status_file_stages(root))
    statuses["metadata"] = StageStatus.COMPLETE if _valid_json(root / "metadata.json") else StageStatus.NOT_STARTED
    statuses["prefilter"] = StageStatus.COMPLETE if _valid_json(root / "prefilter" / "candidates.json") else StageStatus.NOT_STARTED
    statuses["audio"] = StageStatus.COMPLETE if _valid_json(root / "signals" / "audio.json") or _valid_json(root / "audio.json") else statuses.get("audio", StageStatus.NOT_STARTED)
    statuses["motion"] = StageStatus.COMPLETE if _valid_json(root / "signals" / "motion.json") or _valid_json(root / "motion.json") else statuses.get("motion", StageStatus.NOT_STARTED)
    statuses["transcription"] = StageStatus.COMPLETE if _valid_json(root / "signals" / "transcript.json") or _valid_json(root / "transcript.json") else statuses.get("transcription", StageStatus.NOT_STARTED)
    windows = sorted((root / "vision").glob("window_*.json")) if (root / "vision").exists() else []
    valid_windows = sum(_valid_json(path) and "error" not in json.loads(path.read_text(encoding="utf-8")) for path in windows)
    if expected_windows and valid_windows == expected_windows:
        statuses["vision"] = StageStatus.COMPLETE
    elif valid_windows or windows:
        statuses["vision"] = StageStatus.PARTIAL
    elif statuses.get("vision") not in {StageStatus.SKIPPED, StageStatus.FAILED, StageStatus.RUNNING}:
        statuses["vision"] = StageStatus.NOT_STARTED
    statuses["events"] = StageStatus.COMPLETE if _valid_json(root / "events.json") else statuses.get("events", StageStatus.NOT_STARTED)
    statuses["arcs"] = StageStatus.COMPLETE if _valid_json(root / "arcs.json") else statuses.get("arcs", StageStatus.NOT_STARTED)
    statuses["scoring"] = StageStatus.COMPLETE if _valid_json(root / "ranking.json") or _valid_json(root / "scoring.json") else statuses.get("scoring", StageStatus.NOT_STARTED)
    statuses["selection"] = StageStatus.COMPLETE if _valid_json(root / "selection.json") else statuses.get("selection", StageStatus.NOT_STARTED)
    statuses["timeline"] = StageStatus.COMPLETE if _valid_json(root / "timeline.json") else statuses.get("timeline", StageStatus.NOT_STARTED)
    output = root / "output"
    statuses["render"] = StageStatus.COMPLETE if (output / "montage.mp4").exists() or (root / "final.mp4").exists() else statuses.get("render", StageStatus.NOT_STARTED)
    statuses["qc"] = StageStatus.COMPLETE if _valid_json(output / "qc.json") or _valid_json(root / "qc.json") else statuses.get("qc", StageStatus.NOT_STARTED)
    return {stage: str(statuses[stage]) for stage in STAGES}


def write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    temporary.replace(target)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()