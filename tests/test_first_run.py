from __future__ import annotations

from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

from game_ai_editor.desktop.app import FirstRunDialog
from game_ai_editor.runtime import OllamaRuntimeManager, RuntimeSnapshot, RuntimeState


@pytest.fixture(scope="session")
def _qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_first_run_shows_degraded_mode_when_ollama_missing(_qapp) -> None:
    runtime = OllamaRuntimeManager()
    snapshot = RuntimeSnapshot(
        state=RuntimeState.NOT_INSTALLED,
        runtime_name="Ollama",
        base_url="http://localhost:11434",
        model="qwen3-vl:8b-instruct",
        installed=False,
        healthy=False,
        model_available=False,
        externally_managed=False,
        detail="Ollama executable was not found on PATH.",
        error_code="OLLAMA_NOT_INSTALLED",
    )
    diagnostics = {
        "checks": [
            {"status": "READY", "name": "Python", "value": "3.12"},
            {"status": "READY", "name": "FFmpeg", "value": "ready"},
        ]
    }
    with patch.object(runtime, "detect", return_value=snapshot), patch(
        "game_ai_editor.desktop.app.collect_system_diagnostics", return_value=diagnostics
    ):
            dialog = FirstRunDialog(runtime)
            layout = dialog.layout()
            texts = [
                layout.itemAt(index).widget().text()
                for index in range(layout.count())
                if hasattr(layout.itemAt(index).widget(), "text")
            ]
            assert any("Ollama is not installed" in text for text in texts)
