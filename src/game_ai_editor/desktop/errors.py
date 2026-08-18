"""User-facing error UX for the desktop application."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class ErrorPresentation:
    title: str
    description: str
    action: str | None = None
    technical: str | None = None


ERROR_PRESENTATIONS: dict[str, ErrorPresentation] = {
    "VISION_PROVIDER_OFFLINE": ErrorPresentation(
        title="Vision provider is offline",
        description="The local AI service is not responding. Start it or switch provider in Settings.",
        action="Retry",
    ),
    "VISION_MODEL_MISSING": ErrorPresentation(
        title="Vision model is missing",
        description="The configured model is not available locally. Download it from the AI Engine tab.",
        action="Settings",
    ),
    "OLLAMA_NOT_INSTALLED": ErrorPresentation(
        title="Ollama is not installed",
        description="Install Ollama or enable degraded mode to analyse without local AI.",
        action="Continue without AI",
    ),
    "OLLAMA_PULL_FAILED": ErrorPresentation(
        title="Model download failed",
        description="Could not download the model. Check your connection and disk space, then retry.",
        action="Retry",
    ),
    "VISION_TIMEOUT": ErrorPresentation(
        title="Vision request timed out",
        description="The AI did not respond in time. Reduce scene count or restart the service, then retry.",
        action="Retry",
    ),
    "INVALID_VIDEO": ErrorPresentation(
        title="Video not found or invalid",
        description="Check the selected file path and that it is a supported video format.",
        action="Retry",
    ),
    "FFMPEG_ERROR": ErrorPresentation(
        title="Video processing failed",
        description="FFmpeg reported an error. Check the file and try again.",
        action="Retry",
    ),
    "QC_FAILED": ErrorPresentation(
        title="Quality check failed",
        description="The rendered montage did not pass internal quality checks.",
        action="Retry",
    ),
    "SOURCE_CHANGED": ErrorPresentation(
        title="Source video changed",
        description="The video no longer matches the existing analysis session. Re-add it to start fresh.",
        action="Retry",
    ),
    "CONFIGURATION_CHANGED": ErrorPresentation(
        title="Analysis settings changed",
        description="Current settings do not match the existing session. Use a new session to apply them.",
        action="Retry",
    ),
    "JOB_CANCELLED": ErrorPresentation(
        title="Analysis cancelled",
        description="The analysis was cancelled before it finished.",
        action="Retry",
    ),
}


class ErrorDialog(QDialog):
    def __init__(
        self,
        presentation: ErrorPresentation,
        error_code: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(presentation.title)
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>{presentation.title}</b>"))
        layout.addWidget(QLabel(presentation.description))

        self.action_button: QPushButton | None = None
        self.continue_button: QPushButton | None = None
        self.cancel_without_ai = False
        if presentation.action:
            self.action_button = QPushButton(presentation.action)
            layout.addWidget(self.action_button)
            if error_code == "OLLAMA_NOT_INSTALLED":
                self.continue_button = QPushButton("Continue without AI")
                self.continue_button.clicked.connect(self._continue_without_ai)
                layout.addWidget(self.continue_button)

        if presentation.technical:
            details = QPlainTextEdit()
            details.setReadOnly(True)
            details.setPlainText(presentation.technical)
            layout.addWidget(details)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _continue_without_ai(self) -> None:
        self.cancel_without_ai = True
        self.accept()


class ErrorPresenter:
    def __init__(self, parent: QWidget | None = None) -> None:
        self.parent = parent
        self.last_error_code: str | None = None

    def present(
        self,
        error_code: str | None,
        technical_message: str | None = None,
        *,
        on_action: Callable[[], None] | None = None,
        on_continue_without_ai: Callable[[], None] | None = None,
    ) -> bool:
        presentation = ERROR_PRESENTATIONS.get(error_code or "") or ErrorPresentation(
            title="Unexpected error",
            description=technical_message or "An unknown error occurred.",
            technical=technical_message,
        )
        self.last_error_code = error_code
        dialog = ErrorDialog(presentation, error_code=error_code, parent=self.parent)
        if dialog.action_button and on_action:

            def _on_action_clicked() -> None:
                dialog.accept()
                on_action()

            dialog.action_button.clicked.connect(_on_action_clicked)
        if dialog.cancel_without_ai and on_continue_without_ai:
            return True
        dialog.exec()
        return dialog.cancel_without_ai

    @classmethod
    def presentation_for(cls, error_code: str) -> ErrorPresentation:
        return ERROR_PRESENTATIONS.get(error_code, ErrorPresentation(title="Unexpected error", description=""))
