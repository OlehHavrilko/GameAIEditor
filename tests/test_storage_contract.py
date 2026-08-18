from __future__ import annotations

from pathlib import Path

from game_ai_editor.storage import (
    backend_render_artifacts,
    canonical_relative_final_output_path,
    canonical_relative_preview_output_path,
    ensure_project_output_dir,
    project_id_from_source,
)
from game_ai_editor.orchestration.state import source_identity, source_matches


def test_canonical_output_paths_are_repo_relative() -> None:
    project_id = project_id_from_source("input/session_01.mp4")
    final_path = canonical_relative_final_output_path(project_id)
    preview_path = canonical_relative_preview_output_path(project_id)

    assert final_path.replace("\\", "/").startswith("output/")
    assert final_path.replace("\\", "/").endswith("/final.mp4")
    assert preview_path.replace("\\", "/").startswith("output/")
    assert preview_path.replace("\\", "/").endswith("/preview.mp4")


def test_output_directory_is_created_automatically() -> None:
    project_id = "arma_real_test"
    output_dir = ensure_project_output_dir(project_id)

    assert output_dir.exists()
    assert output_dir.as_posix().endswith("output/arma_real_test")
    assert canonical_relative_final_output_path(project_id).replace("\\", "/").startswith("output/")


def test_backend_contract_exposes_public_output_paths() -> None:
    project_id = project_id_from_source("input/arma_real_test.mp4")
    artifacts = backend_render_artifacts(project_id)

    assert artifacts["final_output_path"].replace("\\", "/").startswith("output/")
    assert artifacts["final_output_path"].replace("\\", "/").endswith("/final.mp4")
    assert artifacts["preview_output_path"].replace("\\", "/").startswith("output/")
    assert artifacts["preview_output_path"].replace("\\", "/").endswith("/preview.mp4")
    assert artifacts["final_output_path"] != artifacts["preview_output_path"]


def test_production_render_uses_canonical_output_contract() -> None:
    project_id = "contract_render"
    output_dir = ensure_project_output_dir(project_id)
    final_path = output_dir / "final.mp4"
    preview_path = output_dir / "preview.mp4"

    assert final_path.as_posix().startswith(str((Path(__file__).resolve().parents[1] / "output").resolve().as_posix()))
    assert preview_path.as_posix().startswith(str((Path(__file__).resolve().parents[1] / "output").resolve().as_posix()))
    assert "finalvids" not in str(final_path).lower()
    assert "work" not in str(final_path).lower()


def test_identical_filenames_from_different_directories_get_distinct_project_ids(tmp_path: Path) -> None:
    first = tmp_path / "A" / "recording.mp4"
    second = tmp_path / "B" / "recording.mp4"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"one")
    second.write_bytes(b"one")
    assert project_id_from_source(first) != project_id_from_source(second)


def test_source_identity_can_be_strongly_validated(tmp_path: Path) -> None:
    source = tmp_path / "recording.mp4"
    source.write_bytes(b"original")
    identity = source_identity(source, include_hash=True)
    payload = {"source_identity": identity.__dict__}
    assert source_matches(payload, identity, require_hash=True)
    source.write_bytes(b"replaced")
    replaced = source_identity(source, include_hash=True)
    assert not source_matches(payload, replaced, require_hash=True)
