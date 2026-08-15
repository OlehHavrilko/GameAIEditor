from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DiagnosticCheck:
    name: str
    status: str
    value: str
    detail: str = ""


def collect_system_diagnostics() -> dict[str, Any]:
    checks = [
        DiagnosticCheck("OS", "READY", platform.platform()),
        DiagnosticCheck("Python", "READY" if sys.version_info >= (3, 11) else "WARNING", platform.python_version()),
        _command_check("FFmpeg", "ffmpeg", ["-version"]),
        _command_check("FFprobe", "ffprobe", ["-version"]),
        _memory_check(),
        _gpu_check(),
    ]
    return {
        "checks": [asdict(check) for check in checks],
        "ready": all(check.status != "ERROR" for check in checks),
        "platform": platform.system(),
        "cpu": platform.processor() or platform.machine(),
    }


def _command_check(name: str, executable: str, args: list[str]) -> DiagnosticCheck:
    path = shutil.which(executable)
    if not path:
        return DiagnosticCheck(name, "ERROR", "Not found", f"{executable} is not available on PATH.")
    try:
        result = subprocess.run([path, *args], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return DiagnosticCheck(name, "ERROR", "Unavailable", str(exc))
    if result.returncode != 0:
        return DiagnosticCheck(name, "ERROR", "Failed", result.stderr.strip())
    first_line = (result.stdout or result.stderr).splitlines()[0] if (result.stdout or result.stderr) else path
    return DiagnosticCheck(name, "READY", first_line[:160])


def _memory_check() -> DiagnosticCheck:
    try:
        import psutil  # type: ignore
    except ImportError:
        return DiagnosticCheck("RAM", "UNKNOWN", "Unavailable", "Install psutil for RAM diagnostics.")
    total_gb = psutil.virtual_memory().total / (1024 ** 3)
    available_gb = psutil.virtual_memory().available / (1024 ** 3)
    status = "READY" if available_gb >= 4 else "WARNING"
    return DiagnosticCheck("RAM", status, f"{available_gb:.1f} GB available / {total_gb:.1f} GB total")


def _gpu_check() -> DiagnosticCheck:
    try:
        import torch  # type: ignore
    except ImportError:
        return DiagnosticCheck("GPU", "UNKNOWN", "Unavailable", "Torch is not installed.")
    try:
        if not torch.cuda.is_available():
            return DiagnosticCheck("GPU", "WARNING", "CPU mode", "CUDA GPU was not detected.")
        device = torch.cuda.get_device_properties(0)
        memory_gb = device.total_memory / (1024 ** 3)
        return DiagnosticCheck("GPU", "READY", f"{device.name}, {memory_gb:.1f} GB VRAM")
    except Exception as exc:
        return DiagnosticCheck("GPU", "UNKNOWN", "Unavailable", str(exc))