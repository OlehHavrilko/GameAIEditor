from __future__ import annotations

import sys
from pathlib import Path

from game_ai_editor.batch import SUPPORTED_EXTENSIONS, discover_videos
from game_ai_editor.config.loader import load_game_profile
from game_ai_editor.orchestration.orchestrator import ProductionOrchestrator
from game_ai_editor.vision.factory import create_vision_provider

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
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
    QPushButton,
    QProgressBar,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class AnalysisWorker(QObject):
    progress = Signal(str, str, dict)
    item_progress = Signal(int, str, str)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, videos: list[Path], profile_path: Path, provider_values: dict[str, str], max_clips: int) -> None:
        super().__init__()
        self.videos = videos
        self.profile_path = profile_path
        self.provider_values = provider_values
        self.max_clips = max_clips

    @Slot()
    def run(self) -> None:
        results: list[dict] = []
        try:
            profile = load_game_profile(self.profile_path)
            profile.vision.enabled = True
            for key, value in self.provider_values.items():
                if value:
                    setattr(profile.vision, key, value)
            provider = create_vision_provider(profile.vision)
            for index, video in enumerate(self.videos):
                def on_progress(stage: str, status: str, details: dict, current=index) -> None:
                    self.item_progress.emit(current, stage, status)
                    self.progress.emit(stage, status, details)

                orchestrator = ProductionOrchestrator(
                    profile=profile,
                    vision_provider=provider,
                    progress=on_progress,
                )
                try:
                    results.append(orchestrator.run(video, max_clips=self.max_clips))
                except Exception as exc:
                    results.append({"status": "FAILED", "video": str(video), "error": str(exc)})
            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("GameAIEditor")
        self.resize(980, 700)
        self.videos: list[Path] = []
        default_profile = load_game_profile(Path("config/games/arma_reforger.json"))
        self.thread: QThread | None = None
        self.worker: AnalysisWorker | None = None

        central = QWidget()
        root = QVBoxLayout(central)
        self.setCentralWidget(central)

        header = QHBoxLayout()
        header.addWidget(QLabel("GameAIEditor"))
        self.add_files_button = QPushButton("+ Add Videos")
        self.add_folder_button = QPushButton("+ Add Folder")
        self.start_button = QPushButton("START ANALYSIS")
        header.addStretch()
        header.addWidget(self.add_files_button)
        header.addWidget(self.add_folder_button)
        header.addWidget(self.start_button)
        root.addLayout(header)

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
        root.addWidget(settings)

        self.queue = QListWidget()
        root.addWidget(QLabel("Queue"))
        root.addWidget(self.queue, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.stage_label = QLabel("Ready")
        root.addWidget(self.stage_label)
        root.addWidget(self.progress)

        self.add_files_button.clicked.connect(self.add_files)
        self.add_folder_button.clicked.connect(self.add_folder)
        self.start_button.clicked.connect(self.start_analysis)
        self.provider_combo.currentTextChanged.connect(self._provider_defaults)

    def _provider_defaults(self, provider: str) -> None:
        defaults = {
            "ollama": "http://localhost:11434",
            "lm_studio": "http://localhost:1234/v1",
            "openrouter": "https://openrouter.ai/api/v1",
            "custom": "http://localhost:8000/v1",
        }
        self.base_url_edit.setText(defaults[provider])

    def _append_videos(self, paths: list[Path]) -> None:
        known = {str(path.resolve()) for path in self.videos}
        for path in paths:
            if path.suffix.casefold() in SUPPORTED_EXTENSIONS and str(path.resolve()) not in known:
                self.videos.append(path)
                item = QListWidgetItem(f"{path.name}    Waiting")
                item.setData(32, str(path))
                self.queue.addItem(item)
                known.add(str(path.resolve()))

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
        self.thread = QThread(self)
        self.worker = AnalysisWorker(
            self.videos,
            Path(self.game_combo.currentData()),
            {
                "provider": self.provider_combo.currentText(),
                "model": self.model_edit.text(),
                "base_url": self.base_url_edit.text(),
                "api_key": self.api_key_edit.text() or None,
            },
            self.clip_count.value(),
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.item_progress.connect(self._update_item)
        self.worker.progress.connect(self._update_progress)
        self.worker.finished.connect(self._analysis_finished)
        self.worker.failed.connect(self._analysis_failed)
        self.thread.start()

    @Slot(int, str, str)
    def _update_item(self, index: int, stage: str, status: str) -> None:
        if item := self.queue.item(index):
            item.setText(f"{self.videos[index].name}    {stage}: {status}")

    @Slot(str, str, dict)
    def _update_progress(self, stage: str, status: str, details: dict) -> None:
        self.stage_label.setText(f"{stage}: {status}")
        if details.get("window") and details.get("total"):
            self.progress.setValue(int(100 * details["window"] / details["total"]))

    @Slot(list)
    def _analysis_finished(self, results: list) -> None:
        self.progress.setValue(100)
        self.stage_label.setText(f"Completed: {sum(item.get('status') == 'SUCCESS' for item in results)} / {len(results)}")
        self._stop_worker()

    @Slot(str)
    def _analysis_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Analysis failed", message)
        self._stop_worker()

    def _stop_worker(self) -> None:
        self.start_button.setEnabled(True)
        if self.thread:
            self.thread.quit()
            self.thread.wait()
        self.worker = None
        self.thread = None


def run_desktop_app() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()