from __future__ import annotations

from game_ai_editor.desktop.app import output_directory_from_result
from game_ai_editor.desktop.errors import ErrorPresenter


def test_error_presenter_maps_known_codes() -> None:
    for code in (
        "VISION_PROVIDER_OFFLINE",
        "VISION_MODEL_MISSING",
        "OLLAMA_NOT_INSTALLED",
        "OLLAMA_PULL_FAILED",
        "VISION_TIMEOUT",
        "INVALID_VIDEO",
        "FFMPEG_ERROR",
        "QC_FAILED",
        "SOURCE_CHANGED",
        "CONFIGURATION_CHANGED",
        "JOB_CANCELLED",
    ):
        presentation = ErrorPresenter.presentation_for(code)
        assert presentation.title
        assert presentation.description
        assert presentation.action


def test_error_presenter_handles_unknown_code() -> None:
    presentation = ErrorPresenter.presentation_for("UNKNOWN_MAGIC_CODE")
    assert presentation.title == "Unexpected error"


def test_output_directory_comes_from_backend_result() -> None:
    result = {
        "output_directory": "D:/repo/output/source-id",
        "session_dir": "D:/repo/work/sessions/source-id",
    }
    assert output_directory_from_result(result) == "D:/repo/output/source-id"
