from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable
from urllib import error, request


def get_python_executable() -> str:
    """Return the interpreter running the current Game AI Editor process."""
    return sys.executable


class RuntimeState(StrEnum):
    NOT_INSTALLED = "NOT_INSTALLED"
    INSTALLED_STOPPED = "INSTALLED_STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    READY = "READY"
    MODEL_MISSING = "MODEL_MISSING"
    MODEL_DOWNLOADING = "MODEL_DOWNLOADING"
    ERROR = "ERROR"
    EXTERNAL_INSTANCE = "EXTERNAL_INSTANCE"


@dataclass(frozen=True)
class RuntimeSnapshot:
    state: RuntimeState
    runtime_name: str
    base_url: str
    model: str
    installed: bool
    healthy: bool
    model_available: bool
    externally_managed: bool
    executable_path: str | None = None
    pid: int | None = None
    detail: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    download_percent: float | None = None
    command: list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["state"] = str(self.state)
        return payload


ProgressCallback = Callable[[RuntimeSnapshot], None]


class OllamaRuntimeManager:
    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model: str = "qwen3-vl:8b-instruct",
        timeout_seconds: float = 5.0,
        launch_command: list[str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.launch_command = launch_command
        self._owned_process: subprocess.Popen[str] | None = None
        self._download_process: subprocess.Popen[str] | None = None
        self._download_cancel = threading.Event()

    def detect(self) -> RuntimeSnapshot:
        executable = self._resolve_executable()
        owned_process = self._owned_process
        owned_running = owned_process is not None and owned_process.poll() is None

        if owned_running:
            if not self._healthcheck():
                return RuntimeSnapshot(
                    state=RuntimeState.STARTING,
                    runtime_name="Ollama",
                    base_url=self.base_url,
                    model=self.model,
                    installed=bool(executable),
                    healthy=False,
                    model_available=False,
                    externally_managed=False,
                    executable_path=executable,
                    pid=owned_process.pid,
                    detail="Waiting for local Ollama service to become ready.",
                    command=self._command(),
                )
            return self._ready_snapshot(executable, externally_managed=False, pid=owned_process.pid)

        if self._healthcheck():
            return self._ready_snapshot(executable, externally_managed=True, pid=None)

        if not executable:
            return RuntimeSnapshot(
                state=RuntimeState.NOT_INSTALLED,
                runtime_name="Ollama",
                base_url=self.base_url,
                model=self.model,
                installed=False,
                healthy=False,
                model_available=False,
                externally_managed=False,
                detail="Ollama executable was not found on PATH.",
                error_code="OLLAMA_NOT_INSTALLED",
            )

        return RuntimeSnapshot(
            state=RuntimeState.INSTALLED_STOPPED,
            runtime_name="Ollama",
            base_url=self.base_url,
            model=self.model,
            installed=True,
            healthy=False,
            model_available=False,
            externally_managed=False,
            executable_path=executable,
            detail="Ollama is installed but the service is not responding.",
            command=self._command(),
        )

    def start(self, wait_seconds: float = 20.0) -> RuntimeSnapshot:
        snapshot = self.detect()
        if snapshot.state in {RuntimeState.READY, RuntimeState.MODEL_MISSING, RuntimeState.EXTERNAL_INSTANCE}:
            return snapshot
        if snapshot.state == RuntimeState.NOT_INSTALLED:
            return snapshot

        command = self._command()
        try:
            self._owned_process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError as exc:
            return RuntimeSnapshot(
                state=RuntimeState.ERROR,
                runtime_name="Ollama",
                base_url=self.base_url,
                model=self.model,
                installed=bool(snapshot.installed),
                healthy=False,
                model_available=False,
                externally_managed=False,
                executable_path=snapshot.executable_path,
                detail="Failed to start Ollama service.",
                error_code="OLLAMA_START_FAILED",
                error_message=str(exc),
                command=command,
            )

        started_at = time.monotonic()
        while time.monotonic() - started_at <= wait_seconds:
            current = self.detect()
            if current.state in {RuntimeState.READY, RuntimeState.MODEL_MISSING}:
                return current
            if self._owned_process and self._owned_process.poll() is not None:
                return RuntimeSnapshot(
                    state=RuntimeState.ERROR,
                    runtime_name="Ollama",
                    base_url=self.base_url,
                    model=self.model,
                    installed=True,
                    healthy=False,
                    model_available=False,
                    externally_managed=False,
                    executable_path=snapshot.executable_path,
                    detail="Ollama exited before becoming ready.",
                    error_code="OLLAMA_EXITED_EARLY",
                    command=command,
                )
            time.sleep(0.25)

        return RuntimeSnapshot(
            state=RuntimeState.STARTING,
            runtime_name="Ollama",
            base_url=self.base_url,
            model=self.model,
            installed=True,
            healthy=False,
            model_available=False,
            externally_managed=False,
            executable_path=snapshot.executable_path,
            pid=self._owned_process.pid if self._owned_process else None,
            detail="Ollama is still starting.",
            command=command,
        )

    def stop(self, wait_seconds: float = 5.0) -> RuntimeSnapshot:
        process = self._owned_process
        if process is None or process.poll() is not None:
            self._owned_process = None
            return self.detect()
        process.terminate()
        try:
            process.wait(timeout=wait_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=wait_seconds)
        finally:
            self._owned_process = None
        return self.detect()

    def install_model(self, progress: ProgressCallback | None = None) -> RuntimeSnapshot:
        self._download_cancel.clear()
        executable = self._resolve_executable()
        if not executable:
            return RuntimeSnapshot(
                state=RuntimeState.NOT_INSTALLED,
                runtime_name="Ollama",
                base_url=self.base_url,
                model=self.model,
                installed=False,
                healthy=False,
                model_available=False,
                externally_managed=False,
                error_code="OLLAMA_NOT_INSTALLED",
                detail="Ollama executable was not found on PATH.",
            )

        command = [executable, "pull", self.model]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self._download_process = process
        last_snapshot = RuntimeSnapshot(
            state=RuntimeState.MODEL_DOWNLOADING,
            runtime_name="Ollama",
            base_url=self.base_url,
            model=self.model,
            installed=True,
            healthy=self._healthcheck(),
            model_available=False,
            externally_managed=self._owned_process is None,
            executable_path=executable,
            detail="Downloading model via ollama pull.",
            command=command,
        )
        if progress:
            progress(last_snapshot)

        if process.stdout is not None:
            for raw_line in process.stdout:
                if self._download_cancel.is_set():
                    process.terminate()
                    process.wait(timeout=5)
                    self._download_process = None
                    return RuntimeSnapshot(
                        state=RuntimeState.MODEL_MISSING,
                        runtime_name="Ollama",
                        base_url=self.base_url,
                        model=self.model,
                        installed=True,
                        healthy=self._healthcheck(),
                        model_available=False,
                        externally_managed=self._owned_process is None,
                        executable_path=executable,
                        detail="Model download cancelled.",
                        error_code="JOB_CANCELLED",
                        command=command,
                    )
                line = raw_line.strip()
                percent = _parse_progress_percent(line)
                last_snapshot = RuntimeSnapshot(
                    state=RuntimeState.MODEL_DOWNLOADING,
                    runtime_name="Ollama",
                    base_url=self.base_url,
                    model=self.model,
                    installed=True,
                    healthy=self._healthcheck(),
                    model_available=False,
                    externally_managed=self._owned_process is None,
                    executable_path=executable,
                    detail=line or "Downloading model via ollama pull.",
                    download_percent=percent,
                    command=command,
                )
                if progress:
                    progress(last_snapshot)

        return_code = process.wait()
        self._download_process = None
        if self._download_cancel.is_set():
            return RuntimeSnapshot(
                state=RuntimeState.MODEL_MISSING,
                runtime_name="Ollama",
                base_url=self.base_url,
                model=self.model,
                installed=True,
                healthy=self._healthcheck(),
                model_available=False,
                externally_managed=self._owned_process is None,
                executable_path=executable,
                detail="Model download cancelled.",
                error_code="JOB_CANCELLED",
                command=command,
            )
        if return_code != 0:
            return RuntimeSnapshot(
                state=RuntimeState.ERROR,
                runtime_name="Ollama",
                base_url=self.base_url,
                model=self.model,
                installed=True,
                healthy=self._healthcheck(),
                model_available=False,
                externally_managed=self._owned_process is None,
                executable_path=executable,
                detail="Model download failed.",
                error_code="OLLAMA_PULL_FAILED",
                error_message=last_snapshot.detail,
                command=command,
            )
        return self.detect()

    def cancel_model_download(self, wait_seconds: float = 5.0) -> bool:
        process = self._download_process
        if process is None or process.poll() is not None:
            return False
        self._download_cancel.set()
        process.terminate()
        try:
            process.wait(timeout=wait_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=wait_seconds)
        return True

    def _ready_snapshot(self, executable: str | None, *, externally_managed: bool, pid: int | None) -> RuntimeSnapshot:
        models = self._tags()
        model_available = self.model in models
        if not model_available:
            return RuntimeSnapshot(
                state=RuntimeState.MODEL_MISSING,
                runtime_name="Ollama",
                base_url=self.base_url,
                model=self.model,
                installed=bool(executable),
                healthy=True,
                model_available=False,
                externally_managed=externally_managed,
                executable_path=executable,
                pid=pid,
                detail="Ollama is running but the requested model is missing.",
                error_code="VISION_MODEL_MISSING",
                command=self._command(),
            )
        return RuntimeSnapshot(
            state=RuntimeState.EXTERNAL_INSTANCE if externally_managed else RuntimeState.READY,
            runtime_name="Ollama",
            base_url=self.base_url,
            model=self.model,
            installed=bool(executable),
            healthy=True,
            model_available=True,
            externally_managed=externally_managed,
            executable_path=executable,
            pid=pid,
            detail="Ollama is ready." if not externally_managed else "Using an externally managed Ollama instance.",
            command=self._command(),
        )

    def _resolve_executable(self) -> str | None:
        if self.launch_command:
            candidate = self.launch_command[0]
            if Path(candidate).exists() or shutil.which(candidate):
                return str(Path(candidate)) if Path(candidate).exists() else shutil.which(candidate)
        return shutil.which("ollama")

    def _command(self) -> list[str]:
        if self.launch_command:
            return list(self.launch_command)
        executable = self._resolve_executable() or "ollama"
        return [executable, "serve"]

    def _healthcheck(self) -> bool:
        try:
            payload = _http_json(f"{self.base_url}/api/tags", timeout=self.timeout_seconds)
        except RuntimeError:
            return False
        return isinstance(payload.get("models", []), list)

    def _tags(self) -> set[str]:
        try:
            payload = _http_json(f"{self.base_url}/api/tags", timeout=self.timeout_seconds)
        except RuntimeError:
            return set()
        return {
            str(item.get("name", ""))
            for item in payload.get("models", [])
            if isinstance(item, dict)
        }


def _http_json(url: str, *, timeout: float) -> dict[str, Any]:
    http_request = request.Request(url, method="GET")
    try:
        with request.urlopen(http_request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (error.URLError, OSError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(str(exc)) from exc


def _parse_progress_percent(line: str) -> float | None:
    tokens = line.replace("%", " %").split()
    for index, token in enumerate(tokens):
        if token == "%" and index > 0:
            try:
                return float(tokens[index - 1])
            except ValueError:
                return None
    return None
