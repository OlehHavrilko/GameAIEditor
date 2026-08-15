# Development

The repository contains a production MVP with one canonical execution path: `ProductionOrchestrator`. Keep media, frames, model files, `work/`, caches, previews, build outputs, and rendered videos out of Git.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Fast validation:

```powershell
pytest -q
.venv\Scripts\python.exe -c "from game_ai_editor.desktop.app import MainWindow; print('ui-import-ok')"
.venv\Scripts\python.exe -m game_ai_editor system-status
.venv\Scripts\python.exe -m game_ai_editor runtime-status
```

The synthetic orchestration E2E uses a mock Vision provider and real FFmpeg/QC. A real Ollama smoke test is manual-only and should use a short video only.

## Packaging

PyInstaller is optional for development. See [PACKAGING.md](PACKAGING.md) for the one-directory Windows build and its external FFmpeg/Ollama runtime assumptions.