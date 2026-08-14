from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import SourceIdentity, StageStatus


STAGES = ("metadata", "prefilter", "vision", "events", "arcs", "scoring", "selection", "timeline", "render", "qc")


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


def source_matches(payload: dict[str, Any], identity: SourceIdentity) -> bool:
    stored = payload.get("source_identity", {})
    return (
        stored.get("filename") == identity.filename
        and int(stored.get("size", -1)) == identity.size
        and int(stored.get("mtime_ns", -1)) == identity.mtime_ns
        and str(Path(stored.get("path", "")).resolve()) == identity.path
    )


def _valid_json(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return True


def stage_status(session_dir: str | Path, expected_windows: int | None = None) -> dict[str, str]:
    root = Path(session_dir)
    statuses: dict[str, str] = {}
    statuses["metadata"] = StageStatus.COMPLETE if _valid_json(root / "metadata.json") else StageStatus.NOT_STARTED
    statuses["prefilter"] = StageStatus.COMPLETE if _valid_json(root / "prefilter" / "candidates.json") else StageStatus.NOT_STARTED
    windows = sorted((root / "vision").glob("window_*.json")) if (root / "vision").exists() else []
    valid_windows = sum(_valid_json(path) and "error" not in json.loads(path.read_text(encoding="utf-8")) for path in windows)
    if expected_windows and valid_windows == expected_windows:
        statuses["vision"] = StageStatus.COMPLETE
    elif valid_windows or windows:
        statuses["vision"] = StageStatus.PARTIAL
    else:
        statuses["vision"] = StageStatus.NOT_STARTED
    for stage in ("events", "arcs", "scoring", "selection", "timeline"):
        statuses[stage] = StageStatus.COMPLETE if _valid_json(root / f"{stage}.json") else StageStatus.NOT_STARTED
    output = root / "output"
    statuses["render"] = StageStatus.COMPLETE if (output / "montage.mp4").exists() or (root / "final.mp4").exists() else StageStatus.NOT_STARTED
    statuses["qc"] = StageStatus.COMPLETE if _valid_json(output / "qc.json") or _valid_json(root / "qc.json") else StageStatus.NOT_STARTED
    return {stage: str(statuses[stage]) for stage in STAGES}


def write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    temporary.replace(target)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()