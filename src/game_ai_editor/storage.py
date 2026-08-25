from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath

from game_ai_editor.paths import data_root


def _normalize_project_id(value: str | Path) -> str:
    raw = str(value).strip()
    if not raw:
        return "project"
    source_name = Path(raw).stem if Path(raw).suffix else Path(raw).name
    project_id = re.sub(r"[^A-Za-z0-9._-]+", "_", source_name).strip("._-")
    return (project_id or "project").lower()


def project_id_from_source(source_path: str | Path) -> str:
    source = Path(source_path).resolve()
    try:
        stat = source.stat()
        identity = {
            "path": str(source).casefold(),
            "filename": source.name.casefold(),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
    except OSError:
        identity = {"path": str(source).casefold(), "filename": source.name.casefold()}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    stem = _normalize_project_id(source)
    return f"{stem}-{digest}"


def canonical_relative_output_dir(project_id: str | Path) -> str:
    normalized = _normalize_project_id(project_id)
    return str(PurePosixPath("output") / normalized)


def canonical_relative_final_output_path(project_id: str | Path) -> str:
    return str(PurePosixPath(canonical_relative_output_dir(project_id)) / "final.mp4")


def canonical_relative_preview_output_path(project_id: str | Path) -> str:
    return str(PurePosixPath(canonical_relative_output_dir(project_id)) / "preview.mp4")


def canonical_output_root(project_id: str | Path) -> Path:
    return data_root() / Path(canonical_relative_output_dir(project_id))


def ensure_project_output_dir(project_id: str | Path) -> Path:
    output_dir = canonical_output_root(project_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def backend_render_artifacts(project_id: str | Path) -> dict[str, str]:
    project_key = _normalize_project_id(project_id)
    return {
        "final_output_path": canonical_relative_final_output_path(project_key),
        "preview_output_path": canonical_relative_preview_output_path(project_key),
        "output_directory": str(PurePosixPath(canonical_relative_output_dir(project_key))),
    }
