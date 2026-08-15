from __future__ import annotations

from unittest.mock import patch

from game_ai_editor.desktop.app import ModelDownloadWorker
from game_ai_editor.runtime import OllamaRuntimeManager, RuntimeSnapshot, RuntimeState


def test_model_download_worker_finishes_when_runtime_ready() -> None:
    runtime = OllamaRuntimeManager()
    snapshot = RuntimeSnapshot(
        state=RuntimeState.READY,
        runtime_name="Ollama",
        base_url="http://localhost:11434",
        model="qwen3-vl:8b-instruct",
        installed=True,
        healthy=True,
        model_available=True,
        externally_managed=True,
    )
    with patch.object(runtime, "install_model", return_value=snapshot) as mock_install:
        worker = ModelDownloadWorker(runtime)
        finished_snap = None

        def on_finished(snap):
            nonlocal finished_snap
            finished_snap = snap

        worker.finished.connect(on_finished)
        worker.run()
        mock_install.assert_called_once()
        assert finished_snap is not None
        assert finished_snap.state == RuntimeState.READY


def test_model_download_worker_cancelled_signal() -> None:
    runtime = OllamaRuntimeManager()
    snapshot = RuntimeSnapshot(
        state=RuntimeState.MODEL_MISSING,
        runtime_name="Ollama",
        base_url="http://localhost:11434",
        model="qwen3-vl:8b-instruct",
        installed=True,
        healthy=False,
        model_available=False,
        externally_managed=False,
        error_code="JOB_CANCELLED",
    )
    with patch.object(runtime, "install_model", return_value=snapshot):
        worker = ModelDownloadWorker(runtime)
        cancelled = False

        def on_cancelled():
            nonlocal cancelled
            cancelled = True

        worker.cancelled.connect(on_cancelled)
        worker.run()
        assert cancelled


def test_model_download_worker_failed_signal() -> None:
    runtime = OllamaRuntimeManager()
    snapshot = RuntimeSnapshot(
        state=RuntimeState.ERROR,
        runtime_name="Ollama",
        base_url="http://localhost:11434",
        model="qwen3-vl:8b-instruct",
        installed=True,
        healthy=False,
        model_available=False,
        externally_managed=False,
        error_code="OLLAMA_PULL_FAILED",
        error_message="disk full",
    )
    with patch.object(runtime, "install_model", return_value=snapshot):
        worker = ModelDownloadWorker(runtime)
        failed_code = None

        def on_failed(code, message):
            nonlocal failed_code
            failed_code = code

        worker.failed.connect(on_failed)
        worker.run()
        assert failed_code == "OLLAMA_PULL_FAILED"


def test_model_download_worker_propagates_os_error() -> None:
    runtime = OllamaRuntimeManager()
    with patch.object(runtime, "install_model", side_effect=OSError("fork failed")):
        worker = ModelDownloadWorker(runtime)
        failed_code = None

        def on_failed(code, message):
            nonlocal failed_code
            failed_code = code

        worker.failed.connect(on_failed)
        worker.run()
        assert failed_code == "OLLAMA_PULL_FAILED"
