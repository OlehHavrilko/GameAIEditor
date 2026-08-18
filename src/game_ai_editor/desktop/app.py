from __future__ import annotations

import os
import shutil
import sys
import threading
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import QObject, QSettings, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from game_ai_editor.batch import SUPPORTED_EXTENSIONS, discover_videos
from game_ai_editor.config.loader import load_game_profile
from game_ai_editor.desktop.errors import ErrorPresenter
from game_ai_editor.diagnostics import collect_system_diagnostics
from game_ai_editor.orchestration.orchestrator import ProductionOrchestrator
from game_ai_editor.orchestration.session import AnalysisQueue, AnalysisSession
from game_ai_editor.orchestration.state import STAGES as PIPELINE_STAGES
from game_ai_editor.runtime import OllamaRuntimeManager, RuntimeSnapshot, RuntimeState
from game_ai_editor.vision.factory import create_vision_provider


class AnalysisWorker(QObject):
    progress = Signal(str, str, dict)
    item_progress = Signal(int, str, str)
    finished = Signal(list)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, videos: list[Path], profile_path: Path, provider_values: dict[str, str | None], max_clips: int) -> None:
        super().__init__()
        self.videos = videos
        self.profile_path = profile_path
        self.provider_values = provider_values
        self.max_clips = max_clips
        self.abort_requested = threading.Event()

    @Slot()
    def cancel(self) -> None:
        self.abort_requested.set()

    @Slot()
    def run(self) -> None:
        results: list[dict[str, Any]] = []
        try:
            profile = load_game_profile(self.profile_path)
            profile.vision.enabled = True
            for key, value in self.provider_values.items():
                if value:
                    setattr(profile.vision, key, value)
            provider = create_vision_provider(profile.vision)
            for index, video in enumerate(self.videos):
                if self.abort_requested.is_set():
                    self.cancelled.emit()
                    return
                def on_progress(stage: str, status: str, details: dict[str, Any], current: int = index) -> None:
                    self.item_progress.emit(current, stage, status)
                    self.progress.emit(stage, status, details)

                orchestrator = ProductionOrchestrator(
                    profile=profile,
                    vision_provider=provider,
                    progress=on_progress,
                    cancellation_requested=self.abort_requested.is_set,
                )
                try:
                    result = orchestrator.run(video, max_clips=self.max_clips)
                    result["video"] = str(video)
                    results.append(result)
                except Exception as exc:  # noqa: BLE001 - worker-level isolation boundary
                    if self.abort_requested.is_set() or str(exc) == "JOB_CANCELLED":
                        self.cancelled.emit()
                        return
                    results.append({"status": "FAILED", "video": str(video), "error": str(exc)})
            self.finished.emit(results)
        except Exception as exc:  # noqa: BLE001 - worker-level isolation boundary
            self.failed.emit(str(exc))


def output_directory_from_result(result: dict[str, Any]) -> str | None:
    """Return the backend-owned canonical output directory."""
    value = result.get("output_directory")
    return str(value) if value else None


class ModelDownloadWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal()

    def __init__(self, runtime: OllamaRuntimeManager) -> None:
        super().__init__()
        self.runtime = runtime

    @Slot()
    def run(self) -> None:
        try:
            snapshot = self.runtime.install_model(progress=self.progress.emit)
        except OSError as exc:
            self.failed.emit("OLLAMA_PULL_FAILED", str(exc))
            return
        if snapshot.error_code == "JOB_CANCELLED":
            self.cancelled.emit()
        elif snapshot.state == RuntimeState.ERROR:
            self.failed.emit(snapshot.error_code or "OLLAMA_PULL_FAILED", snapshot.error_message or snapshot.detail or "Model download failed.")
        else:
            self.finished.emit(snapshot)

    @Slot()
    def cancel(self) -> None:
        self.runtime.cancel_model_download()


class FirstRunDialog(QDialog):
    def __init__(self, runtime: OllamaRuntimeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("GameAIEditor setup")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Welcome to GameAIEditor\nAnalyze gameplay and create highlight videos locally."))
        layout.addWidget(QLabel("System check"))
        diagnostics = collect_system_diagnostics()
        checks = "\n".join(f"{item['status']}: {item['name']} - {item['value']}" for item in diagnostics["checks"])
        runtime_snapshot = runtime.detect()
        checks += f"\n{runtime_snapshot.state}: Ollama - {runtime_snapshot.detail or runtime_snapshot.base_url}"
        checks += f"\nModel: {runtime_snapshot.model}"
        check_view = QPlainTextEdit()
        check_view.setReadOnly(True)
        check_view.setPlainText(checks)
        layout.addWidget(check_view)
        if runtime_snapshot.state == RuntimeState.NOT_INSTALLED:
            layout.addWidget(QLabel("Ollama is not installed. You can continue in degraded mode or install it separately."))
        elif runtime_snapshot.state == RuntimeState.MODEL_MISSING:
            layout.addWidget(QLabel("The selected local vision model is missing. Download it from the AI Engine tab, or continue in degraded mode."))
        layout.addWidget(QLabel("Local AI setup is optional; no API keys are stored by this setup."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("GameAIEditor")
        self.resize(980, 700)
        self.videos: list[Path] = []
        default_profile = load_game_profile(Path("config/games/arma_reforger.json"))
        self.analysis_thread: QThread | None = None
        self.worker: AnalysisWorker | None = None
        self.download_thread: QThread | None = None
        self.download_worker: ModelDownloadWorker | None = None
        self.ollama_manager = OllamaRuntimeManager(
            base_url=default_profile.vision.base_url,
            model=default_profile.vision.model,
        )

        central = QWidget()
        root = QVBoxLayout(central)
        self.setCentralWidget(central)
        self.analysis_queue = AnalysisQueue(Path("work/desktop"))
        self.analysis_queue.load()
        self.queue_sessions = {session.source_path: session for session in self.analysis_queue.sessions}
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        header = QHBoxLayout()
        header.addWidget(QLabel("GameAIEditor"))
        self.add_files_button = QPushButton("+ Add Videos")
        self.add_folder_button = QPushButton("+ Add Folder")
        self.start_button = QPushButton("START ANALYSIS")
        self.cancel_analysis_button = QPushButton("CANCEL ANALYSIS")
        self.cancel_analysis_button.setEnabled(False)
        header.addStretch()
        header.addWidget(self.add_files_button)
        header.addWidget(self.add_folder_button)
        header.addWidget(self.start_button)
        header.addWidget(self.cancel_analysis_button)
        dashboard_page = QWidget()
        dashboard_layout = QVBoxLayout(dashboard_page)
        dashboard_layout.addLayout(header)
        self.dashboard_status = QLabel("Preparing workspace...")
        self.dashboard_summary = QLabel("")
        dashboard_layout.addWidget(self.dashboard_status)
        dashboard_layout.addWidget(self.dashboard_summary)
        dashboard_layout.addStretch()

        settings = QGroupBox("Analysis settings")
        form = QFormLayout(settings)
        self.game_combo = QComboBox()
        self.game_combo.addItem("Arma Reforger", "config/games/arma_reforger.json")
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["ollama", "lm_studio", "openrouter", "custom"])
        self.model_edit = QLineEdit(default_profile.vision.model)
        self.base_url_edit = QLineEdit("http://localhost:11434")
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.clip_count = QSpinBox()
        self.clip_count.setRange(1, 50)
        self.clip_count.setValue(10)
        form.addRow("Game", self.game_combo)
        form.addRow("AI provider", self.provider_combo)
        form.addRow("Model", self.model_edit)
        form.addRow("Base URL", self.base_url_edit)
        form.addRow("API key (memory only)", self.api_key_edit)
        form.addRow("Maximum clips", self.clip_count)
        settings_page = QWidget()
        settings_layout = QVBoxLayout(settings_page)
        settings_layout.addWidget(settings)
        settings_layout.addStretch()

        ai_engine = QGroupBox("AI Engine")
        ai_form = QFormLayout(ai_engine)
        self.runtime_status_label = QLabel("Checking runtime...")
        self.runtime_detail_label = QLabel("")
        self.runtime_provider_label = QLabel(self.provider_combo.currentText())
        self.runtime_model_label = QLabel(self.model_edit.text())
        self.runtime_management_label = QLabel("Local runtime lifecycle available for Ollama")
        ai_form.addRow("Provider", self.runtime_provider_label)
        ai_form.addRow("Runtime status", self.runtime_status_label)
        ai_form.addRow("Model", self.runtime_model_label)
        ai_form.addRow("Details", self.runtime_detail_label)
        ai_form.addRow("Management", self.runtime_management_label)
        ai_buttons = QHBoxLayout()
        self.refresh_runtime_button = QPushButton("Refresh Runtime")
        self.start_runtime_button = QPushButton("Start Local AI")
        self.download_model_button = QPushButton("Download Model")
        self.stop_runtime_button = QPushButton("Stop Local AI")
        ai_buttons.addWidget(self.refresh_runtime_button)
        ai_buttons.addWidget(self.start_runtime_button)
        ai_buttons.addWidget(self.download_model_button)
        ai_buttons.addWidget(self.stop_runtime_button)
        ai_form.addRow(ai_buttons)
        ai_page = QWidget()
        ai_layout = QVBoxLayout(ai_page)
        ai_layout.addWidget(ai_engine)
        ai_layout.addWidget(QLabel("System diagnostics"))
        self.system_diagnostics = QPlainTextEdit()
        self.system_diagnostics.setReadOnly(True)
        ai_layout.addWidget(self.system_diagnostics)

        self.queue = QListWidget()
        queue_page = QWidget()
        queue_layout = QVBoxLayout(queue_page)
        queue_layout.addWidget(QLabel("Queue"))
        queue_layout.addWidget(self.queue, 1)
        queue_layout.addWidget(QLabel("Persistent queue is stored in work/desktop/queue.json"))
        queue_actions = QHBoxLayout()
        self.pause_queue_button = QPushButton("Pause Selected")
        self.resume_queue_button = QPushButton("Resume Selected")
        self.cancel_queue_button = QPushButton("Cancel Selected")
        self.retry_queue_button = QPushButton("Retry Selected")
        for button in (self.pause_queue_button, self.resume_queue_button, self.cancel_queue_button, self.retry_queue_button):
            queue_actions.addWidget(button)
        queue_layout.addLayout(queue_actions)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.stage_label = QLabel("Ready")
        analysis_page = QWidget()
        analysis_layout = QVBoxLayout(analysis_page)
        analysis_layout.addWidget(QLabel("Pipeline analysis"))
        self.stage_list = QListWidget()
        for stage in PIPELINE_STAGES:
            self.stage_list.addItem(f"{stage}: NOT_STARTED")
        analysis_layout.addWidget(self.stage_list)
        analysis_layout.addWidget(self.stage_label)
        analysis_layout.addWidget(self.progress)
        results_page = QWidget()
        results_layout = QVBoxLayout(results_page)
        results_layout.addWidget(QLabel("Highlights and outputs"))
        self.results_view = QPlainTextEdit()
        self.results_view.setReadOnly(True)
        results_layout.addWidget(self.results_view)
        self.results_selection = QListWidget()
        results_layout.addWidget(self.results_selection)
        results_actions = QHBoxLayout()
        self.remove_result_button = QPushButton("Remove Clip")
        self.move_result_up_button = QPushButton("Move Up")
        self.move_result_down_button = QPushButton("Move Down")
        self.rerender_button = QPushButton("Re-render Montage")
        self.open_result_button = QPushButton("Open Result Folder")
        self.export_result_button = QPushButton("Export Montage")
        for button in (self.remove_result_button, self.move_result_up_button, self.move_result_down_button, self.rerender_button, self.open_result_button, self.export_result_button):
            results_actions.addWidget(button)
        results_layout.addLayout(results_actions)
        self.result_context: dict[str, object] | None = None

        self.tabs.addTab(dashboard_page, "Dashboard")
        self.tabs.addTab(settings_page, "Settings")
        self.tabs.addTab(queue_page, "Queue")
        self.tabs.addTab(analysis_page, "Analysis")
        self.tabs.addTab(ai_page, "AI Engine")
        self.tabs.addTab(results_page, "Results")

        self.add_files_button.clicked.connect(self.add_files)
        self.add_folder_button.clicked.connect(self.add_folder)
        self.start_button.clicked.connect(self.start_analysis)
        self.cancel_analysis_button.clicked.connect(self._cancel_analysis)
        self.provider_combo.currentTextChanged.connect(self._provider_defaults)
        self.provider_combo.currentTextChanged.connect(self._refresh_ai_status)
        self.model_edit.editingFinished.connect(self._refresh_ai_status)
        self.base_url_edit.editingFinished.connect(self._refresh_ai_status)
        self.refresh_runtime_button.clicked.connect(self._refresh_ai_status)
        self.start_runtime_button.clicked.connect(self._start_runtime)
        self.download_model_button.clicked.connect(self._download_model)
        self.stop_runtime_button.clicked.connect(self._stop_runtime)
        self.pause_queue_button.clicked.connect(lambda: self._queue_action("pause"))
        self.resume_queue_button.clicked.connect(lambda: self._queue_action("resume"))
        self.cancel_queue_button.clicked.connect(lambda: self._queue_action("cancel"))
        self.retry_queue_button.clicked.connect(lambda: self._queue_action("retry"))
        self.remove_result_button.clicked.connect(self._remove_result)
        self.move_result_up_button.clicked.connect(lambda: self._move_result(-1))
        self.move_result_down_button.clicked.connect(lambda: self._move_result(1))
        self.rerender_button.clicked.connect(self._rerender_results)
        self.open_result_button.clicked.connect(self._open_result_folder)
        self.export_result_button.clicked.connect(self._export_result)
        self.runtime_timer = QTimer(self)
        self.runtime_timer.setInterval(10000)
        self.runtime_timer.timeout.connect(self._refresh_ai_status)
        self.runtime_timer.start()
        self.system_diagnostics.setPlainText(self._diagnostics_text())
        self._restore_queue()
        self._refresh_ai_status()
        if not QSettings("GameAIEditor", "GameAIEditor").value("first_run_complete", False, type=bool):
            QTimer.singleShot(0, self._show_first_run)

    def _show_first_run(self) -> None:
        dialog = FirstRunDialog(self.ollama_manager, self)
        dialog.exec()
        settings = QSettings("GameAIEditor", "GameAIEditor")
        settings.setValue("first_run_complete", True)

    def _diagnostics_text(self) -> str:
        result = collect_system_diagnostics()
        return "\n".join(
            f"{item['status']:8} {item['name']}: {item['value']}"
            for item in result["checks"]
        )

    def _restore_queue(self) -> None:
        self.videos.clear()
        self.queue.clear()
        for session in self.analysis_queue.sessions:
            path = Path(session.source_path)
            if path.exists():
                self.videos.append(path)
                item = QListWidgetItem(f"{path.name}    {session.status}    {session.overall_progress:.0f}%")
                item.setData(32, str(path))
                self.queue.addItem(item)
        self._update_dashboard()

    def _selected_session(self) -> AnalysisSession | None:
        item = self.queue.currentItem()
        if item is None:
            return None
        path = str(item.data(32) or "")
        return self.queue_sessions.get(str(Path(path).resolve()))

    @Slot()
    def _queue_action(self, action: str) -> None:
        session = self._selected_session()
        if session is None:
            return
        getattr(self.analysis_queue, action)(session.session_id)
        self._restore_queue()

    def _update_dashboard(self) -> None:
        active = sum(session.status in {"RUNNING", "QUEUED"} for session in self.analysis_queue.sessions)
        completed = sum(session.status in {"SUCCESS", "NO_HIGHLIGHTS"} for session in self.analysis_queue.sessions)
        self.dashboard_status.setText(f"AI Engine: {self.runtime_status_label.text()}")
        self.dashboard_summary.setText(f"Queue: {len(self.analysis_queue.sessions)} sessions | Active: {active} | Completed: {completed}")

    def _provider_defaults(self, provider: str) -> None:
        defaults = {
            "ollama": "http://localhost:11434",
            "lm_studio": "http://localhost:1234/v1",
            "openrouter": "https://openrouter.ai/api/v1",
            "custom": "http://localhost:8000/v1",
        }
        self.base_url_edit.setText(defaults[provider])

    def _sync_runtime_manager(self) -> None:
        self.ollama_manager.base_url = self.base_url_edit.text().strip() or "http://localhost:11434"
        self.ollama_manager.model = self.model_edit.text().strip() or "qwen3-vl:8b-instruct"

    def _provider_config(self) -> dict[str, str | None]:
        return {
            "provider": self.provider_combo.currentText(),
            "model": self.model_edit.text().strip(),
            "base_url": self.base_url_edit.text().strip(),
            "api_key": self.api_key_edit.text() or None,
        }

    def _set_runtime_snapshot(self, snapshot: RuntimeSnapshot) -> None:
        self.runtime_provider_label.setText(f"ollama ({snapshot.base_url})")
        self.runtime_model_label.setText(snapshot.model)
        detail = snapshot.detail or snapshot.error_message or ""
        management = "External instance detected" if snapshot.externally_managed else "Managed by GameAIEditor"
        if snapshot.state == RuntimeState.READY:
            status = "READY"
        elif snapshot.state == RuntimeState.EXTERNAL_INSTANCE:
            status = "READY (EXTERNAL_INSTANCE)"
        else:
            status = str(snapshot.state)
        if snapshot.download_percent is not None:
            detail = f"{detail} ({snapshot.download_percent:.0f}%)".strip()
        self.runtime_status_label.setText(status)
        self.runtime_detail_label.setText(detail)
        self.runtime_management_label.setText(management)
        self.start_runtime_button.setEnabled(snapshot.state in {RuntimeState.NOT_INSTALLED, RuntimeState.INSTALLED_STOPPED, RuntimeState.ERROR})
        self.download_model_button.setEnabled(snapshot.state in {RuntimeState.READY, RuntimeState.EXTERNAL_INSTANCE, RuntimeState.MODEL_MISSING})
        self.stop_runtime_button.setEnabled(not snapshot.externally_managed and snapshot.state in {RuntimeState.READY, RuntimeState.MODEL_MISSING, RuntimeState.STARTING})
        self._update_dashboard()

    def _refresh_ai_status(self) -> None:
        provider = self.provider_combo.currentText()
        self.runtime_provider_label.setText(provider)
        self.runtime_model_label.setText(self.model_edit.text().strip())
        if provider == "ollama":
            self._sync_runtime_manager()
            self._set_runtime_snapshot(self.ollama_manager.detect())
            return

        config = self._provider_config()
        self.start_runtime_button.setEnabled(False)
        self.download_model_button.setEnabled(False)
        self.stop_runtime_button.setEnabled(False)
        self.runtime_management_label.setText("External provider lifecycle is managed outside GameAIEditor")
        try:
            provider_client = create_vision_provider(config)
            checker = getattr(provider_client, "check_available", None)
            if callable(checker):
                checker()
            self.runtime_status_label.setText("READY")
            self.runtime_detail_label.setText("Endpoint responded and the configured model is available.")
        except Exception as exc:  # noqa: BLE001 - availability probe isolation
            self.runtime_status_label.setText("OFFLINE")
            self.runtime_detail_label.setText(str(exc))
        self._update_dashboard()

    @Slot()
    def _start_runtime(self) -> None:
        self._sync_runtime_manager()
        self._set_runtime_snapshot(self.ollama_manager.start())

    @Slot()
    def _stop_runtime(self) -> None:
        self._sync_runtime_manager()
        self._set_runtime_snapshot(self.ollama_manager.stop())

    @Slot()
    def _download_model(self) -> None:
        self._sync_runtime_manager()
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Downloading local vision model")
        dialog.setText(f"Downloading {self.ollama_manager.model}...\nThis may take several minutes.")
        dialog.setStandardButtons(QMessageBox.StandardButton.Cancel)
        self.download_thread = QThread(self)
        self.download_worker = ModelDownloadWorker(self.ollama_manager)
        self.download_worker.moveToThread(self.download_thread)
        self.download_thread.started.connect(self.download_worker.run)
        self.download_worker.progress.connect(lambda snapshot: self._update_download_dialog(dialog, snapshot))
        self.download_worker.finished.connect(lambda snapshot: self._download_finished(dialog, snapshot))
        self.download_worker.cancelled.connect(lambda: self._download_cancelled(dialog))
        self.download_worker.failed.connect(lambda code, message: self._download_failed(dialog, code, message))
        dialog.button(QMessageBox.StandardButton.Cancel).clicked.connect(self.download_worker.cancel)
        self.download_thread.start()
        dialog.exec()

    @staticmethod
    def _update_download_dialog(dialog: QMessageBox, snapshot: RuntimeSnapshot) -> None:
        percent = f" {snapshot.download_percent:.0f}%" if snapshot.download_percent is not None else ""
        dialog.setText(f"Downloading {snapshot.model}...{percent}\n{snapshot.detail or ''}")

    def _finish_download_worker(self) -> None:
        if self.download_thread:
            self.download_thread.quit()
            self.download_thread.wait()
        self.download_worker = None
        self.download_thread = None

    def _download_finished(self, dialog: QMessageBox, snapshot: RuntimeSnapshot) -> None:
        dialog.done(QDialog.DialogCode.Accepted)
        self._set_runtime_snapshot(snapshot)
        self._finish_download_worker()
        self._refresh_ai_status()

    def _download_cancelled(self, dialog: QMessageBox) -> None:
        dialog.done(QDialog.DialogCode.Rejected)
        self._finish_download_worker()
        self._refresh_ai_status()

    def _download_failed(self, dialog: QMessageBox, code: str, message: str) -> None:
        dialog.done(QDialog.DialogCode.Rejected)
        presenter = ErrorPresenter(parent=self)
        presenter.present(code, technical_message=message)
        self._finish_download_worker()
        self._refresh_ai_status()

    def _append_videos(self, paths: list[Path]) -> None:
        known = {str(path.resolve()) for path in self.videos}
        for path in paths:
            if path.suffix.casefold() in SUPPORTED_EXTENSIONS and str(path.resolve()) not in known:
                self.videos.append(path)
                item = QListWidgetItem(f"{path.name}    Waiting")
                item.setData(32, str(path))
                self.queue.addItem(item)
                session = self.analysis_queue.add(
                    path,
                    Path("work/desktop/sessions") / path.stem,
                    profile_path=self.game_combo.currentData(),
                    provider=self.provider_combo.currentText(),
                    model=self.model_edit.text().strip(),
                )
                self.queue_sessions[str(path.resolve())] = session
                known.add(str(path.resolve()))
        self.analysis_queue.save()
        self._update_dashboard()

    @Slot()
    def add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add gameplay videos", filter="Video files (*.mp4 *.mkv *.mov *.webm)")
        self._append_videos([Path(path) for path in paths])

    @Slot()
    def add_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Add recordings folder")
        if directory:
            self._append_videos(discover_videos(directory))

    @Slot()
    def start_analysis(self) -> None:
        if not self.videos:
            QMessageBox.information(self, "Queue is empty", "Add at least one gameplay video.")
            return
        self.start_button.setEnabled(False)
        self.cancel_analysis_button.setEnabled(True)
        self.progress.setValue(0)
        self.stage_label.setText("Preparing analysis...")
        self.analysis_thread = QThread(self)
        self.worker = AnalysisWorker(
            self.videos,
            Path(self.game_combo.currentData()),
            self._provider_config(),
            self.clip_count.value(),
        )
        self.worker.moveToThread(self.analysis_thread)
        self.analysis_thread.started.connect(self.worker.run)
        self.worker.item_progress.connect(self._update_item)
        self.worker.progress.connect(self._update_progress)
        self.worker.finished.connect(self._analysis_finished)
        self.worker.failed.connect(self._analysis_failed)
        self.worker.cancelled.connect(self._analysis_cancelled)
        self.analysis_thread.start()

    @Slot(int, str, str)
    def _update_item(self, index: int, stage: str, status: str) -> None:
        if item := self.queue.item(index):
            item.setText(f"{self.videos[index].name}    {stage}: {status}")
        if stage in PIPELINE_STAGES:
            stage_index = PIPELINE_STAGES.index(stage)
            if stage_index < self.stage_list.count():
                self.stage_list.item(stage_index).setText(f"{stage}: {status}")

    @Slot(str, str, dict)
    def _update_progress(self, stage: str, status: str, details: dict[str, Any]) -> None:
        stage_title = f"{stage}: {status}"
        if details.get("error_code"):
            stage_title = f"{stage}: {status} ({details['error_code']})"
        self.stage_label.setText(stage_title)
        if stage in PIPELINE_STAGES:
            stage_index = PIPELINE_STAGES.index(stage)
            if stage_index < self.stage_list.count():
                self.stage_list.item(stage_index).setText(f"{stage}: {status}")
        if stage in PIPELINE_STAGES:
            stage_index = PIPELINE_STAGES.index(stage)
            completed = stage_index / len(PIPELINE_STAGES)
            if status == "COMPLETE" or status == "DEGRADED":
                completed = (stage_index + 1) / len(PIPELINE_STAGES)
            elif status == "PROGRESS" and details.get("window") and details.get("total"):
                completed = (stage_index + (float(details["window"]) / float(details["total"]))) / len(PIPELINE_STAGES)
            self.progress.setValue(max(0, min(100, int(completed * 100))))

    @Slot(list)
    def _analysis_finished(self, results: list[dict[str, Any]]) -> None:
        self.progress.setValue(100)
        self.stage_label.setText(f"Completed: {sum(item.get('status') == 'SUCCESS' for item in results)} / {len(results)}")
        lines: list[str] = []
        for result in results:
            status = result.get("status", "FAILED")
            session_dir = result.get("session_dir", "")
            selected = result.get("selected", [])
            lines.append(f"{Path(result.get('video', session_dir)).name}: {status}")
            lines.append(f"  Highlights: {len(selected)}")
            final_output_path = result.get("final_output_path") or result.get("final_path")
            if final_output_path:
                lines.append(f"  Montage: {final_output_path}")
            for item in selected:
                event_type = item.get("event_type", "highlight").replace("_", " ")
                lines.append(
                    f"  Why this clip? {event_type}; "
                    f"score {float(item.get('highlight_score', 0.0)):.0f}, "
                    f"context {float(item.get('context_score', 0.0)):.0f}, "
                    f"confidence {float(item.get('confidence', 0.0)) * 100:.0f}%: "
                    f"{float(item.get('start_time', 0.0)):.1f}s - {float(item.get('end_time', 0.0)):.1f}s"
                )
        first = next((result for result in results if result.get("selected")), None)
        self.result_context = first
        self.results_selection.clear()
        if first:
            for index, item in enumerate(first.get("selected", []), start=1):
                self.results_selection.addItem(
                    f"{index}. {item.get('event_type', 'highlight')}  "
                    f"{float(item.get('start_time', 0.0)):.1f}s - {float(item.get('end_time', 0.0)):.1f}s  "
                    f"score {float(item.get('highlight_score', 0.0)):.0f}"
                )
        self.results_view.setPlainText("\n".join(lines) or "No results")
        self.tabs.setCurrentIndex(5)
        for result in results:
            session_dir = result.get("session_dir")
            if session_dir:
                session = next((item for item in self.analysis_queue.sessions if item.session_dir == session_dir), None)
                if session:
                    self.analysis_queue.mark_completed(session.session_id, result.get("status", "FAILED"))
        self._restore_queue()
        self._refresh_ai_status()
        self._stop_worker()

    def _selected_result_items(self) -> list[dict[str, Any]]:
        if not self.result_context:
            return []
        return cast("list[dict[str, Any]]", self.result_context.get("selected", []))

    def _refresh_result_items(self, selected: list[dict[str, Any]]) -> None:
        self.results_selection.clear()
        for index, item in enumerate(selected, start=1):
            self.results_selection.addItem(f"{index}. {item.get('event_type', 'highlight')}  {float(item.get('start_time', 0.0)):.1f}s - {float(item.get('end_time', 0.0)):.1f}s")

    def _remove_result(self) -> None:
        index = self.results_selection.currentRow()
        selected = self._selected_result_items()
        if 0 <= index < len(selected):
            selected.pop(index)
            if self.result_context:
                self.result_context["selected"] = selected
            self._refresh_result_items(selected)

    def _move_result(self, offset: int) -> None:
        index = self.results_selection.currentRow()
        selected = self._selected_result_items()
        target = index + offset
        if 0 <= index < len(selected) and 0 <= target < len(selected):
            selected[index], selected[target] = selected[target], selected[index]
            if self.result_context:
                self.result_context["selected"] = selected
            self._refresh_result_items(selected)
            self.results_selection.setCurrentRow(target)

    def _rerender_results(self) -> None:
        if not self.result_context:
            return
        video = self.result_context.get("video")
        session_dir = self.result_context.get("session_dir")
        if not video or not session_dir:
            return
        profile = load_game_profile(Path(self.game_combo.currentData()))
        result = ProductionOrchestrator(profile=profile, vision_provider=None).rerender_selection(
            str(video), str(session_dir), self._selected_result_items()
        )
        self.result_context.update(result)
        final_output_path = result.get("final_output_path") or result.get("final_path") or "none"
        self.results_view.appendPlainText(f"\nRe-render: {result.get('status')}\nMontage: {final_output_path}")

    def _open_result_folder(self) -> None:
        output_directory = output_directory_from_result(self.result_context or {})
        if output_directory:
            os.startfile(str(output_directory))  # type: ignore[attr-defined]

    def _export_result(self) -> None:
        final_path = (self.result_context or {}).get("final_output_path") or (self.result_context or {}).get("final_path") if self.result_context else None
        if final_path:
            target, _ = QFileDialog.getSaveFileName(self, "Export montage", Path(str(final_path)).name, "MP4 video (*.mp4)")
            if target:
                shutil.copy2(str(final_path), target)

    @Slot(str)
    def _analysis_failed(self, message: str) -> None:
        presenter = ErrorPresenter(parent=self)
        presenter.present("VISION_PROVIDER_OFFLINE", technical_message=message, on_action=self._open_settings)
        self._stop_worker()

    def _open_settings(self) -> None:
        self.tabs.setCurrentIndex(1)

    @Slot()
    def _analysis_cancelled(self) -> None:
        self.stage_label.setText("Analysis cancelled")
        self._stop_worker()

    @Slot()
    def _cancel_analysis(self) -> None:
        if self.worker:
            self.worker.cancel()

    def _stop_worker(self) -> None:
        self.start_button.setEnabled(True)
        self.cancel_analysis_button.setEnabled(False)
        if self.analysis_thread:
            self.analysis_thread.quit()
            self.analysis_thread.wait()
        self.analysis_thread = None


def run_desktop_app() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()