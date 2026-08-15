from __future__ import annotations

import pytest

from game_ai_editor.desktop.errors import ERROR_PRESENTATIONS, ErrorPresenter


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
